# Plan: 클러스터 전체 버전 스윕 (2026-11-01) — 실행 완료

## Context

`homelab` 클러스터(단일 노드 K3s, Flux GitOps)의 모든 계층 — Flux 컨트롤러, 인프라 Helm 차트, 플랫폼 컨트롤러,
애플리케이션 이미지, K3s 노드 — 을 upstream 최신 릴리스로 수렴시킨다.

지난 스윕(2026-10-08, `dda5732`)은 완료되어 `main`에 반영됐고, 그 결과로 `readme.md`의 "Version sweep"
수동 런북만 남았다. 이번 스윕은 그 런북을 **실제로 한 번 더 실행**하고, 동시에 사용자가 결정한
**Renovate 부활**까지 함께 처리한다.

현재 상태(2026-11-01 02:00 KST 기준, 감사 완료):

- 노드 1대(`homelab`), K3s `v1.37.1+k3s1`, 60일 가동, 파드 전부 `Running`.
- Flux GitOps 51개 Kustomization 전부 `Ready` @ `main@sha1:2163502`.
- Longhorn 1.13.0, 볼륨 36개(attached 35 / detached 1), `robustness` 전부 healthy,
  SystemBackup 최신 `Ready` (2026-10-31 04:00, `v1.13.0`), backupvolume 49개.
- CNPG 클러스터 13개 전부 healthy, 각 ScheduledBackup이 4시간 주기로 `completed`.
- 대부분의 컴포넌트가 이미 최신이거나 한 단계 차이. **큰 버전 점프는 없다.**

### 확정된 결정 (사용자 승인)

| # | 항목 | 결정 |
|---|------|------|
| 1 | 전달 방식 | **`main`에 웨이브 단위 커밋**, 웨이브당 1커밋, 각 웨이브 사이 검증 + reconcile |
| 2 | 리스크 게이트 | **전체 백업 게이트** — stateful 웨이브 전 Longhorn SystemBackup Ready + CNPG 13개 Backup completed + 온디맨드 etcd 스냅샷 |
| 3 | Renovate | **이번에 부활** — 향후 bump이 PR로 도착하도록 워크플로 추가 |

---

## 현재 버전 감사 (2026-11-01, current → latest)

### Flux 컨트롤러 — **최신, 변경 없음**

`# Flux Version: v2.10.0`, 배포된 이미지도 v2.10.0과 일치.

| 컴포넌트 | 현재 | 최신 |
|---|---|---|
| source-controller | v1.10.1 | v1.10.1 |
| kustomize-controller | v1.10.1 | v1.10.1 |
| helm-controller | v1.7.1 | v1.7.1 |
| notification-controller | v1.10.0 | v1.10.0 |
| image-reflector-controller | v1.3.0 | v1.3.0 |
| image-automation-controller | v1.3.0 | v1.3.0 |

> 로컬 `flux` CLI는 v2.9.6으로 낡았다. 매니페스트 재생성은 하지 않지만, `flux install --export`로 검증하거나
> 후속 스윕을 하려면 `brew upgrade fluxcd/tap/flux`(또는 동등) 로 CLI를 v2.10.0에 맞춘다.

### 인프라 Helm 차트

| 파일 | 현재 | 최신 | 비고 |
|---|---|---|---|
| `infrastructure/base/traefik/traefik.helm-release.yaml` | 42.1.3 | **42.2.0** | 렌더 결과 6 kinds 동일, 이미지 `v3.7.16` 동일 → 값 호환 |
| `infrastructure/base/traefik-external/traefik.helm-release.yaml` | 42.1.3 | **42.2.0** | 위와 동일 (같은 값 파일 사용) |
| `infrastructure/base/monitoring/monitoring.k8s-monitoring.helm-release.yaml` | 4.5.5 | **4.6.0** | 40 kinds 동일, alloy-operator 1.14.3 → 1.14.4만 이동 |
| `infrastructure/base/monitoring/monitoring.stack.helm-release.yaml` (victoria-metrics-k8s-stack) | 0.97.0 | 0.97.0 | 변경 없음 |
| `infrastructure/base/prometheus-operator-crds/…` | 32.0.2 | 32.0.2 | 변경 없음 |
| `infrastructure/base/cert-manager/install/…` | v1.21.3 | v1.21.3 | 변경 없음 |
| `infrastructure/base/kyverno/kyverno.helm-release.yaml` | 3.9.2 | 3.9.2 | 변경 없음 (app v1.19.2) |
| `infrastructure/base/longhorn/install/…` | 1.13.0 | 1.13.0 | 변경 없음 |
| `infrastructure/base/mariadb-operator/{operator,crds}` | 26.10.2 | 26.10.2 | 변경 없음 |
| `infrastructure/base/ot-redis-operator/…` | 0.27.0 | 0.27.0 | 변경 없음 |
| `infrastructure/base/reflector/…` | 10.0.70 | 10.0.70 | 변경 없음 |
| `infrastructure/base/sealed-secrets/…` | 2.22.0 | 2.22.0 | 차트는 최신 |
| `infrastructure/base/juicefs/…` | 0.33.2 | 0.33.2 | 변경 없음 |
| `apps/base/collabora/…` (collabora-online) | 1.3.7 | 1.3.7 | 변경 없음 (app 26.04.5.2.1 최신) |
| `apps/base/openwebui/…` (open-webui) | 17.4.0 | **17.5.0** | 값 호환 확인됨, 앱 이미지는 values에서 digest로 고정 중이라 그대로 |
| `apps/base/nextcloud-mcp/…` | 0.105.13 (app 0.202.1 postRender) | **0.105.16** (app 0.203.0) | postRenderer 태그/digest도 함께 갱신 |

