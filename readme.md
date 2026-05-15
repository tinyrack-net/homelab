<div align="center">

# Homelab

**개인 홈랩 Kubernetes 클러스터를 위한 Flux GitOps 저장소.**

[GitOps](#gitops) · [Disaster Recovery](#disaster-recovery) · [Bootstrap](#bootstrap)

</div>

---

이 저장소는 개인 홈랩의 `production` 클러스터 상태를 관리합니다.

K3s 위에 Flux를 올리고, `apps`와 `infrastructure` 디렉터리의 manifest를 통해 애플리케이션, 네트워크, 인증서, 스토리지, 관측 스택을 선언적으로 운영합니다.

## GitOps

- `clusters/production`이 Flux bootstrap 경로입니다.
- `infrastructure/overlays/production`은 클러스터 기반 구성입니다.
- `apps/overlays/production`은 홈랩 애플리케이션 구성입니다.
- `apps/base/*`와 `infrastructure/base/*`에 실제 workload manifest를 둡니다.
- Secret은 plaintext로 커밋하지 않고 Sealed Secrets로 암호화합니다.

## Disaster Recovery

복구의 목표는 새 노드에 K3s를 설치한 뒤, Sealed Secrets 키와 이 저장소만으로 Flux가 클러스터 상태를 다시 만들게 하는 것입니다.

1. K3s를 Traefik 없이 설치합니다.
2. Sealed Secrets private key를 먼저 복원합니다.
3. Flux를 `clusters/production` 경로로 bootstrap합니다.
4. `infrastructure`가 준비된 뒤 `apps`가 reconcile 되는지 확인합니다.
5. Longhorn 백업 또는 애플리케이션별 백업에서 필요한 데이터를 복원합니다.

DR 원칙:

- Git이 선언적 인프라의 source of truth입니다.
- Sealed Secrets 키는 별도로 안전하게 보관해야 합니다.
- 데이터 볼륨은 Git으로 복구되지 않으므로 백업 정책을 서비스별로 확인합니다.
- DB/Redis처럼 자체 백업이 있는 서비스는 Longhorn 볼륨 백업 대상에서 제외합니다.
- 복구 후 Flux, 인증서, ingress, 스토리지, 핵심 앱 순서로 상태를 확인합니다.

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
