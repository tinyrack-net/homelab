# Cluster recovery runbook

This runbook rebuilds the single-node production cluster from Git and remote
application backups. It is not an etcd restore. Do not bootstrap the production
path on a blank node before the recovery checks are complete, because production
workloads can otherwise create empty volumes.

## Recovery sources

- Sealed Secrets private key: externally stored and restored before Flux.
- PostgreSQL: Barman Cloud base backups and WAL under
  `s3://tinyrack-homelab/apps/*`.
- User file volumes: the ten claims in `recovery/volume-inventory.yaml`.
- Disposable state: SearXNG Redis and Infisical Redis are recreated empty.

Longhorn system restore is intentionally not used. A system restore selects all
Longhorn volumes that have backups, including old PostgreSQL and Redis volume
backups, which would conflict with application-level recovery.

## 1. Audit the running cluster

Run these checks while the current cluster is still healthy:

```sh
./scripts/bootstrap-node.sh --check
./scripts/recovery-audit.sh --context homelab
./scripts/restore-longhorn.sh --context homelab --check
kubectl --context homelab get kustomizations -A
kubectl --context homelab get clusters.postgresql.cnpg.io -A
```

Stop if a database backup is incomplete, older than 13 hours, the Longhorn
backup target is unavailable, or any allowlisted volume lacks a completed
backup. For a planned cutover, create fresh CNPG and Longhorn backups and record
their names, timestamps, the Git revision, and the Sealed Secrets certificate
fingerprint.

## 2. Prepare the replacement node

The supported recovery target is amd64 Ubuntu 24.04 on the existing L2 network.
Configure the intended hostname and static address before installing K3s. For a
direct replacement use hostname `xeon` and address `10.132.245.40`.

```sh
sudo ./scripts/bootstrap-node.sh --install
./scripts/bootstrap-node.sh --check
```

Restore the Sealed Secrets private key as documented in `readme.md`. Confirm its
public certificate fingerprint matches the committed certificate before
continuing.

## 3. Bootstrap recovery infrastructure

Bootstrap Flux against the recovery path, not production:

```sh
flux bootstrap github \
  --repository=homelab \
  --branch=main \
  --path=./clusters/recovery \
  --owner=tinyrack-net
```

Wait for repositories, Sealed Secrets, Reflector, common configuration,
Longhorn, cert-manager, and CloudNativePG to become Ready. Confirm the Longhorn
backup target has synchronized its BackupVolume and Backup resources.

## 4. Restore data

First inspect the exact backups selected by the allowlist:

```sh
./scripts/restore-longhorn.sh --context homelab --check
```

The default maximum backup age is 13 hours. If a real outage leaves only an
older usable backup, explicitly set `--max-age-hours` and record the accepted
recovery-point objective before running either check or apply mode.

After operator approval, run `--apply`. The script refuses to overwrite an
existing Longhorn Volume, PV, or PVC. It creates stable target volume names,
uses `Retain` PVs, and waits for each restored volume to become healthy and
bound.

The `recovery-databases` Flux Kustomization restores all seven CNPG Clusters
from their current archive server names. Application Deployments, HelmReleases,
IngressRoutes, Redis operands, and n8n file storage are removed or disabled by
the recovery patches. Wait for every Cluster to report healthy, then compare
database schema versions and application-specific row counts.

## 5. Switch to production

Only after all restored data is validated, bootstrap the normal path:

```sh
flux bootstrap github \
  --repository=homelab \
  --branch=main \
  --path=./clusters/production \
  --owner=tinyrack-net
```

Verify infrastructure first, then applications, ingress, certificates, tunnels,
and externally reachable routes. Create a new CNPG backup from each recovered
Cluster and a new Longhorn backup from each restored file volume.

## Acceptance checks

```sh
kubectl --context homelab get nodes
kubectl --context homelab get kustomizations -A
kubectl --context homelab get helmreleases -A
kubectl --context homelab get clusters.postgresql.cnpg.io -A
kubectl --context homelab get pvc -A
kubectl --context homelab -n longhorn-system get volumes.longhorn.io
kubectl --context homelab get events -A --field-selector=type=Warning --sort-by=.lastTimestamp
```

All Flux and Helm resources must be Ready, all CNPG Clusters healthy, all
Longhorn volumes healthy, and all claims Bound. Validate login and one core data
operation in Bulwark, Karakeep, n8n, Open WebUI, Issuary, RustDesk, wg-easy, and
Beszel.