### 원격 릴리스 매니페스트

| 파일 | 현재 | 최신 |
|---|---|---|
| `infrastructure/base/cloudnative-pg/kustomization.yaml` (cnpg) | v1.30.1 | v1.30.1 |
| 같은 파일 (plugin-barman-cloud) | v0.15.1 | v0.15.1 |
| `infrastructure/base/system-upgrade-controller/…` | v0.20.2 | v0.20.2 |

### 컨테이너 이미지

| 파일 | 현재 | 최신 |
|---|---|---|
| `apps/base/n8n/n8n.deployment.yaml` | n8nio/n8n 2.45.5 | **2.45.7** |
| `apps/base/n8n/n8n.task-runner.deployment.yaml` | n8nio/runners 2.45.5 | **2.45.7** |
| `apps/base/searxng/searxng.deployment.yaml` | 2026.10.28-c360868e5 | **2026.10.30-ffa88e3ba** |
| `apps/base/cliproxyapi/cliproxyapi.deployment.yaml` | eceasy/cli-proxy-api v8.0.47 | **v8.0.48** |
| `infrastructure/base/cloudflared/cloudflared.deployment.yaml` | 2026.10.5 | **2026.10.7** |
| `apps/base/nextcloud-mcp/nextcloud-mcp.gateway.yaml` | nginx-unprivileged 1.30.6-alpine | **1.31.7-alpine** |
| `apps/base/nextcloud-mcp/nextcloud-mcp.helm-release.yaml` (postRenderer) | app 0.202.1 | **0.203.0** |
| `apps/base/bifrost/bifrost.statefulset.yaml` | `maximhq/bifrost:latest@sha256:a1c906…` | `v2.4.0@sha256:a1c906…` (**같은 digest, 태그만 명시화**) |
| `apps/base/openwebui/openwebui.values.yaml` | open-webui v0.12.4 (index digest) | v0.12.5 (index digest) |
| `apps/base/immich/app/values.yaml` | v3.3.5 (index digest) | v3.3.5 (변경 없음) |
| `apps/base/nextcloud/app/values.yaml` | 35.0.2-apache (index digest) | 35.0.2 (변경 없음) |

변경 없음(확인 완료): home-assistant 2026.10.4, zigbee2mqtt 2.14.2, eclipse-mosquitto 2.1.2-alpine,
karakeep 0.34.1 + karakeep-chrome 156.0.8078.47-r1, meilisearch v1.56.0, outline 1.12.0, mathesar 0.12.0,
dbhub 1.5.0, guacamole/guacd 1.6.0, syncthing 2.1.7, rustdesk-server-s6 1.1.16, tailscale v1.104.4,
multus v4.3.1-thick, cilium 1.20.4, opstree/redis v8.10.1, CNPG operand 18.6, vchord pg18-v1.1.1,
busybox 1.38.0, python 3.15-alpine, node 22-alpine, uv alpine, tika 4.2.0-full, proxer/issuary(Flux image automation 소유).

> **차트가 관리하는 이미지는 수동으로 pin하지 않는다.** monitoring 4.6.0이 끌고 가는 alloy-operator 1.14.4,
> traefik 42.2.0이 끌고 가는 traefik v3.7.16은 차트 기본값을 따른다.
> 단 `monitoring.stack.values.yaml`의 `grafana.imageRenderer.image.tag: v5.12.10`은 명시 pin이므로 차트 업그레이드 시 함께 확인한다
> (현재 upstream 최신도 v5.12.10 → 변경 불필요).

### 이미지 digest 규약 (기존 파일 관례 — 반드시 준수)

| 규약 | 대상 |
|---|---|
| **index(멀티아치) digest** | n8n, runners, searxng, cloudflared, karakeep, zigbee2mqtt, guacamole, guacd, opstree/redis, python, node, busybox, uv, searxng, open-webui, immich, nextcloud, CNPG operand, vchord, postgres, mater, dbhub, outline, syncthing, tailscale, meilisearch, rustdesk, multus, karakeep-chrome |
| **amd64 platform digest** | `eceasy/cli-proxy-api`, `nginx-unprivileged`, `nextcloud-mcp-server` |

핀 대상 44개 파일 / 38개 고유 digest. 각 bump에서 태그와 digest를 **같이** 갱신한다.

### 노드 / 호스트 / Ansible

| 항목 | 현재 | 최신 | 조치 |
|---|---|---|---|
| K3s | v1.37.1+k3s1 | v1.37.1+k3s1 (latest 채널) | **변경 없음** — v1.37.2는 아직 rc |
| `k3s-io/k3s` stable 채널 | — | v1.36.5+k3s1 | 참고용 (현재 노드가 latest보다 앞섬) |
| `infrastructure/base/k3s-upgrade/k3s-server-plan.yaml` | v1.37.1+k3s1 | 동일 | 변경 없음 |
| `ansible/roles/setup_k3s_server/defaults/main.yml` | v1.37.1+k3s1 | 동일 | 변경 없음 |
| `ansible/roles/setup_cilium/defaults/main.yml` | 1.20.4 | 1.20.4 | 변경 없음 |
| 노드 OS | Ubuntu 24.04.5, 무재부팅 14일 | — | apt upgradable 7건 (cloud-init, glib, snapd, tmux). **Wave 0에서 처리** |

K3s 번들(kubectl v1.36.4, coredns 1.14.7, metrics-server v0.9.0, local-path-provisioner v0.0.37)은 노드에 종속 — 별도 조치 없음.

### Renovate — 현재 완전 정지

