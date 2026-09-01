<div align="center">

# Homelab

**A Flux GitOps repository for my personal homelab Kubernetes cluster.**

[GitOps](#gitops) · [Disaster Recovery](#disaster-recovery) · [Bootstrap](#bootstrap)

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

Use `ansible/` to install K3s and restore the Sealed Secrets private key before
bootstrapping Flux from `clusters/production`. Wait until the infrastructure and
Longhorn backup target are ready. Access Longhorn without ingress if necessary:

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

### K3s and Sealed Secrets key

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

See `ansible/README.md` for the Vault variable format. Do not bootstrap Flux
until `make verify` confirms that the recovery key in the new cluster matches
the Vault values.

### Flux

```bash
flux bootstrap github \
  --repository=homelab \
  --branch=main \
  --path=./clusters/production \
  --owner=tinyrack-net
```

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
