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

The recovery goal is to install K3s on a new node, restore the Sealed Secrets key, and let Flux recreate the cluster state from this repository.

1. Install K3s without Traefik.
2. Restore the Sealed Secrets private key first.
3. Bootstrap Flux from `clusters/production`.
4. Wait for `infrastructure` to become ready, then verify `apps` reconciliation.
5. Restore required data from Longhorn backups or application-specific backups.

DR guidelines:

- Git is the source of truth for declarative infrastructure.
- Keep the Sealed Secrets key backed up separately and securely.
- Data volumes are not restored from Git; verify backup policy per service.
- Exclude DB/Redis volumes from Longhorn volume backups when they have their own backup flow.
- After recovery, verify Flux, certificates, ingress, storage, and core apps in that order.

## Bootstrap

### K3s

```bash
curl -fL https://get.k3s.io | \
sh -s - server \
  --cluster-init \
  --cluster-cidr=10.61.0.0/16 \
  --service-cidr=10.62.0.0/16 \
  --disable traefik
```

### Sealed Secrets key

```bash
export PRIVATEKEY="tinyrack-homelab-secret-key.key"
export PUBLICKEY="tinyrack-homelab-secret-key.crt"
export NAMESPACE="sealed-secrets"
export SECRETNAME="tinyrack-homelab-s3-secret"

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
