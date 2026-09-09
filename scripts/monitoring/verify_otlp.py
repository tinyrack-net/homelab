#!/usr/bin/env python3
"""Replay real /metrics fixtures through the rendered Alloy OTLP destination.

Requires Docker, PyYAML, prometheus-client and opentelemetry-proto.
All containers bind only to localhost and are removed on exit. Nothing is sent
to production. Pass --outage-seconds 300 to exercise the five-minute outage.
"""
import argparse
import gzip
import json
import math
import re
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from prometheus_client.parser import text_string_to_metric_families


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True).strip()


def remove_block(text, token):
    start = text.index(token)
    opening = text.index('{', start)
    level = 1
    end = opening + 1
    while level:
        level += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[:start] + text[end:]


def key(name, labels):
    # Scrape/OTLP transport attributes are not application labels. Keep only
    # original label names when comparing; histogram boundaries are numeric.
    return name, tuple(sorted((k, str(float(v)) if k in ('le', 'quantile') else str(v))
                              for k, v in labels.items() if v != ''))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rendered-alloy', type=Path, required=True)
    parser.add_argument('--release', type=Path, required=True)
    parser.add_argument('--k3s-fixture', type=Path, required=True)
    parser.add_argument('--node-fixture', type=Path, required=True)
    parser.add_argument('--outage-seconds', type=int, default=0)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    values = yaml.safe_load(args.release.read_text())['spec']['values']
    fixtures = {'/k3s': args.k3s_fixture.read_bytes(), '/node': args.node_fixture.read_bytes()}
    expected, label_names = {}, {}
    nan_samples = 0
    fixture_node = None
    for origin, body in fixtures.items():
        raw_names = {line.split('{', 1)[0].split(' ', 1)[0]
                     for line in body.decode().splitlines() if line and not line.startswith('#')}
        for family in text_string_to_metric_families(body.decode()):
            for sample in family.samples:
                if origin == '/k3s' and sample.name == 'kubelet_node_name':
                    fixture_node = sample.labels['node']
                # VictoriaMetrics omits NaN-only samples. They contain no
                # measurement; account for them separately from finite values.
                if math.isnan(sample.value):
                    nan_samples += 1
                    continue
                # prometheus-client adds _total to legacy counter names while
                # parsing; compare the actual exposed names, not that rewrite.
                name = sample.name
                if name not in raw_names and name.endswith('_total') and name[:-6] in raw_names:
                    name = name[:-6]
                expected[(origin[1:], *key(name, sample.labels))] = sample.value
                label_names.setdefault(name, set()).update(sample.labels)

    # Exercise path identity when general metrics and cAdvisor share job/node.
    # These probes are checked separately from the captured input series.
    for endpoint, source in [('/k3s', 'general'), ('/cadvisor', 'cadvisor'), ('/resource', 'resource')]:
        fixtures[endpoint] = fixtures.get(endpoint, b'').rstrip() + (
            '\n# TYPE otlp_path_probe gauge\notlp_path_probe{source="' + source + '"} 1\n').encode()

    state = {'mode': 'ok', 'requests': 0, 'rejected': 0, 'max_points': 0,
             'max_rss': 0, 'max_queue_bytes': 0, 'last_success': 0, 'errors': [],
             'input_nan_samples': nan_samples, 'failure_counters': {}, 'phases': []}
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *unused):
            pass

        def do_GET(self):
            data = fixtures.get(self.path)
            self.send_response(200 if data else 404)
            self.send_header('Content-Type', 'text/plain; version=0.0.4')
            self.end_headers()
            if data:
                self.wfile.write(data)

        def do_POST(self):
            body = self.rfile.read(int(self.headers['Content-Length']))
            if self.headers.get('Content-Encoding') == 'gzip':
                body = gzip.decompress(body)
            req = ExportMetricsServiceRequest.FromString(body)
            points = sum(len(getattr(m, m.WhichOneof('data')).data_points)
                         for rm in req.resource_metrics for sm in rm.scope_metrics
                         for m in sm.metrics if m.WhichOneof('data'))
            with lock:
                state['requests'] += 1
                state['max_points'] = max(state['max_points'], points)
                mode = state['mode']
                if mode == 'reject':
                    state['rejected'] += 1
            if mode == 'reject':
                self.send_response(503)
                self.end_headers()
                return
            if mode == 'slow':
                time.sleep(3)
            try:
                request = urllib.request.Request('http://127.0.0.1:19429/opentelemetry/v1/metrics',
                                                 data=body, headers={'Content-Type': 'application/x-protobuf'})
                with urllib.request.urlopen(request, timeout=20) as response:
                    response.read()
                with lock:
                    state['last_success'] = time.monotonic()
                self.send_response(200)
                self.end_headers()
            except Exception as exc:
                with lock:
                    state['errors'].append(str(exc))
                self.send_response(502)
                self.end_headers()

    server = ThreadingHTTPServer(('127.0.0.1', 19428), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    containers = []
    try:
        vm = docker('run', '-d', '--rm', '--network=host', '--memory=1g',
                    'victoriametrics/victoria-metrics:v1.150.0', '-httpListenAddr=127.0.0.1:19429',
                    '-storageDataPath=/tmp/vm-data', '-opentelemetry.usePrometheusNaming=true',
                    '-retentionPeriod=1d')
        containers.append(vm)
        text = args.rendered_alloy.read_text()
        text = text[text.index('// Destination: telemetry (otlp)'):]
        text = remove_block(text, 'otelcol.auth.bearer "telemetry"')
        text = remove_block(text, 'remote.kubernetes.secret "telemetry"')
        start = text.index('  client {', text.index('otelcol.exporter.otlphttp "telemetry"'))
        text = text[:start] + remove_block(text[start:], '  client {')
        text = text.replace('otelcol.exporter.otlphttp "telemetry" {',
                            'otelcol.exporter.otlphttp "telemetry" {\n'
                            '  client {\n    endpoint = "http://127.0.0.1:19428"\n    timeout = "30s"\n  }')
        text = re.sub(r'(metrics_endpoint|logs_endpoint|traces_endpoint) = "[^"]+"',
                      r'\1 = "http://127.0.0.1:19428/metrics"', text)
        rules = values['clusterMetrics']['kubelet']['extraMetricProcessingRules']
        prefix = '''prometheus.scrape "k3s" {
  targets = [{"__address__" = "127.0.0.1:19428", "__metrics_path__" = "/k3s", "instance" = "k3s-fixture", "node" = "fixture"}]
  job_name = "kubelet"
  scrape_interval = "30s"
  scrape_timeout = "10s"
  forward_to = [prometheus.relabel.k3s.receiver]
}
prometheus.relabel "k3s" {
  forward_to = [otelcol.receiver.prometheus.telemetry.receiver]
''' + rules + '\n}\n' + '''prometheus.scrape "node" {
  targets = [{"__address__" = "127.0.0.1:19428", "__metrics_path__" = "/node", "instance" = "node-fixture"}]
  job_name = "node-exporter"
  scrape_interval = "30s"
  forward_to = [otelcol.receiver.prometheus.telemetry.receiver]
}
'''
        for endpoint, section, job in [('cadvisor', 'cadvisor', 'kubelet'),
                                       ('resource', 'kubeletResource', 'integrations/kubernetes/resources')]:
            path_rules = values['clusterMetrics'][section]['extraMetricProcessingRules']
            prefix += '\n'.join([
                f'prometheus.scrape "{endpoint}" {{',
                '  targets = [{"__address__" = "127.0.0.1:19428", "__metrics_path__" = "/' + endpoint + '", "instance" = "k3s-fixture", "node" = "fixture"}]',
                f'  job_name = "{job}"', '  scrape_interval = "30s"',
                f'  forward_to = [prometheus.relabel.{endpoint}.receiver]', '}',
                f'prometheus.relabel "{endpoint}" {{', path_rules,
                '  forward_to = [otelcol.receiver.prometheus.telemetry.receiver]', '}', ''])
        with tempfile.TemporaryDirectory(prefix='alloy-otlp-replay-') as directory:
            config = Path(directory) / 'config.alloy'
            assert fixture_node, 'K3s fixture must contain kubelet_node_name'
            prefix = prefix.replace('"node" = "fixture"', '"node" = ' + json.dumps(fixture_node))
            config.write_text(prefix + text)
            config.chmod(0o644)
            Path(directory).chmod(0o755)
            alloy = docker('run', '-d', '--rm', '--network=host', '--memory=2g', '--cpus=1',
                           '-v', str(config)+':/etc/alloy/config.alloy:ro', 'grafana/alloy:v1.18.1',
                           'run', '--server.http.listen-addr=127.0.0.1:19430',
                           '--storage.path=/tmp/alloy', '/etc/alloy/config.alloy')
            containers.append(alloy)

            def observe(seconds, mode):
                state['mode'] = mode
                print('phase', mode, seconds, flush=True)
                end = time.monotonic() + seconds
                while time.monotonic() < end:
                    time.sleep(5)
                    try:
                        data = urllib.request.urlopen('http://127.0.0.1:19430/metrics', timeout=15).read().decode()
                    except Exception:
                        raise AssertionError('Alloy became unavailable: ' + docker('logs', alloy)[-2000:])
                    queue_sizes = []
                    for line in data.splitlines():
                        if line.startswith('alloy_resources_process_resident_memory_bytes '):
                            state['max_rss'] = max(state['max_rss'], float(line.split()[-1]))
                        if line.startswith('otelcol_exporter_queue_size{'):
                            queue_sizes.append(float(line.split()[-1]))
                        if re.match(r'otelcol_.*(?:failed|refused)_metric_points(?:_total)?\{', line):
                            metric, value = line.rsplit(' ', 1)
                            state['failure_counters'][metric] = float(value)
                    assert queue_sizes, 'Exporter queue telemetry missing'
                    state['queue_bytes'] = max(queue_sizes)
                    state['max_queue_bytes'] = max(state['max_queue_bytes'], state['queue_bytes'])
                    assert state['max_points'] <= 8192, state
                    assert state['max_queue_bytes'] <= 134217728, state
                    assert state['max_rss'] < 2 * 1024**3, state
                state['phases'].append({'mode': mode, 'seconds': seconds,
                                        'max_rss': state['max_rss'], 'max_queue_bytes': state['max_queue_bytes'],
                                        'failure_points': sum(state['failure_counters'].values())})

            observe(75, 'ok')
            query = urllib.parse.urlencode({'match[]': '{instance=~"(k3s|node)-fixture"}'})
            exported = urllib.request.urlopen('http://127.0.0.1:19429/api/v1/export?' + query, timeout=30).read().decode()
            args.output.with_suffix('.export.jsonl').write_text(exported)
            actual, jobs, probe_paths = {}, {}, {}
            for line in exported.splitlines():
                record = json.loads(line)
                metric = record['metric']
                name = metric['__name__']
                if name == 'otlp_path_probe':
                    probe_paths[metric['source']] = (metric.get('job'), metric.get('metrics_path'))
                if name not in label_names:
                    continue
                labels = {k: metric[k] for k in label_names[name] if k in metric}
                origin = metric['instance'].removesuffix('-fixture')
                actual[(origin, *key(name, labels))] = float(record['values'][-1])
                jobs.setdefault((origin, name), set()).add(metric.get('job'))
            missing = set(expected) - set(actual)
            different = [k for k in expected.keys() & actual.keys()
                         if not (math.isclose(expected[k], actual[k], rel_tol=1e-10, abs_tol=1e-12)
                                 or math.isnan(expected[k]) and math.isnan(actual[k]))]
            state['missing_series'] = len(missing)
            state['different_values'] = len(different)
            state['input_series'] = len(expected)
            state['output_series'] = len(actual)
            args.output.write_text(json.dumps(state, indent=2))
            assert not missing, list(sorted(missing))[:15]
            assert not different, different[:15]
            assert probe_paths == {'general': ('kubelet', '/metrics'),
                                   'cadvisor': ('kubelet', '/metrics/cadvisor'),
                                   'resource': ('integrations/kubernetes/resources', '/metrics/resource')}, probe_paths
            assert state['max_rss'] > 0 and state['max_points'] > 0
            for (origin, name), js in jobs.items():
                assert len(js) == 1, (name, js)
                if name.startswith('scheduler_'):
                    assert js == {'kube-scheduler'}, (name, js)
                if origin == 'k3s' and name.startswith(('apiserver_', 'rest_client_', 'workqueue_', 'go_', 'process_')):
                    assert js == {'apiserver'}, (name, js)
                if origin == 'node':
                    assert js == {'node-exporter'}, (name, js)
            print('preservation PASS', state['input_series'], flush=True)
            if args.outage_seconds:
                observe(30, 'slow')
                observe(args.outage_seconds, 'reject')
                resumed = time.monotonic()
                observe(90, 'ok')
                assert state['last_success'] > resumed
                assert state['rejected'] > 0
                assert state['queue_bytes'] == 0, 'Queue did not drain after receiver recovery'
            state['container_state'] = json.loads(docker('inspect', alloy))[0]['State']
            assert not state['container_state']['OOMKilled']
            assert state['container_state']['Running']
            state['alloy_logs_tail'] = docker('logs', '--tail=20', alloy)
            args.output.write_text(json.dumps(state, indent=2))
            print(json.dumps({k: v for k, v in state.items() if k != 'alloy_logs_tail'}, indent=2), flush=True)
    finally:
        for container in reversed(containers):
            subprocess.run(['docker', 'rm', '-f', container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        server.shutdown()


if __name__ == '__main__':
    main()
