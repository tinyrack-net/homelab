# OTLP stability verification

The monitoring HelmRelease keeps OTLP and 30-second scrapes. K3s generic
`/metrics` is collected once per node through kubelet. cAdvisor, resource,
node-exporter, kube-state-metrics, CoreDNS, and the separate etcd endpoint remain.
There is no metric-name allowlist on the consolidated K3s scrape.

## Logical job contract

| K3s metric prefixes | Job |
| --- | --- |
| `apiserver_`, `apiextensions_`, `aggregator_`, `authentication_`, `authorization_`, `authenticated_`, `rest_client_` | `apiserver` |
| Shared `workqueue_`, `process_`, `go_` | `apiserver` |
| `scheduler_` | `kube-scheduler` |
| Explicit controller prefixes in `kubelet.extraMetricProcessingRules` | `kube-controller-manager` |
| Everything else, including the real scrape `up` | `kubelet` |

The shared process/queue families use `apiserver` because the provisioned API
Server dashboard references them under that job. They describe the shared K3s
process, not independent component processes. Audit on 2026-09-09 covered 41
dashboards (16 component panel queries and two API Server selectors) and 204 active recording/alert rules (38
component references). `rest_client_*` preserves `KubeClientErrors`; scheduler
histogram rules retain `job="kube-scheduler"`.

The six alerts for removed API/controller/scheduler scrape endpoints are disabled
by name in the stack values. `k3s-metrics-unreachable` checks the real consolidated
scrape instead. No synthetic component `up` series are generated. The vendored API Server dashboard
keeps its UID and panels; its cluster/instance selectors use
`apiserver_request_total` instead of the removed endpoint `up`. Explicit
`metrics_path` labels distinguish `/metrics`, `/metrics/resource`, and
`/metrics/cadvisor` through OTLP conversion. Node Exporter labels are unchanged.

## Reproduce the isolated replay

Install `requirements.txt` into a virtual environment. Render the HelmRelease's
`spec.values` with `k8s-monitoring` **4.5.0**, then extract `config.alloy` from its
collector ConfigMap. Validate it using:

```sh
docker run --rm -v /absolute/path/config.alloy:/tmp/config.alloy:ro \
  grafana/alloy:v1.18.1 validate /tmp/config.alloy
```

Capture read-only K3s `/metrics` and node-exporter `/metrics` responses into
temporary files; do not commit them. Run:

```sh
python scripts/monitoring/verify_otlp.py \
  --rendered-alloy /absolute/path/config.alloy \
  --release infrastructure/base/monitoring/monitoring.k8s-monitoring.helm-release.yaml \
  --k3s-fixture /absolute/path/k3s.prom \
  --node-fixture /absolute/path/node.prom \
  --outage-seconds 300 --output /tmp/replay.json
```

The test uses Docker Alloy **1.18.1** (2 GiB limit, 1 CPU) and VictoriaMetrics
**1.150.0**, with local-only listeners on 19428–19430. It copies the rendered
destination, substitutes only local endpoints/authentication, and uses the
actual K3s metric relabel rules. It compares finite input samples with stored
output values, including histogram buckets/sums/counts and original labels.
Empty labels are equivalent to absent labels in Prometheus. The parser's legacy
counter `_total` rewrite is reversed before comparison. NaN samples contain no
measurement and VictoriaMetrics omits them; their count is reported separately.

The scenarios cover healthy delivery, a slow receiver, five minutes of 503s,
and recovery. Assertions check a maximum of 8,192 OTLP points per request,
128 MiB per signal queue, RSS below 2 GiB, and a running container without OOM.
Queue overflow may discard data; failure counters are captured explicitly.
This is a memory queue, not a guarantee of lossless delivery during outages.

While the replay is running, execute `python scripts/monitoring/verify_alerts.py`.
It sends isolated `test_*` fixtures to the local VictoriaMetrics and checks
healthy, stale, sparse, completely absent clusters and independent instance /
signal queue ratios. It does not write production metrics.

## GitOps rollout and observation

Render all three repository paths before deployment:

```sh
kubectl kustomize infrastructure/base/monitoring >/dev/null
kubectl kustomize infrastructure/overlays/production >/dev/null
kubectl kustomize apps/overlays/production >/dev/null
```

Apply backend capacity/detection first, then homelab, tinyrack, mail-server with
30 minutes of observation each. Do not advance if restarts/OOM, dropped metrics,
insertion timeouts, growing queues, or label/query regressions appear. Validate
one hour across all clusters, then recheck at 24 hours. Inspect raw timestamps
(not query-range interpolated points): representative node CPU, memory, and time
series need at least 114 unique timestamps per hour and no gap over 90 seconds.
Old missing data cannot be reconstructed by this change.

Remote SSH is used for transport/read-only observation only. Existing local
kubeconfig credentials can access each API through a local SSH tunnel, without
changing host files, sudo policy, or Kubernetes resources. Deployments must use
GitOps; host configuration changes must use Ansible.

The read-only `check_window.py` checks a fixed post-rollout window, raw sample
coverage, Alloy pod/restart identity, metric failures, queue ratios, and insertion
timeouts. Capture a baseline after rollout and use the same start time for the
30-minute and 60-minute checks:

```sh
python scripts/monitoring/check_window.py --cluster homelab \
  --start <rollout-epoch-seconds> --output /tmp/homelab-baseline.json
python scripts/monitoring/check_window.py --cluster homelab \
  --start <rollout-epoch-seconds> --baseline /tmp/homelab-baseline.json \
  --output /tmp/homelab-window.json
```

Use repeated `--cluster` flags for the final all-cluster check. Exit status is
nonzero for any detected regression. A missing queue metric is a failure, not a
zero queue. A newly captured baseline may initially lack a flushed sample; retain
the report and run the full elapsed window before advancing.