- `.github/workflows/` 없음, Dependency Dashboard 이슈 0건, Renovate PR 0건, 저장소 설치 앱 조회 불가(401).
- `renovate.json5`는 유효. `customManagers` 7개(K3s plan, cnpg 매니페스트, barman, CNPG operand, OT Redis, browseros, 및 원격 URL 2건)가 이미 정확히 작성되어 있음.

---

## Approach

**웨이브 단위 스테이징.** 리스크가 낮은 것부터, 되돌릴 수 없는 것일수록 나중에.

```
Wave 0  안전망 + 호스트 패치        ─ 커밋 없음(호스트), etcd 스냅샷
Wave 1  무상태 인프라 차트           ─ traefik x2, monitoring(k8s-monitoring)
Wave 2  무상태 앱/차트 + 이미지      ─ open-webui, nextcloud-mcp, searxng, cliproxyapi, cloudflared, bifrost
Wave 3  상태 저장 앱 이미지          ─ n8n + runners  ← DB 마이그레이션 동반, 백업 게이트
Wave 4  Renovate 부활                ─ 코드만, 클러스터 무영향 (언제 해도 안전)
Wave 5  K3s 재점검                   ─ 버전 변경 없음. 노드 재부팅/apt 반영 여부만 결정
Wave 6  문서/런북 갱신
```

원칙:
- **한 웨이브 = 한 커밋** → 문제 시 `git revert <sha>` + `flux reconcile` 1회로 복구.
- 모든 이미지 bump에서 태그 + digest를 동시에 갱신하고, **파일이 기존에 쓰던 digest 규약(index/amd64)을 유지**한다.
- Wave 4(Renovate)는 클러스터에 아무것도 배포하지 않으므로 Wave 3와 순서를 바꿔도 무방하다.
- **버전 변경이 없는 항목은 커밋하지 않는다.** "이미 최신" 확인 자체를 Wave 6 문서에 남긴다.

---

## Files to modify

**Wave 1**
- `infrastructure/base/traefik/traefik.helm-release.yaml`
- `infrastructure/base/traefik-external/traefik.helm-release.yaml`
- `infrastructure/base/monitoring/monitoring.k8s-monitoring.helm-release.yaml`

**Wave 2**
- `apps/base/openwebui/openwebui.helm-release.yaml` + `apps/base/openwebui/openwebui.values.yaml`
- `apps/base/nextcloud-mcp/nextcloud-mcp.helm-release.yaml` + `apps/base/nextcloud-mcp/nextcloud-mcp.gateway.yaml`
- `apps/base/searxng/searxng.deployment.yaml`
- `apps/base/cliproxyapi/cliproxyapi.deployment.yaml`
- `infrastructure/base/cloudflared/cloudflared.deployment.yaml`
- `apps/base/bifrost/bifrost.statefulset.yaml`

**Wave 3**
- `apps/base/n8n/n8n.deployment.yaml`
- `apps/base/n8n/n8n.task-runner.deployment.yaml`

**Wave 4**
- `.github/workflows/renovate.yml` (신규)
- `renovate.json5` (필요 최소 수정만 — 예: `onboarding: false`, `rebaseWhen`, `prHourlyLimit` 등 실제 운영 파라미터)

**Wave 5**
- (버전 변경 없음) 필요 시 `ansible/roles/setup_k3s_server/defaults/main.yml`만

**Wave 6**
- `readme.md` (Version sweep 섹션 갱신: Renovate 재가동 사실, 노드 패치 절차, digest 규약표)
- `plans/update-all-resources.md` (본 문서, 완료 체크 표시)

**변경하지 않는 것**
- `clusters/production/flux-system/gotk-components.yaml` (Flux v2.10.0 = 최신)
- `infrastructure/base/longhorn/**`, `cloudnative-pg/**`, `system-upgrade-controller/**` (모두 최신)
- 모든 `*.secret.yaml` / `*.secrets.yaml`

---

## Reuse

새 스크립트/도구를 만들지 않고 이미 검증된 경로를 재사용한다.

- **렌더 검증**: `kubectl kustomize ./apps/overlays/production`, `kubectl kustomize ./infrastructure/overlays/production`,
  변경한 베이스별 `kubectl kustomize ./infrastructure/base/<name>`. `./clusters/production`은 kustomize 루트가 아니다(AGENTS.md).
  `./clusters/production/flux-system`은 루트다.
- **차트 값 호환성 사전 확인**: `helm template <name> <repo>/<chart> --version <new> -f <values> --kube-version 1.37.1`.
  이번 감사에서 traefik 42.2.0(6 kinds, 이미지 동일), k8s-monitoring 4.6.0(40 kinds, alloy-operator만 이동),
  open-webui 17.5.0(값 키 그대로 소비) 확인 완료. **차트 values는 HelmRelease 안에 인라인**되어 있으므로
  `values:` 블록만 4칸 dedent 해 임시 파일로 떠서 렌더한다.
- **digest 조회**:
  ```bash
  docker buildx imagetools inspect <ref> --format '{{json .Manifest}}'   # index digest = .digest
  # amd64 platform digest = .manifests[] | select(.platform.architecture=="amd64") | .digest
  ```
  index 규약 파일과 amd64 규약 파일을 구분해서 적용한다(위 표 참조).
- **백업 게이트 자산**: Longhorn RecurringJob 3종
  (`longhorn-system-backup` 04:00 / `longhorn-volume-backup` 03:30·15:30 / `longhorn-snapshot-cleanup`),
  CNPG `ScheduledBackup`(4시간 주기, 13개 클러스터), K3s etcd 스냅샷(`kubectl get etcdsnapshotfile`).
  새 백업 잡을 만들지 않고 이들을 게이트로 쓴다.
