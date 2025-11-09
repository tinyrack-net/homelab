# Homelab

# Installation

K3S 설치

```bash
curl -fL https://get.k3s.io | \
sh -s - server \
  --cluster-init \
  --cluster-cidr=10.61.0.0/16 \
  --service-cidr=10.62.0.0/16 \
  --disable traefik \
  --disable servicelb
```

Flux 부트스트랩

```bash
flux bootstrap github \
  --owner=tinyrack94 \
  --repository=homelab \
  --branch=main \
  --path=./clusters/production \
  --owner=tinyrack-net
```

# Sealed Secret 암호화

```bash
kubectl create secret generic docmost-secret \
        --namespace docmost-system \
        --dry-run=client \
        --from-literal=SOME_SECRET_KEY=SOME_SECRET_VALUE \
        --from-literal=SOME_SECRET_KEY=SOME_SECRET_VALUE \
        --from-literal=SOME_SECRET_KEY=SOME_SECRET_VALUE -o yaml \
        | kubeseal --cert ./tinyrack-homelab-secret-key.crt \
        > ./some.secret.yaml
```
