# Cluster upgrade runbook

This runbook deploys the dependency updates in small GitOps waves. Do not push
all version changes as one production rollout. Finish the checks for one wave
before merging the next.

## 1. Pre-flight checks

Use the `homelab` context explicitly.

```sh
kubectl --context homelab get nodes -o wide
kubectl --context homelab get kustomizations -A
kubectl --context homelab get helmreleases -A
kubectl --context homelab get pods -A --field-selector=status.phase!=Running
kubectl --context homelab get events -A --field-selector=type=Warning --sort-by=.lastTimestamp
```

All nodes, Flux resources, Helm releases, PostgreSQL clusters, Longhorn volumes,
and user-facing applications must be healthy. Stop if the Loki readiness 503
warning continues for more than 15 minutes.

Create a fresh plugin backup for every PostgreSQL cluster and wait for each
`Backup` to reach `completed`:

```sh
kubectl cnpg backup --context homelab -n davinci-resolve-system davinci-resolve-database-cluster --method=plugin --plugin-name=barman-cloud.cloudnative-pg.io
kubectl cnpg backup --context homelab -n guacamole-system guacamole-database-cluster --method=plugin --plugin-name=barman-cloud.cloudnative-pg.io
kubectl cnpg backup --context homelab -n infisical-system infisical-database-cluster --method=plugin --plugin-name=barman-cloud.cloudnative-pg.io
kubectl cnpg backup --context homelab -n litellm-system litellm-database-cluster --method=plugin --plugin-name=barman-cloud.cloudnative-pg.io
kubectl cnpg backup --context homelab -n n8n-system n8n-database-cluster --method=plugin --plugin-name=barman-cloud.cloudnative-pg.io
kubectl cnpg backup --context homelab -n openwebui-system openwebui-database-cluster --method=plugin --plugin-name=barman-cloud.cloudnative-pg.io
kubectl cnpg backup --context homelab -n issuary-system issuary-database-cluster --method=plugin --plugin-name=barman-cloud.cloudnative-pg.io
kubectl --context homelab get backups.postgresql.cnpg.io -A --sort-by=.metadata.creationTimestamp
```

Also create a Longhorn system backup and volume backups, and create a new K3s
etcd snapshot on `xeon` before the K3s or Longhorn waves.

## 2. Rollout waves

Merge and reconcile in this order:

1. Flux v2.9.4.
2. system-upgrade-controller v0.20.1, then K3s v1.36.3+k3s1 during a maintenance window.
3. Reflector, Sealed Secrets, Tailscale, both Traefik releases, then the observability charts.
4. Longhorn v1.12.1 by itself. Never attempt a chart downgrade after it succeeds.
5. Redis Operator v0.26.1, then one Redis 7.4.11 operand at a time.
6. Barman Cloud v0.14.0, verify a new backup, then CloudNativePG v1.30.0.
7. One PostgreSQL 17/18 operand and one application image update at a time.
8. The DaVinci Resolve PostgreSQL 13 to 18 migration by itself.

After each merge, reconcile only the affected Flux Kustomization and wait at
least 15 minutes after it becomes Ready before continuing.

## 2.1 Known recovery cases

- Verify every system-upgrade helper tag exists before changing a Plan. The K3s
  target and the `rancher/kubectl` helper do not always publish matching patch
  tags; keep the last published helper when necessary.
- On this single-node cluster, set both Longhorn
  `persistence.defaultClassReplicaCount` and `defaultSettings.defaultReplicaCount`
  to `1`. StorageClass changes affect only new volumes, so reduce existing
  volumes separately after confirming a fresh backup.
- Loki must use an S3 bucket allowed by the configured credentials. During a
  large WAL replay, do not repeatedly restart the pod; wait for
  `loki_ingester_wal_replay_active` and `loki_ingester_flush_queue_length` to
  reach zero before retrying the Helm reconciliation.
- A Barman plugin update also changes the injected database sidecar and can
  restart every PostgreSQL instance. Wait for all Cluster resources to report
  the new plugin version and become healthy before testing a backup.
- Use absolute in-cluster DNS names (with a trailing `.`) for Node.js workloads
  that use libc `getaddrinfo`; this avoids `ndots:5` search expansion failures.
- Remove overrides for SearXNG engines removed upstream. Use `inactive: true`
  instead of only `disabled: true` when an unavailable engine must not be
  initialized at startup.

## 3. PostgreSQL 13 to 18

The DaVinci Resolve database uses PostgreSQL 13.22, has no non-core extension,
and is small enough for an offline in-place upgrade. Confirm a fresh PG13 backup,
then deploy the Cluster image and PG18 ObjectStore change together. CloudNativePG
will stop the cluster and run `pg_upgrade --link`.

Monitor the Cluster, upgrade Job, operator, and Barman plugin logs. If the upgrade
Job fails, revert the image and ObjectStore reference before retrying. After a
successful upgrade, do not downgrade the image. Validate the application and run:

```sh
kubectl --context homelab exec -n davinci-resolve-system davinci-resolve-database-cluster-1 -c postgres -- psql -U postgres -d davinci-resolve -c 'ANALYZE;'
kubectl --context homelab exec -n davinci-resolve-system davinci-resolve-database-cluster-1 -c postgres -- postgres --version
kubectl cnpg backup --context homelab -n davinci-resolve-system davinci-resolve-database-cluster --method=plugin --plugin-name=barman-cloud.cloudnative-pg.io
```

Verify table row counts, the new `database-18` WAL archive, and the new base
backup. Keep the old `database-13` ObjectStore and backup data for at least 30
days. If post-upgrade validation fails, recover a new cluster from the retained
PG13 backup instead of attempting a PostgreSQL downgrade.

## 4. Acceptance checks

```sh
kubectl --context homelab get nodes
kubectl --context homelab get kustomizations -A
kubectl --context homelab get helmreleases -A
kubectl --context homelab get clusters.postgresql.cnpg.io -A
kubectl --context homelab get volumes.longhorn.io -n longhorn-system
kubectl --context homelab get events -A --field-selector=type=Warning --sort-by=.lastTimestamp
```

Check TLS and routing for `auth`, `ai`, `bookmarks`, `llm`, `n8n`, `search`, and
`webmail`, plus the intranet proxy routes. Confirm application login and one core
workflow for Karakeep, LiteLLM, n8n, Open WebUI, and DaVinci Resolve Project Server.
