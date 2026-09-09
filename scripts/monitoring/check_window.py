#!/usr/bin/env python3
"""Read-only rollout check using raw VictoriaMetrics timestamps and Kubernetes.

Remote contexts use existing credentials over local SSH tunnels (16443 tinyrack,
16444 mail-server). No resources are mutated. The observation window must start
after the collector has loaded its intended configuration.
"""
import argparse
import json
import subprocess
import time
import urllib.parse
from pathlib import Path


def kubectl(context, *args):
    cmd = ['kubectl', '--context', context, '--request-timeout=30s']
    if context in ('tinyrack', 'mail-server'):
        port = 16443 if context == 'tinyrack' else 16444
        cmd += [f'--server=https://127.0.0.1:{port}']
    return subprocess.check_output(cmd + list(args), text=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cluster', action='append', required=True, choices=['homelab', 'tinyrack', 'mail-server'])
    parser.add_argument('--start', type=float, required=True, help='UTC epoch seconds after rollout')
    parser.add_argument('--end', type=float, default=None)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    end = args.end or time.time()
    seconds = end - args.start
    assert seconds > 0
    base = '/api/v1/namespaces/monitoring-system/services/vmsingle-monitoring-victoria-metrics-k8s-stack:8428/proxy'
    report = {'start': args.start, 'end': end, 'clusters': {}, 'failures': []}
    baseline = json.loads(args.baseline.read_text()) if args.baseline else None

    def query(expr):
        uri = base + '/api/v1/query?' + urllib.parse.urlencode({'query': expr, 'time': end})
        result = json.loads(kubectl('homelab', 'get', '--raw', uri))
        assert result['status'] == 'success', result
        return result['data']['result']

    for cluster in args.cluster:
        item = report['clusters'][cluster] = {'series': [], 'alloy': []}
        pods = json.loads(kubectl(cluster, '-n', 'monitoring-system', 'get', 'pods', '-o', 'json'))
        for pod in pods['items']:
            if not pod['metadata']['name'].startswith('monitoring-alloy-'):
                continue
            for container in pod['status'].get('containerStatuses', []):
                if container['name'] != 'alloy':
                    continue
                item['alloy'].append({'uid': pod['metadata']['uid'], 'pod': pod['metadata']['name'],
                                      'restarts': container['restartCount'], 'ready': container['ready'],
                                      'lastTermination': container.get('lastState', {}).get('terminated')})
        if not item['alloy'] or not all(a['ready'] for a in item['alloy']):
            report['failures'].append(cluster + ': Alloy unavailable')
        if baseline:
            previous = baseline['clusters'][cluster]['alloy']
            if {(a['uid'], a['restarts']) for a in previous} != {(a['uid'], a['restarts']) for a in item['alloy']}:
                report['failures'].append(cluster + ': Alloy restarted or pod changed')
        selectors = [f'node_cpu_seconds_total{{cluster="{cluster}",job="node-exporter",cpu="0",mode="idle"}}',
                     f'{{__name__=~"node_time_seconds|node_memory_MemTotal_bytes",cluster="{cluster}",job="node-exporter"}}']
        params = urllib.parse.urlencode({'match[]': selectors, 'start': args.start, 'end': end}, doseq=True)
        exported = kubectl('homelab', 'get', '--raw', base + '/api/v1/export?' + params)
        series = {}
        for line in exported.splitlines():
            row = json.loads(line)
            key = json.dumps(row['metric'], sort_keys=True)
            series.setdefault(key, set()).update(t / 1000 for t in row['timestamps'] if args.start <= t / 1000 <= end)
        names = set()
        for key, timestamps in series.items():
            metric = json.loads(key)
            names.add(metric['__name__'])
            ts = sorted(timestamps)
            edges = [args.start, *ts, end]
            max_gap = max(b-a for a,b in zip(edges, edges[1:]))
            detail = {'metric': metric, 'uniqueSamples': len(ts), 'maxGapSeconds': round(max_gap, 3)}
            item['series'].append(detail)
            if max_gap > 90 or len(ts) < int(seconds / 3600 * 114):
                report['failures'].append(cluster + ': sample coverage ' + metric['__name__'])
        if names != {'node_cpu_seconds_total', 'node_memory_MemTotal_bytes', 'node_time_seconds'}:
            report['failures'].append(cluster + ': representative series missing')
        window = f'{max(1, int(seconds))}s'
        failed = query(f'sum(increase({{__name__=~"otelcol_(exporter_(send|enqueue)_failed|receiver_refused|processor_refused)_metric_points_total",cluster="{cluster}"}}[{window}]))')
        item['failedMetricPoints'] = sum(float(r['value'][1]) for r in failed)
        if item['failedMetricPoints'] > 0:
            report['failures'].append(cluster + ': metric delivery failures')
        item['queueRatios'] = query(f'max by(cluster,instance,exporter,data_type,component_id,component_path)(otelcol_exporter_queue_size{{cluster="{cluster}"}}) / max by(cluster,instance,exporter,data_type,component_id,component_path)(otelcol_exporter_queue_capacity{{cluster="{cluster}"}})')
        if not item['queueRatios']:
            report['failures'].append(cluster + ': queue telemetry missing')
        if any(float(r['value'][1]) > .8 for r in item['queueRatios']):
            report['failures'].append(cluster + ': queue over 80%')
    report['insertTimeouts'] = query(f'sum(increase(vm_concurrent_insert_limit_timeout_total[{max(1, int(seconds))}s]))')
    if any(float(r['value'][1]) > 0 for r in report['insertTimeouts']):
        report['failures'].append('VictoriaMetrics insertion timeout')
    args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps({'minutes': round(seconds/60, 1), 'failures': report['failures'],
                      'samples': {c: [s['uniqueSamples'] for s in v['series']] for c,v in report['clusters'].items()}}))
    raise SystemExit(bool(report['failures']))


if __name__ == '__main__':
    main()