- **K3s 업그레이드 경로**: `system-upgrade-controller` + `k3s-server` Plan. 이번엔 버전 변경이 없어 트리거되지 않는다.
- **Ansible**: `ansible/Makefile`의 `preflight`/`check`/`apply`/`verify`. 부트스트랩/복구 및 노드 검증 전용.
- **Docker Hub rate limit 회피(런북 기존 지식)**:
  `k3s ctr -n k8s.io images pull mirror.gcr.io/<path>:<tag>` 후 `k3s ctr -n k8s.io images tag ...`.
  워크스테이션과 노드가 같은 egress IP를 공유하므로 대량 probe 시 429가 발생할 수 있다.
- **`backup-cleanup` 스위치**: `infrastructure/base/backup-cleanup/backup-cleanup.configmap.yaml`의
  `backup-cleanup-control` — 게이트 중 백업이 자동 삭제되지 않게 잠시 끌 때 재사용.

---

## Steps

### Wave 0 — 안전망 + 호스트 패치 (커밋 없음)

- [ ] 롤백 기준점 기록: `git rev-parse HEAD` → `2163502` (main, clean)
- [ ] Flux 전체 상태: `flux --context homelab get kustomizations -A` → 51개 전부 `Ready`
- [ ] 소스 확인: `flux --context homelab get source git flux-system` → `Ready` @ `main@sha1:2163502`
- [ ] Longhorn 게이트:
      ```bash
      kubectl --context homelab -n longhorn-system get systembackups.longhorn.io \
        --sort-by=.metadata.creationTimestamp | tail -3          # 최신이 Ready
      kubectl --context homelab -n longhorn-system get recurringjobs.longhorn.io
      kubectl --context homelab -n longhorn-system get volumes.longhorn.io \
        -o custom-columns="NAME:.metadata.name,STATE:.status.state,ROBUST:.status.robustness"
      ```
      기준: 최신 SystemBackup `Ready`(2026-10-31 04:00 관측), 모든 볼륨 `robustness=healthy`.
- [ ] CNPG 게이트 (13개 클러스터):
      ```bash
      kubectl --context homelab get clusters.postgresql.cnpg.io -A
      kubectl --context homelab get backups.postgresql.cnpg.io -A --sort-by=.metadata.creationTimestamp | tail -15
      ```
      기준: 전부 `Cluster in healthy state`, 각 클러스터 최신 Backup `completed`.
- [ ] etcd 스냅샷 강제 생성(업그레이드 직전 기준점):
      ```bash
      kubectl --context homelab get etcdsnapshotfile -n kube-system | tail -3
      ssh homelab 'sudo k3s etcd-snapshot save --name pre-sweep-20261101'
      ```
- [ ] **host apt 패치** (7건: cloud-init, glib 2.80.0-6ubuntu3.10, snapd 2.77.1, tmux 3.4-1ubuntu0.2):
      ```bash
      ssh homelab 'sudo apt-get update && sudo apt-get -y upgrade'
      ssh homelab 'ls /var/run/reboot-required'
      ```
      재부팅이 필요하면 **Wave 5까지 미루고** 여기서는 설치만. 재부팅은 K3s 재시작을 동반하므로 별도 판단.
- [ ] 게이트 실패 시 **중단**하고 백업 문제부터 해결

### Wave 1 — 무상태 인프라 차트 (traefik, monitoring)

- [ ] `infrastructure/base/traefik/traefik.helm-release.yaml`: `42.1.3` → **`42.2.0`**
- [ ] `infrastructure/base/traefik-external/traefik.helm-release.yaml`: `42.1.3` → **`42.2.0`**
- [ ] `infrastructure/base/monitoring/monitoring.k8s-monitoring.helm-release.yaml`: `4.5.5` → **`4.6.0`**
- [ ] 렌더 회귀 확인 (감사에서 이미 확인했으나 커밋 전 재확인):
      ```bash
      # HelmRelease의 values: 블록을 4칸 dedent해 /tmp/*.yaml로 저장한 뒤
      helm template t traefik/traefik --version 42.2.0 -f /tmp/traefik.values.yaml | grep -c '^kind:'
      helm template m grafana/k8s-monitoring --version 4.6.0 -f /tmp/monitoring.values.yaml | grep -c '^kind:'
      ```
      기대: traefik 6 kinds, monitoring 40 kinds (변경 전과 동일).
- [ ] 로컬 검증:
      `kubectl kustomize ./infrastructure/base/traefik`, `.../traefik-external`, `.../monitoring`,
      `kubectl kustomize ./infrastructure/overlays/production`
- [ ] 커밋 & 푸시 (1커밋): `chore(infra): bump traefik 42.2.0 and k8s-monitoring 4.6.0`
- [ ] 재조정 & 검증:
      ```bash
      flux --context homelab reconcile kustomization traefik --with-source
      flux --context homelab reconcile kustomization traefik-external --with-source
      flux --context homelab reconcile kustomization monitoring --with-source
      flux --context homelab get helmreleases -A
      kubectl --context homelab -n traefik-system get pods
      kubectl --context homelab -n traefik-external-system get pods
      kubectl --context homelab -n monitoring-system get pods
      ```
      확인: 외부/내부 진입점 HTTP 200, TLS 인증서 유효, Grafana 접속, Alloy/VM 타깃 정상,
      `alloy-operator` 이미지가 `1.14.4`로 이동.

### Wave 2 — 무상태 앱 차트 + 이미지

- [ ] **open-webui**: `apps/base/openwebui/openwebui.helm-release.yaml` `17.4.0` → **`17.5.0`**,
      `apps/base/openwebui/openwebui.values.yaml` `image.tag: v0.12.4@sha256:a5b9e403…` → **`v0.12.5@sha256:03443b8d…`**(index digest)
