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

Install K3s, restore the Sealed Secrets private key, and bootstrap Flux from
`clusters/production`. Wait until the infrastructure and Longhorn backup target
are ready. Access Longhorn without ingress if necessary:

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

### K3s

On amd64 Ubuntu 24.04, install the Longhorn prerequisites and the pinned K3s
version with the production network ranges:

```bash
sudo apt-get update
sudo apt-get install -y curl ca-certificates jq open-iscsi nfs-common cryptsetup
sudo systemctl enable --now iscsid.socket
sudo systemctl start iscsid

curl -sfL https://get.k3s.io | \
sudo env INSTALL_K3S_VERSION='v1.36.4+k3s1' sh -s - server \
  --cluster-init \
  --cluster-cidr=10.61.0.0/16 \
  --service-cidr=10.62.0.0/16 \
  --disable traefik \
  --disable servicelb
```

### Sealed Secrets key

```bash
export PRIVATEKEY="tinyrack-homelab-secret-key.key"
export PUBLICKEY="tinyrack-homelab-secret-key.crt"
export NAMESPACE="sealed-secrets"
export SECRETNAME="sealed-secrets-key"

kubectl create namespace "$NAMESPACE"
kubectl -n "$NAMESPACE" create secret tls "$SECRETNAME" --cert="$PUBLICKEY" --key="$PRIVATEKEY"
kubectl -n "$NAMESPACE" label secret "$SECRETNAME" sealedsecrets.bitnami.com/sealed-secrets-key=active
```

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
