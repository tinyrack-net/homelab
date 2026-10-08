<div align="center">

# Homelab

**A Flux GitOps repository for my personal homelab Kubernetes cluster.**

[GitOps](#gitops) · [Disaster Recovery](#disaster-recovery) · [Bootstrap](#bootstrap) · [Version sweep](#version-sweep)

</div>

---

This repository manages the desired state of my personal homelab `production` cluster.

It runs Flux on K3s and uses the manifests under `apps` and `infrastructure` to declaratively manage applications, networking, certificates, storage, and observability.

## GitOps

- `clusters/production` is the Flux bootstrap path.
- `infrastructure/overlays/production` contains the cluster foundation.
- `apps/overlays/production` contains homelab application configuration.
- `apps/base/*` and `infrastructure/base/*` hold the workload manifests.
- Secrets are encrypted with Sealed Secrets before they are committed.
- `ansible/` prepares the replacement machine used for cluster migration.

## Disaster Recovery

Recovery uses the normal production path. There is no separate recovery Flux
installation or recovery overlay.

Before bootstrapping a replacement cluster, temporarily remove the application
entry point from Flux and push that change:

```bash
mv clusters/production/apps.yaml clusters/production/apps.yaml.bak
git add clusters/production/apps.yaml clusters/production/apps.yaml.bak
git commit -m "chore: pause applications for cluster recovery"
git push
```

Use `ansible/` to install K3s, bootstrap Cilium, and restore the Sealed Secrets
private key before bootstrapping Flux from `clusters/production`. The bootstrap
uses the same `cilium` Helm release and values that Flux adopts later. Wait until
the infrastructure and Longhorn backup target are ready. Access Longhorn without
ingress if necessary:

```bash
kubectl -n longhorn-system port-forward service/longhorn-frontend 8000:80
```

In the Longhorn UI, restore the latest `Ready` system backup created by the same
Longhorn minor version. The system backup restores application volumes from
their latest volume backups.

PostgreSQL is restored by CloudNativePG from Barman S3 backups, not from
Longhorn volume backups. Before enabling applications, remove any CNPG data
PVCs restored by an old Longhorn backup and confirm their PVs and Longhorn
volumes are gone:

```bash
kubectl get pvc -A -l cnpg.io/pvcRole=PG_DATA
kubectl delete pvc -A -l cnpg.io/pvcRole=PG_DATA
kubectl get pv
```

Enable applications again and push the change:

```bash
mv clusters/production/apps.yaml.bak clusters/production/apps.yaml
git add clusters/production/apps.yaml clusters/production/apps.yaml.bak
git commit -m "chore: resume applications after cluster recovery"
git push
```

All seven CNPG manifests use `bootstrap.recovery`; they recreate their databases
from S3 when Flux applies the application manifests. Verify CNPG recovery before
allowing external traffic, then check Flux, certificates, ingress, storage, and
core application data.

## Bootstrap

### K3s, Cilium, and Sealed Secrets key

Store the become password and Sealed Secrets TLS certificate/private key in the
Ansible Vault, then let Ansible prepare everything up to the Flux boundary:

```bash
cd ansible
make vault-edit
make preflight
make check
make apply
make apply
make verify
cd ..
```

Do not bootstrap Flux until `make verify` confirms that Cilium is healthy and
that the recovery key in the new cluster matches the Vault values. K3s starts
with Flannel, its network-policy controller, and kube-proxy disabled; Cilium must
therefore be running before Flux controllers and workloads can start.

### Flux

```bash
flux bootstrap github \
  --repository=homelab \
  --branch=main \
  --path=./clusters/production \
  --owner=tinyrack-net
```

Flux reconciles the `cilium` HelmRelease in `kube-system` and takes over the
release installed by Ansible. Multus remains the first CNI configuration and
delegates the primary Pod network to Cilium.

## Configuration files

- Keep a HelmRelease focused on chart lifecycle and load chart configuration
  from a sibling `<component>.values.yaml` through `spec.valuesFrom`.
- Generate Helm values ConfigMaps with a stable name, the
  `reconcile.fluxcd.io/watch: Enabled` label, and `values.yaml` as the data key.
- Keep application-native YAML, TOML, JSON, ENV, and Alloy River configuration
  in files named for the owning component. Use Kustomize's default name hash
  when a Pod directly mounts or imports a ConfigMap so changes roll the Pod.
- Disable the name hash only when the consumer requires a stable name, such as
  Helm values and Alloy's externally managed, dynamically reloaded ConfigMap.
- Keep credentials out of values and configuration files. Secrets remain
  encrypted SealedSecret manifests or references to existing Secrets.

## Version sweep

Renovate is **not running**. `renovate.json5` is kept in the repository, but
there is no Dependency Dashboard issue, no Renovate pull request, and no
`.github/workflows` directory for a scheduled run, so nothing refreshes the
pinned versions automatically. Component versions are updated by a manual
sweep.

Confirm the state before assuming an automatic update:

```bash
gh issue list --repo tinyrack-net/homelab --search renovate
gh pr list --repo tinyrack-net/homelab --search renovate
ls .github/workflows 2>/dev/null
```

Reviving Renovate, or replacing it with another updater, needs its own decision
and is out of scope for the sweep. Leave `renovate.json5` untouched.

### Sweep checklist

Refresh one layer at a time, commit per layer, and verify before moving on.

1. **Flux controllers** — `clusters/production/flux-system/gotk-components.yaml`
   is generated, so compare its `# Flux Version:` header and image tags with the
   latest upstream release by exporting that release:
   `flux install --version=<v> --components=source-controller,kustomize-controller,helm-controller,notification-controller,image-reflector-controller,image-automation-controller --export`,
   then check `kubectl kustomize ./clusters/production/flux-system`.
2. **K3s** — take the version from the K3s release channel
   (`curl -s https://update.k3s.io/v1-release/channels`) or the upstream GitHub
   releases, and update both
   `infrastructure/base/k3s-upgrade/k3s-server-plan.yaml` (the `version:` field
   drives the upgrade; `upgrade.image` stays untagged) and
   `ansible/roles/setup_k3s_server/defaults/main.yml`.
3. **Helm charts** — `helm search repo <repo>/<chart> --versions` and bump
   `spec.chart.spec.version` in the owning `*.helm-release.yaml`. Render the base
   with `helm template` and `kubectl kustomize ./infrastructure/base/<name>`
   before committing, because a new chart minor can rename values keys and
   silently drop configuration.
4. **Remote release manifests** — `infrastructure/base/cloudnative-pg` and
   `infrastructure/base/system-upgrade-controller` pull manifests from upstream
   release URLs. Check their releases and diff the rendered output.
5. **Container images** — `docker buildx imagetools inspect <ref>` for the
   newest tag, then re-pin the digest.
6. **Node components** — K3s ships its own coredns, metrics-server,
   local-path-provisioner, and kubectl. They move with the node and are not
   pinned in this repository.

### Image digests

Every `@sha256:` must be refreshed together with its tag. The node is
`linux/amd64`:

```bash
docker buildx imagetools inspect <registry>/<path>:<tag> --format '{{json .Manifest}}' \
  | jq -r 'if .manifests then (.manifests[] | select(.platform.os == "linux" and .platform.architecture == "amd64") | .digest) else .digest end'
```

Most images pin the platform digest the command above prints.
`eceasy/cli-proxy-api` and `library/postgres` pin the **index** digest instead,
so check the existing pin and match its convention.

### Pitfalls found by hand

- Registry tags drift into pre-release channels: `n8nio/n8n` publishes `2.43.x`
  with `prerelease: true` while `2.42.5` is the promoted stable release. Check
  the GitHub release `prerelease` flag and the image `stable` tag before bumping.
- A new image tag may not exist for every distribution: `eclipse-mosquitto`
  publishes `2.1.x` only as `-alpine`, and `tailscale/tailscale` tags a release
  before it publishes an image. Verify the image, not just the release. Mosquitto
  2.1 refuses ConfigMap and Secret files that Kubernetes mounts through symlinks
  unless `MOSQUITTO_UNSAFE_ALLOW_SYMLINKS=true` is set.
- Docker Hub throttles anonymous pulls per egress IP, and the workstation and the
  node share one, so probing registries during a rollout can break it with `429
  Too Many Requests`. Pre-seed the node from a pull-through mirror instead of
  waiting: `k3s ctr -n k8s.io images pull mirror.gcr.io/<path>:<tag>` and then
  `k3s ctr -n k8s.io images tag mirror.gcr.io/<path>:<tag> docker.io/<path>:<tag>`.
- `kubectl get backup -A` resolves to MariaDB backups. Name the resource
  explicitly: `kubectl get backups.postgresql.cnpg.io -A`.
- The Traefik LoadBalancer IPs are not reachable from the workstation. Verify an
  ingress with `kubectl -n <namespace> port-forward service/<service> <local>:<port>`.
- Snapshot stateful volumes before a sweep that touches storage or the node: a
  Longhorn `Snapshot` per volume, a Longhorn `SystemBackup`, and a manual CNPG
  `Backup` in every namespace.

## CNI migration

The production cluster was migrated from Flannel and kube-proxy to Cilium. The
one-time migration and rollback playbooks were removed after verification.

## Traefik network policy ownership

- Keep only shared entrypoint, Kubernetes API, and telemetry access in the
  Traefik infrastructure policies.
- Put route-specific access beside its owning application or proxy in a
  `<owner>.traefik.cilium-network-policy.yaml` file.
- Create the policy in `traefik-system` or `traefik-external-system`, name it
  `route-<owner>`, and add the `networking.tinyrack.net/owner` label and
  `networking.tinyrack.net/hosts` annotation.
- Use `toServices` with the backend target port for Kubernetes Services and
  `toCIDRSet` with a `cidrGroupRef` plus explicit ports for LAN or ExternalName
  backends.
- Group routes that share a backend into one owner policy. Host annotations are
  documentation and do not enable Cilium L7 HTTP filtering.

## Cilium CIDR groups

CIDR literals in network policies are replaced by `CiliumCIDRGroup` aliases so a
reader can tell which network or host a rule targets.

- Define network groups (`lan`, `vpn-server`, `vpn-control`, `tailscale`) and
  one group per LAN host in `infrastructure/base/network-security`.
- Reference groups with `fromCIDRSet`/`toCIDRSet` and `cidrGroupRef`; list
  several refs when a rule needs several networks.
- `homelab-host-firewall` depends on the `network-security` Kustomization, so a
  group always exists before a policy that references it is applied.
- Cilium has no alias for ports and `except` only accepts literal CIDRs, so those
  stay explicit and carry a comment describing their purpose.

## Sealed Secrets

```bash
kubectl create secret generic some-secret \
  --namespace some-namespace \
  --dry-run=client \
  --from-literal=SOME_SECRET_KEY=SOME_SECRET_VALUE \
  -o yaml | \
  kubeseal --cert ./tinyrack-homelab-secret-key.crt \
  > ./some.secret.yaml
```
