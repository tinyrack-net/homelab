#!/usr/bin/env python3
"""Exercise production alert expressions against an isolated local VictoriaMetrics.

Run while verify_otlp.py is running. Writes only test_* series to localhost.
"""
import json
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import yaml


def main():
    base = 'http://127.0.0.1:19429'
    path = Path(__file__).resolve().parents[2] / 'infrastructure/base/monitoring/monitoring.stack.values.yaml'
    values = yaml.safe_load(path.read_text())
    rules = {r['uid']: r['data'][0]['model']['expr']
             for g in values['grafana']['alerting']['rules.yaml']['groups'] for r in g['rules']}
    end = int(time.time()) - 3600
    prefix = 'test_' + uuid.uuid4().hex + '_'
    samples = []
    for cluster, count, age in [('homelab', 10, 0), ('mail-server', 3, 0), ('tinyrack', 10, 150)]:
        for i in range(count):
            timestamp = end - age - i * 30
            samples.append(f'test_node_time_seconds{{cluster="{cluster}",job="node-exporter"}} {timestamp} {timestamp * 1000}')
    for instance, signal, size, capacity in [('a', 'metrics', 90, 100), ('a', 'logs', 10, 100), ('b', 'metrics', 90, 1000)]:
        labels = f'cluster="homelab",instance="{instance}",data_type="{signal}",exporter="otlp",component_id="x",component_path="/"'
        for metric, value in [('size', size), ('capacity', capacity)]:
            samples.append(f'test_otelcol_exporter_queue_{metric}{{{labels}}} {value} {end * 1000}')
    for cluster, value in [('homelab', 1), ('tinyrack', 0)]:
        samples.append(f'test_up{{cluster="{cluster}",job="kubelet",metrics_path="/metrics"}} {value} {end * 1000}')
    for timestamp, value in [(end - 60, 0), (end, 8192)]:
        samples.append(f'test_otelcol_exporter_enqueue_failed_metric_points_total{{cluster="mail-server",exporter="otlp"}} {value} {timestamp * 1000}')
    request = urllib.request.Request(base + '/api/v1/import/prometheus', data=('\n'.join(samples)+'\n').replace('test_', prefix).encode())
    urllib.request.urlopen(request).read()
    # Imported rows become queryable after the storage flush, independently of
    # the HTTP import acknowledgement.
    deadline = time.monotonic() + 30
    while True:
        params = urllib.parse.urlencode({'query': f'count({prefix}node_time_seconds)', 'time': end, 'nocache': '1'})
        ready = json.load(urllib.request.urlopen(base + '/api/v1/query?' + params))['data']['result']
        if ready and float(ready[0]['value'][1]) == 3:
            break
        assert time.monotonic() < deadline, ready
        time.sleep(1)

    def query(uid, at):
        expr = rules[uid].replace('node_time_seconds', prefix + 'node_time_seconds').replace('otelcol_', prefix + 'otelcol_').replace('up{', prefix + 'up{')
        params = urllib.parse.urlencode({'query': expr, 'time': at, 'nocache': '1'})
        response = json.load(urllib.request.urlopen(base + '/api/v1/query?' + params))
        assert response['status'] == 'success', response
        return [r['metric'] for r in response['data']['result'] if float(r['value'][1]) > 0]

    stale = query('node-telemetry-stale', end)
    assert {m['cluster'] for m in stale} == {'tinyrack'}, stale
    assert {m['cluster'] for m in query('node-telemetry-sparse', end)} == {'mail-server', 'tinyrack'}
    for uid in ['node-telemetry-stale', 'node-telemetry-sparse']:
        assert {m['cluster'] for m in query(uid, end + 1800)} == {'homelab', 'mail-server', 'tinyrack'}
    pressure = query('metrics-ingestion-pressure', end)
    assert len(pressure) == 1 and pressure[0]['instance'] == 'a' and pressure[0]['data_type'] == 'metrics', pressure
    assert {m['cluster'] for m in query('k3s-metrics-unreachable', end)} == {'mail-server', 'tinyrack'}
    assert {m['cluster'] for m in query('metrics-delivery-failure', end)} == {'mail-server'}
    print('PASS: healthy, stale, sparse, absent clusters; separate exporter queues and signals; failed scrapes and queue overflow')


if __name__ == '__main__':
    main()