- [ ] **nextcloud-mcp**: `nextcloud-mcp.helm-release.yaml` 차트 `0.105.13` → **`0.105.16`**,
      postRenderer `newTag: 0.202.1` → **`0.203.0`**, `digest: sha256:653b682f…` → **`sha256:af1034fe…`**(amd64)
- [ ] **nextcloud-mcp gateway** nginx: `1.30.6-alpine@sha256:969ccb55…` → **`1.31.7-alpine@sha256:d43f0577…`**(amd64)
- [ ] **searxng**: `2026.10.28-c360868e5@sha256:268a4b46…` → **`2026.10.30-ffa88e3ba@sha256:f4aa660c…`**(index)
- [ ] **cliproxyapi**: `v8.0.47@sha256:d1874eba…` → **`v8.0.48@sha256:b3cec78c…`**(amd64)
- [ ] **cloudflared**: `2026.10.5@sha256:1b1d34d0…` → **`2026.10.7@sha256:4955524a…`**(index)
- [ ] **bifrost**: `docker.io/maximhq/bifrost:latest@sha256:a1c906…` → **`docker.io/maximhq/bifrost:v2.4.0@sha256:a1c906…`**
      (digest 동일 — `latest`가 v2.4.0을 가리키므로 동작 변화 없이 태그만 명시화. Renovate `pinDigests` 대상에서 안전해짐)
- [ ] `kubectl kustomize ./apps/base/<name>` 각각 + `kubectl kustomize ./apps/overlays/production`
- [ ] 커밋 & 푸시 (1커밋): `chore(apps): bump stateless apps and charts (open-webui, nextcloud-mcp, searxng, cloudflared)`
- [ ] 재조정 & 검증:
      ```bash
      for k in openwebui-deployment nextcloud-mcp-deployment searxng-deployment cliproxyapi-production cloudflared-deployment bifrost-production; do
        flux --context homelab reconcile kustomization $k --with-source
      done
      kubectl --context homelab get pods -A | grep -vE "Running|Completed"
      ```
      스모크: Open WebUI 채팅 1회, Nextcloud MCP 엔드포인트 200, SearXNG 검색 1회(내부 전용 유지 확인),
      Cloudflare 터널 유지, Bifrost 라우트 1회.
      **주의**: SearXNG는 `feat(searxng): migrate search route to intranet-only` 이후 intranet 전용 —
      외부에서 접근 불가가 정상이다.

### Wave 3 — 상태 저장 앱 이미지 (n8n) ← 백업 게이트 필수

- [ ] **선행: Wave 0 백업 게이트 재확인** + n8n 전용 강제 백업
      ```bash
      kubectl --context homelab -n n8n-system get clusters.postgresql.cnpg.io
      kubectl --context homelab -n n8n-system get backups.postgresql.cnpg.io --sort-by=.metadata.creationTimestamp | tail -3
      ```
- [ ] `apps/base/n8n/n8n.deployment.yaml`: `2.45.5@sha256:9f6d0a59…` → **`2.45.7@sha256:9a8d8dce…`**(index)
- [ ] `apps/base/n8n/n8n.task-runner.deployment.yaml`: `runners 2.45.5@sha256:357c1898…` → **`2.45.7@sha256:2f070888…`**(index)
      **두 파일의 버전을 반드시 일치**시킨다(n8n task runner는 메이저/마이너가 어긋나면 실행 거부).
- [ ] `kubectl kustomize ./apps/base/n8n` + `kubectl kustomize ./apps/overlays/production`
- [ ] 커밋 & 푸시: `chore(n8n): bump to 2.45.7 and match the task runner`
- [ ] 재조정 & 검증:
      ```bash
      flux --context homelab reconcile kustomization n8n-deployment --with-source
      kubectl --context homelab -n n8n-system get pods
      kubectl --context homelab -n n8n-system logs deploy/n8n --tail=100 | grep -iE "migration|error"
      ```
      스모크: 기존 워크플로 1개 수동 실행 성공, task runner가 작업을 처리하는지 확인.

### Wave 4 — Renovate 부활

클러스터에 아무것도 배포하지 않는다. 코드/설정만 변경.

- [ ] `.github/workflows/renovate.yml` 추가. **`RENOVATE_TOKEN`(classic PAT, `repo`+`workflow`)** 또는
      GitHub App(`RENOVATE_APP_ID` + `RENOVATE_APP_PRIVATE_KEY`) 중 하나를 저장소 시크릿으로 등록하는 것을 전제로 한다.
      - `permissions: contents: read` + job에서 `renovatebot/github-action@v41` 계열 사용
      - `schedule`은 `renovate.json5`의 `schedule: ['before 6am on saturday']`(Asia/Seoul)와 충돌하지 않게
        UTC 기준 토요일 21:00 이전(=`0 15-20 * * 5`)으로 두거나, 워크플로 cron을 두고 `renovate.json5`의
        `schedule`을 제거한다. **둘 중 하나만 스케줄을 소유하게 한다** (이중 스케줄은 디버깅을 어렵게 만든다).
      - `workflow_dispatch`도 함께 열어 수동 실행 가능하게 한다.
      - `permissions`는 최소: `contents: write`, `pull-requests: write`, `issues: write`.
- [ ] `renovate.json5` 최소 수정:
      - `onboarding: false` (이미 온보딩된 저장소)
      - `dependencyDashboard: true` 유지 → Dashboard 이슈가 생기는지 확인
      - `prConcurrentLimit: 5`, `minimumReleaseAge: '3 days'`, `automerge: false` 유지
      - `packageRules`는 그대로. `matchUpdateTypes: ['major']` + stateful 목록의 `dependencyDashboardApproval: true`가
        이번 스윕에서 수동 판단이 필요했던 항목(k3s, cnpg, longhorn, redis-operator 등)을 정확히 덮는다.
