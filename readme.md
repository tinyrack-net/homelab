# Homelab

# Installation

```bash
curl -fL https://get.k3s.io | \
sh -s - server \
  --cluster-init \
  --cluster-cidr=10.61.0.0/16 \
  --service-cidr=10.62.0.0/16 \
  --disable traefik \
  --disable servicelb
```

```bash
flux bootstrap github \
  --owner=tinyrack94 \
  --repository=homelab \
  --branch=main \
  --path=./clusters/production \
  --owner=tinyrack-net
```
