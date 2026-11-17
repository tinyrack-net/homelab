# Plan: Full cluster upgrade sweep (2026-11)

Status: **executed 2026-11-17** (phases 0–5 and 7). Phase 6 majors remain open, see
[Execution log](#execution-log-2026-11-17). Inventory taken 2026-11-17 from the repo,
`kubectl --context homelab`, the Renovate Dependency Dashboard (#76), and upstream releases.
Re-check every target version at execution time.

## Current state

- Node `homelab`: K3s `v1.37.1+k3s1`, containerd `2.3.4-k3s1`, Ubuntu 24.04.5, kernel `6.8.0-149`.
  `NRestarts=0`, root disk 40% used, 5 apt packages upgradable (no kernel), no reboot pending.
- Flux `v2.10.0` (latest upstream). All Flux objects Ready.
- Renovate runs on schedule (last success 2026-11-17). It has opened **no PRs**: everything sits
  in the dashboard as *Pending Approval*, *Awaiting Schedule*, or *Pending Status Checks*.

## Target versions

### Already at latest (verify only, no change expected)

| Component | Version |
|---|---|
| Flux | v2.10.0 |
| Cilium | 1.20.4 |
| Longhorn | 1.13.0 |
| cert-manager | v1.21.3 |
| CloudNativePG operator | v1.30.1 |
| Charts not listed by Renovate (crowdsec, sealed-secrets, mariadb-operator, ot-redis-operator, forgejo, immich chart, devenv chart) | current; confirm with `helm search repo` |

### Updates, grouped by risk

**A. Node / control plane (manual, highest blast radius)**
| Item | From → To | Files |
|---|---|---|
| K3s | v1.37.1+k3s1 → v1.37.2+k3s1 (stable channel) | `infrastructure/base/k3s-upgrade/k3s-server-plan.yaml`, `ansible/roles/setup_k3s_server/defaults/main.yml` |
| system-upgrade-controller | v0.20.2 → v0.21.1 (Renovate disabled, vendored CRD/RBAC) | `infrastructure/base/system-upgrade-controller/*` |
| Node apt packages | 5 packages | on node |

**B. Infrastructure charts / manifests**
| Item | From → To | Note |
|---|---|---|
| prometheus-operator-crds | 32.0.2 → **33.x (major)** | needs approval; check CRD changes vs victoria-metrics/k8s-monitoring consumers |
| victoria-metrics-k8s-stack | 0.97.0 → 0.98.1 | |
| k8s-monitoring | 4.6.0 → 4.6.1 | |
| kyverno | 3.9.2 → 3.10.0 (minor) | render and diff policies/webhooks |
| traefik + traefik-external | 42.2.0 → 42.4.0 | both releases together |
| juicefs-csi-driver | 0.33.2 → 0.33.3 | |
| reflector | 10.0.70 → 10.0.78 | |
| plugin-barman-cloud | v0.15.1 → v0.16.0 (minor) | needs approval; affects every CNPG backup |
| multus-cni | v4.3.1 → v4.3.2 | CNI path; DaemonSet restart; index digest |
| cloudflared | 2026.10.7 → 2026.11.0 | public ingress path |

**C. Applications – patch/minor**
| Item | From → To |
|---|---|
| bifrost | v2.4.0 → v2.5.1 |
| cli-proxy-api | v8.0.62 → v8.0.69 (**amd64** digest) |
| collabora-online chart | 1.3.7 → 1.3.8 |
| nextcloud-mcp-server chart | 0.105.16 → 0.105.23 |
| nextcloud chart | 9.4.3 → 9.4.5 |
| open-webui chart | 18.0.0 → 18.3.0 |
| immich | → v3.4.1 (server + ML) |
| outline | 1.12.0 → 1.13.0 |
| karakeep | 0.34.1 → 0.35.0 |
| meilisearch | v1.56.0 → v1.57.0 (check dump/migration requirement for karakeep) |
| home-assistant | 2026.10.4 → 2026.11.2 |
| zigbee2mqtt | 2.14.2 → 2.14.3 |
| n8n + runners | 2.45.7 → 2.48.4 (check `prerelease` flag, keep both in lockstep) |
| searxng | → 2026.11.15-2d500cb6b |
| tailscale | v1.104.4 → v1.104.7 (verify image exists) |
| nginx-unprivileged | 1.31.7 → 1.31.8 (**amd64** digest) |
| google-cloud-cli | 589.0.0 → 593 |
| karakeep-chrome | 156 → 157 |
| CNPG operand image | 18.6 → next 18.x tag (+ digest refreshes for bookworm/trixie) |
| Digest-only refreshes | mosquitto 2.1.2-alpine, uv:alpine, email-mcp 0.6.0, node:22-alpine, postgres:17.11, python:3.15-alpine |
| Pin dependencies | bookorbit-korean-provider, prompter, `rancher/k3s-upgrade` (keep untagged – see below) |

**D. Majors – deferred / separate change each**
| Item | Decision needed |
|---|---|
| n8n / runners 2.x → **3.x** | breaking release; read migration notes, take CNPG backup, do alone |
| postgres 17 → **18** (`guacamole.database-init.yaml`) | only an init image; confirm guacamole DB server version before moving |
| postgres 17.11 → 17.12 | safe patch, can go in C |
| node 22 → **26** (`node:22-alpine` users) | check app compatibility (bifrost/cliproxyapi/gcp-mcp sidecars) |
| actions/checkout v7 | CI only, independent |
| `rancher/k3s-upgrade` pin | **reject**: README requires `upgrade.image` to stay untagged; add a Renovate ignore |

## Execution order

Each phase = its own commit(s) on `main`, Flux reconcile, verify, then next phase.
Stop the sweep on any failure; do not stack phases on an unhealthy cluster.

### Phase 0 – Safety net
1. `flux --context homelab get all -A` all Ready; `kubectl --context homelab get pods -A | grep -v Running|Completed` empty.
2. Snapshots (README "Pitfalls"): Longhorn `Snapshot` per volume, a Longhorn `SystemBackup`,
   a manual CNPG `Backup` in every namespace (`kubectl get backups.postgresql.cnpg.io -A` to confirm),
   MariaDB backup.
3. `ssh homelab 'sudo k3s etcd-snapshot save --name pre-upgrade-2026-11-17'`.
4. Check Docker Hub pull budget; pre-seed large images through `mirror.gcr.io` if needed.

### Phase 1 – Node and control plane
1. Upgrade system-upgrade-controller to v0.21.1: refresh vendored CRD/RBAC/deployment from the
   release, diff rendered output, commit, reconcile `system-upgrade-controller`.
2. Bump K3s plan + Ansible default to `v1.37.2+k3s1`; commit; watch the `Plan`/Job and
   `kubectl get nodes`. Expect brief API unavailability.
3. `apt-get -y -o Dpkg::Options::=--force-confold upgrade` on the node. Reboot only if
   `/var/run/reboot-required` appears, as a separate scheduled step (follow the VM shutdown
   pitfall: etcd snapshot, check Traefik CrowdSec plugin and crowdsec-agent after boot).

### Phase 2 – CRDs and platform foundations
1. prometheus-operator-crds 33 (review changelog; `helm template` diff of CRDs).
2. kyverno 3.10.0.
3. plugin-barman-cloud v0.16.0 → afterwards trigger one manual CNPG `Backup` and confirm it completes.
4. multus v4.3.2 → confirm pods with secondary networks (home-assistant, devenv LAN addresses) still get interfaces.

### Phase 3 – Ingress and edge
1. traefik + traefik-external 42.4.0 (render with dedented values, diff).
2. cloudflared 2026.11.0.
3. Verify: public `curl -o /dev/null -w '%{http_code}' https://<host>` for several routes,
   no `middleware does not exist` in Traefik logs.

### Phase 4 – Observability and misc infra
victoria-metrics-k8s-stack 0.98.1, k8s-monitoring 4.6.1, juicefs 0.33.3, reflector 10.0.78.
Verify metrics/logs still arrive in Grafana.

### Phase 5 – Applications (patch/minor + digests)
Batch by app, one commit per app (or approve the Renovate PRs one by one):
stateless first (searxng, nginx, tailscale, gcp-mcp, email-mcp, cliproxyapi, karakeep-chrome),
then stateful (bifrost, outline, karakeep+meilisearch, immich, nextcloud + mcp + collabora,
open-webui, home-assistant + zigbee2mqtt + mosquitto, n8n 2.48.4), then CNPG operand images
(rolling restart of every Postgres cluster – do last, one cluster at a time).

### Phase 6 – Majors (separate tasks, later)
n8n 3, node 26, postgres 18 init image – each with its own plan after reading upstream notes.

### Phase 7 – Cleanup
Delete the Phase 0 Longhorn snapshots once everything is verified; add a Renovate
`ignoreDeps`/rule for `rancher/k3s-upgrade` pinning; update README if any procedure changed.

## Verification per change
- `kubectl kustomize ./infrastructure/overlays/production` and `./apps/overlays/production`.
- `kubectl kustomize ./infrastructure/base/<name>` / `./apps/base/<name>`; for charts also `helm template`.
- Digests: match the file's convention (amd64 vs index) – see README "Image digests".
- After push: `flux --context homelab reconcile kustomization <name> --with-source`, HelmRelease Ready,
  pods Ready, app health endpoint / public URL.

## Rollback
- Chart/image: `git revert` the commit; Flux rolls back (HelmRelease remediation).
- K3s: revert plan version is **not** a safe downgrade; restore from the etcd snapshot only if the node is broken.
- Data: CNPG recovery from Barman S3; Longhorn snapshot/system backup.

## Execution log (2026-11-17)

| Phase | Commit | Result |
|---|---|---|
| 0 | – | etcd snapshot `pre-upgrade-20261117`, Longhorn `Snapshot` per volume + `SystemBackup pre-upgrade-20261117` (Ready), manual CNPG `Backup` in 16 namespaces. bifrost's manual backup failed (`NoSuchUpload`, see below); the scheduled 12:00 backup completed. |
| 1 | `dee69ff` | system-upgrade-controller v0.21.1 (CRD docstring change only). |
| 1 | `1332c85` | K3s v1.37.2+k3s1, containerd 2.3.7. Node apt upgrade (5 packages, no kernel, no reboot). |
| 2 | `d252df8` | prometheus-operator-crds 33.0.2 (adds optional `extraScrapeMetrics`), kyverno 3.10.0 (only `policies.kyverno.io` + GlobalContextEntry in use, so the new legacy-policy gate passes), plugin-barman-cloud 0.16.0 (rolled every CNPG pod; test backup completed, WAL archiving OK on all clusters), multus 4.3.2. |
| 3 | `4c46679` | Traefik chart 42.4.0 (Traefik v3.7.18) on both releases, cloudflared 2026.11.0. 42.3+ values schema rejects `service.additionalServices.<name>.type`; moved under `spec` (rendered Service unchanged). 39 hosts returned the same status code before and after. |
| 4 | `79d892e` | victoria-metrics-k8s-stack 0.98.1, k8s-monitoring 4.6.1, juicefs 0.33.3, reflector 10.0.78. |
| 5 | `a184eed` | Stateless images (searxng, nextcloud-mcp 0.105.23/app 0.210.0, nginx, tailscale, gcloud, cli-proxy-api, digests). |
| 5 | `6f60e13` | outline 1.13.0, karakeep 0.35.0 + chrome 157 + meilisearch 1.57.0, home-assistant 2026.11.2, zigbee2mqtt 2.14.3, n8n 2.48.4, collabora 1.3.8, open-webui 18.3.0, nextcloud chart 9.4.5 / 35.0.3. |
| 5 | `5c7cef4` | immich v3.4.1 (migrations finished). |
| 5 | `e39d3ce`, `8254a36` | CNPG operand 18.7 on all 16 clusters, bifrost v2.5.1. |
| 7 | this commit | Renovate rule disabling `rancher/k3s-upgrade` pinning. |

### Findings
- README digest table was wrong in two places: `multus-cni` is pinned by **amd64** digest,
  `eceasy/cli-proxy-api` by **index** digest. Fixed.
- `crowdsec-system` scrape targets `crowdsec-service` and `crowdsec-agent-service` report `up=0`;
  this predates the sweep (seen 1d earlier). Not fixed here.
- Manual bifrost base backups still fail with `NoSuchUpload` at CompleteMultipartUpload
  (22GB database). Commit `4d3032a` (2GB archives) landed earlier the same day; the scheduled
  backup afterwards completed. Watch the next scheduled runs.
- One `nextcloud-cron` job pod failed while its database restarted for 18.7; the next run succeeded.

### Still open (Phase 6)
- n8n / runners 3.x (still `prerelease: true` upstream on 2026-11-17).
- node 22 → 26 for bifrost/gcp-mcp init images.
- postgres 17 → 18 for `guacamole.database-init.yaml`.
- `actions/checkout` v7 (CI only).