- [ ] **`customManagers` 검증** — 이번 감사에서 실제 파일과 정규식이 여전히 맞는지 확인:
      | manager | 대상 파일 | 확인 |
      |---|---|---|
      | CNPG operand | `apps/base/**/*.database.yaml` 의 `imageName:` | 13개 파일 매칭, `versioningTemplate` `18.6-standard-bookworm` 파싱 OK |
      | OT Redis | `apps/base/searxng/**/*.redis.yaml` 의 `quay.io/opstree/redis:` | 매칭 OK (단, `nextcloud/`·`outline/`의 동일 이미지는 **범위 밖** — 의도된 제한인지 결정) |
      | K3s Plan | `infrastructure/base/k3s-upgrade/k3s-server-plan.yaml` | 매칭 OK |
      | CNPG 매니페스트 | `infrastructure/base/cloudnative-pg/kustomization.yaml` | 매칭 OK |
      | Barman 플러그인 | 같은 파일 | 매칭 OK |
      | browseros | `apps/base/browseros/*.deployment.yaml` | 매칭 OK |
      > OT Redis manager의 `managerFilePatterns`가 `searxng`로 좁혀져 있어 nextcloud/outline의 redis 이미지는
      > Renovate가 갱신하지 못한다. 이번에 범위를 `apps/base/**/*.redis.yaml`로 넓힐지 결정한다(권장: 넓힌다).
- [ ] `.github/workflows` 최초 생성이므로 **Actions가 저장소에서 활성인지** 확인.
- [ ] 커밋 & 푸시: `chore(ci): revive Renovate with a scheduled workflow`
- [ ] 검증 (24시간 내):
      ```bash
      gh workflow list --repo tinyrack-net/homelab
      gh run list --repo tinyrack-net/homelab --workflow renovate.yml --limit 5
      gh issue list --repo tinyrack-net/homelab --search renovate   # Dependency Dashboard 생성 확인
      gh pr list --repo tinyrack-net/homelab --search renovate
      ```
      기대: Dashboard 이슈 1건, 그리고 **버전이 이미 최신인 항목은 PR이 생기지 않는다**(Wave 1~3을 먼저 끝낸 효과).
      남는 PR은 `customManagers`가 잡는 항목과, 이번에 의도적으로 남긴 항목뿐이어야 한다.
- [ ] **`readme.md`의 "Renovate is not running" 문단을 Wave 6에서 반드시 갱신** (문서와 사실 불일치 방지)

### Wave 5 — K3s / 노드 재점검

- [ ] K3s 버전 재확인: 노드 `v1.37.1+k3s1` = 최신 채널 값 → **Plan/Ansible 변경 없음(커밋 없음)**
      ```bash
      curl -s https://update.k3s.io/v1-release/channels | jq -r '.data[] | select(.name=="latest") | .latest'
      kubectl --context homelab get node homelab -o wide
      kubectl --context homelab -n system-upgrade get plans
      ```
- [ ] Wave 0에서 `/var/run/reboot-required`가 생겼다면 재부팅 결정:
      - 재부팅은 단일 노드 전체 워크로드 재시작 → Wave 3까지 검증이 끝난 **지금이 가장 안전한 시점**
      - 재부팅 전: etcd 스냅샷 + Longhorn SystemBackup 최신 확인
      ```bash
      ssh homelab 'sudo k3s etcd-snapshot save --name pre-reboot-20261101 && sudo reboot'
      # 복귀 후
      kubectl --context homelab get nodes
      kubectl --context homelab get pods -A | grep -vE "Running|Completed"
      kubectl --context homelab get clusters.postgresql.cnpg.io -A
      kubectl --context homelab -n longhorn-system get volumes.longhorn.io
      flux --context homelab get kustomizations -A
      ```
- [ ] 재부팅이 불필요하면 이 웨이브는 "확인만 하고 종료"

### Wave 6 — 문서 갱신

- [ ] `readme.md` "Version sweep" 섹션:
      - **"Renovate is not running" 문단 삭제/교체** — 이제 워크플로가 있고 Dashboard 이슈가 있다
      - 확인 명령을 그대로 유지(`gh issue list`, `gh pr list`, `ls .github/workflows`)
      - 수동 스윕 체크리스트는 **비상용/검증용으로 유지** (Renovate가 PR을 못 만드는 항목이 남아 있으므로)
      - **digest 규약표 추가** (index vs amd64 — 위 표를 문서로 옮긴다)
      - 노드 apt 패치 절차 추가 (Wave 0에서 실제로 수행한 내용)
- [ ] 본 문서에 완료 체크 표시 후 `plans/` 유지 (지난 스윕처럼 완료 후 정리 커밋으로 제거)
- [ ] 커밋 & 푸시: `docs: record the 2026-11 version sweep and the Renovate revival`

---

## Verification

### 1. 렌더 검증 (푸시 전)
```bash
kubectl kustomize ./apps/overlays/production
kubectl kustomize ./infrastructure/overlays/production
kubectl kustomize ./infrastructure/base/traefik
kubectl kustomize ./infrastructure/base/traefik-external
kubectl kustomize ./infrastructure/base/monitoring
kubectl kustomize ./apps/base/openwebui
kubectl kustomize ./apps/base/nextcloud-mcp
kubectl kustomize ./apps/base/searxng
kubectl kustomize ./apps/base/cliproxyapi
kubectl kustomize ./apps/base/bifrost
kubectl kustomize ./apps/base/n8n
```
`./clusters/production`은 kustomize 루트가 아니다(AGENTS.md). `./clusters/production/flux-system`은 루트다.

### 2. Flux 검증 (푸시 후)
```bash
flux --context homelab reconcile source git flux-system
flux --context homelab reconcile kustomization <name> --with-source
flux --context homelab get kustomizations -A     # 전부 Ready, Applied revision = 새 SHA
flux --context homelab get helmreleases -A       # 새 차트 버전, Ready
flux --context homelab events --all-namespaces   # 경고 확인
```

### 3. 워크로드 검증
```bash
kubectl --context homelab get pods -A | grep -vE "Running|Completed"
kubectl --context homelab get clusters.postgresql.cnpg.io -A    # 13개 healthy
kubectl --context homelab get pvc -A | grep -v Bound
kubectl --context homelab -n longhorn-system get volumes.longhorn.io \
  -o custom-columns="NAME:.metadata.name,ROBUST:.status.robustness" | grep -v healthy
```

### 4. 기능 스모크 (수동)
- Traefik 내부/외부 진입점 HTTP 200, TLS 유효
- Grafana 접속 + 새 메트릭 수신, Alloy/VM 타깃 up
- Open WebUI 채팅, SearXNG 검색(intranet 전용), Cloudflare 터널 경유 서비스 1개
- n8n 워크플로 1개 실행 성공 (task runner 동작 확인)
- Nextcloud ↔ Collabora 문서 편집 1회 (nextcloud-mcp/nginx 변경 영향 없음 확인)

### 5. 백업 파이프라인 재가동 확인
업그레이드 후 첫 주기의 Longhorn `longhorn-volume-backup`(03:30/15:30)과
CNPG ScheduledBackup(4시간)이 `completed`로 끝나는지 확인한다.

---

## Rollback

| 웨이브 | 방법 | 완전 복구 가능? |
|---|---|---|
| 1 차트 | `git revert <sha>` + reconcile — Helm이 직전 리비전으로 롤백 | 가능 |
| 2 무상태 앱 | `git revert <sha>` + reconcile | 가능 |
| 3 n8n | `git revert <sha>` — **DB 스키마 마이그레이션은 되돌아가지 않는다** | 부분적. 필요 시 CNPG Barman S3 복원 |
| 4 Renovate | `git revert <sha>` (클러스터 무영향) | 가능 |
| 5 노드 재부팅 | 재부팅 자체는 롤백 대상 아님. 문제 시 노드 상태 점검 | 해당 없음 |

**공통**: `git revert` → `flux --context homelab reconcile source git flux-system` → 영향받은 Kustomization reconcile.
Wave 3 이후 문제는 `readme.md`의 Disaster Recovery 절차(CNPG Barman S3 + Longhorn 시스템 백업)를 따른다.

---

## Risks

| 리스크 | 영향 | 완화 |
|---|---|---|
| **n8n 2.45.5 → 2.45.7 DB 마이그레이션** | 되돌릴 수 없는 스키마 변경 가능 | Wave 3 전 백업 게이트, 패치 릴리스라 위험 낮음, 배포 직후 마이그레이션 로그 확인 |
| **n8n ↔ runners 버전 불일치** | task runner가 작업 거부 | 두 파일을 **같은 커밋**에서 동시에 갱신 |
| **nextcloud-mcp postRenderer digest 불일치** | 이미지 pull 실패 또는 잘못된 이미지 배포 | amd64 digest 규약 유지(기존 pin이 amd64였음), `docker buildx imagetools inspect`로 재확인 |
| **open-webui values 키 소진** | 차트가 값을 무시해 설정이 조용히 사라짐 | 17.4.0→17.5.0 렌더 비교 완료(파드/이미지 동일). 배포 후 redis 활성·replicaCount 2 유지 확인 |
| **traefik 42.2.0 values 변경** | 진입점 장애 = 모든 외부 접근 불가 | 렌더 kinds 6개 동일 확인. 배포 후 내부/외부 진입점 HTTP 확인, 문제 시 즉시 revert |
| **monitoring 4.6.0 → alloy-operator 1.14.4 자동 이동** | 텔레메트리 수집 중단 가능 | 배포 후 Alloy/VM 타깃 up 확인, Grafana 데이터 수신 확인 |
| **digest 규약 혼동(index vs amd64)** | 태그·digest 불일치로 배포 실패 | 파일별 기존 pin이 index인지 amd64인지 확인 후 동일 규약 적용(위 표) |
| **Docker Hub 429** | 이미지 pull 실패로 롤아웃 지연 | 감사 중 이미 40여 회 probe함. 롤아웃 시 `mirror.gcr.io` pre-seed 사용 |
| **Renovate 첫 실행 폭주** | PR/Dashboard 홍수 | `prConcurrentLimit: 5`, `prHourlyLimit` 설정, `minimumReleaseAge: 3 days`, major는 `dependencyDashboardApproval: true` |
| **Renovate 스케줄 이중화** | 예측 불가한 실행 시점 | 워크플로 cron과 `renovate.json5`의 `schedule` 중 **하나만** 소유 |
| **`RENOVATE_TOKEN` 권한 부족** | 워크플로 실패 | `repo` + `workflow` scope, 또는 GitHub App 사용. 실패 시 Wave 6에서 문서로 사실관계 정정 |
| **노드 재부팅(Wave 5)** | 단일 노드 전체 재시작, Longhorn detach/attach | 백업 직후 수행, 복귀 후 노드/PVC/CNPG/Longhorn/kustomization 5종 확인 |

---

## Open Questions

1. **노드 재부팅 시점**: apt 7건은 재부팅 없이 반영 가능하지만 snapd/glib는 재부팅이 권장된다.
   Wave 5에서 재부팅할지, 아니면 다음 유지보수 때로 미룰지.
2. **Renovate 인증 방식**: `RENOVATE_TOKEN`(classic PAT) vs GitHub App. PAT가 단순하지만 만료/권한 관리가 필요하다.
3. **OT Redis customManager 범위**: `searxng`만 잡고 있어 nextcloud/outline의 redis 이미지가 갱신 대상에서 빠진다.
   범위를 `apps/base/**/*.redis.yaml`로 넓힐지.
4. **bifrost `latest` → `v2.4.0` 명시화**: digest가 동일해 동작 변화는 없다. 다만 upstream이 `latest`를 계속 움직이므로
   이 변경으로 자동 추적이 끊긴다(digest pin이므로 어차피 끊겨 있었음). 명시적 태그를 유지할지 확인.

---

## 실행 결과 (2026-11-01)

### 커밋

| 커밋 | 내용 |
|---|---|
| `70360fa` | traefik x2 → 42.2.0, k8s-monitoring → 4.6.0 |
| `8db8270` | open-webui 17.5.0 + v0.12.5, nextcloud-mcp 0.105.16/0.203.0/nginx 1.31.7, searxng, cliproxyapi v8.0.48, cloudflared, bifrost 태그 명시화 |
| `f8b8c72` | n8n + runners → 2.45.7 |
| `791bde4` | Renovate 워크플로 + OT Redis manager 범위 확장 |
| (이 커밋) | readme Version sweep/런북 갱신 |

### 계획과 달라진 점

1. **선행 결함 2건을 먼저 고쳤다.** Wave 0 백업 게이트에서 다음을 발견했다.
   - `syncthing-backup-20261031040000`, `mathesar-backup-20261031040000` 이 `started` 상태로 13시간 방치.
     04:00 무렵 API 서버 정지로 CNPG 컨트롤러가 status를 쓰지 못한 것이 원인. 실행 중인 백업
     프로세스가 없음을 확인하고 두 `Backup` CR만 삭제 → 다음 슬롯(08:00)이 정상 `completed`.
   - `immich-backup-20261031160000` 실패. 로그 끝이 `Read timeout on endpoint URL` +
     `ValueError: I/O operation on closed file` — S3 순간 타임아웃. 일회성 `Backup` CR로 재실행해 `completed` 확인.
2. **K3s는 변경 없음.** 노드가 이미 최신 채널 값(`v1.37.1+k3s1`)이고 v1.37.2는 rc 단계.
   `plans/` 의 Wave 5는 "확인만 하고 종료"로 끝났다.
3. **bifrost `latest` → `v2.4.0` 태그 명시화.** digest가 동일해 동작 변화 없음. 대신 Renovate `pinDigests`
   대상에서 안전해진다.
4. **Renovate 스케줄 소유권.** 워크플로 cron(`0 18 * * *`)과 `renovate.json5`의
   `schedule: ['before 6am on saturday']`가 겹치지 않도록 **스케줄은 json5가 단독 소유**하고
   워크플로는 일일 트리거만 제공. 18:00 UTC = 토요일 03:00 KST로 윈도우 안에 떨어지는 것을 계산으로 확인.
5. **OT Redis customManager 범위 확장.** `apps/base/searxng` → `apps/base/**.redis.yaml`.
   nextcloud·outline이 동일 이미지를 쓰는데 기존 패턴에 걸리지 않아 영원히 갱신되지 않았다.
   수정 후 Dashboard에서 3개 파일 모두 감지 확인.
6. **digest 규약 정정.** 계획서에는 `eceasy/cli-proxy-api`가 amd64 핀이라고 적었으나 실제로는 **index** 핀이다.
   파일별 기존 규약을 확인해 적용했고, readme 표를 정정했다.

### 검증 결과

- 렌더: `kubectl kustomize` 로 apps/infrastructure overlays + 변경한 6개 base 전부 OK.
- 차트 호환: traefik 42.2.0 = 6 kinds·`v3.7.16` 동일, k8s-monitoring 4.6.0 = 28 kinds,
  구조 diff는 Alloy `cache_ttl` 인자 추가와 버전 라벨뿐(alloy-operator 1.14.3 → 1.14.4).
  open-webui 17.5.0은 기존 values 키를 그대로 소비.
- 배포: traefik/monitoring/n8n/앱 6종 HelmRelease 및 Deployment 모두 Ready. n8n은 마이그레이션 후
  `/healthz` `ok`, task runner가 2.45.7로 브로커 재연결.
- 진입점: monitor 302, n8n 200, cloud 302 (TLS verify 0).
- Renovate: 최초 실행 success, Dependency Dashboard 이슈 #76 생성, PR 0건(업그레이드 완료 상태이므로 기대대로).
  n8n 2.46.3은 status check 대기로 보류 — prerelease 필터가 동작하는 것으로 확인.

### 남은 이슈 (이번 범위 밖, 사용자 결정)

- **k3s 반복 재시작.** `NRestarts=49`. 근본 원인은 etcd `slow fdatasync` 최대 6.1초 —
  루트 디스크가 회전식(`ROTA=1`)이고 79% 사용 중이다. lease 갱신이 데드라인을 넘기면 k3s가
  exit 1로 종료하고, 그 순간 모든 컨트롤러가 exit 255로 재시작되며 진행 중인 API 쓰기가 유실된다
  (위 두 백업 사고의 원인). 버전 업그레이드와 무관한 기존 문제이며, 이번 작업에서는 기록만 하고
  손대지 않기로 결정했다. 별도 작업으로 etcd 디스크 분리 또는 노드 스토리지 정리가 필요하다.
- Renovate가 제안한 후속 업데이트: `actions/checkout` v7, python/node digest, postgres 18 등.
  Dashboard에서 개별 승인하면 된다.
