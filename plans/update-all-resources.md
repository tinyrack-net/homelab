# Plan: 클러스터 내 모든 리소스를 최신 버전으로 업데이트

## Context

`homelab` 클러스터(단일 노드 K3s, Flux GitOps)의 모든 계층 — Flux 컨트롤러, 인프라 Helm 차트, 플랫폼 컨트롤러, 애플리케이션 이미지, K3s 노드 — 이
upstream 최신 릴리스 대비 뒤처져 있다. `renovate.json5`는 존재하지만 GitHub에 Dependency Dashboard 이슈도, PR도, 워크플로도 없어 **Renovate가 실제로 동작하지 않는 상태**다.
따라서 이번 작업은 "자동화 복구"가 아니라 **한 번의 수동 전면 스윕**이며, 이후를 위한 수동 스윕 런북을 남기는 것이 목표다.

목표 결과: 모든 컴포넌트가 2026-10-08 기준 최신 버전으로 수렴하고, 각 단계마다 백업 확인 → 배포 → 헬스 검증을 거쳐 되돌릴 수 있는 지점을 유지한다.

### 확정된 결정 (사용자 승인)

| # | 항목 | 결정 |
|---|------|------|
| 1 | 범위 | **전부** — K3s 노드 업그레이드와 Flux 컨트롤러 포함 |
| 2 | 전달 방식 | `main`에 **웨이브 단위 스테이징**, 웨이브당 커밋 1개, 각 웨이브 사이 검증 + reconcile (main push 즉시 배포됨) |
| 3 | 리스크 게이트 | **백업 + 단계별 검증** — 리스크 있는 웨이브 전 Longhorn system backup / CNPG Barman S3 백업 최신 여부 확인, 컴포넌트 하나씩 올리고 헬스 확인 후 다음으로 |
| 4 | Renovate | **손대지 않음** (설정 변경 없음). 이번 작업은 주기적 수동 스윕으로 취급 |

> 결정 4에 따라 초안의 "Wave 6 — Renovate 조사/활성화" 단계는 삭제하고, 대신 **수동 스윕 런북**을 문서로 남긴다.

---

## 현재 버전 감사 (2026-10-08 기준, current → latest)

### Flux 컨트롤러 (upstream `flux2` v2.9.6)

| 컴포넌트 | 현재 | 최신 |
|---|---|---|
| source-controller | v1.9.5 | **v1.9.6** |
| kustomize-controller | v1.9.5 | **v1.9.6** |
| helm-controller | v1.6.4 | **v1.6.5** |
| notification-controller | v1.9.4 | v1.9.4 (동일) |
| image-reflector-controller | v1.2.5 | v1.2.5 (동일) |
| image-automation-controller | v1.2.5 | v1.2.5 (동일) |

### Helm 차트 / 원격 매니페스트

| 파일 | 현재 | 최신 |
|---|---|---|
| `infrastructure/base/longhorn/install/longhorn.helm-release.yaml` | 1.12.1 | **1.13.0** |
| `infrastructure/base/monitoring/monitoring.stack.helm-release.yaml` (victoria-metrics-k8s-stack) | 0.93.0 | **0.95.2** |
| `infrastructure/base/monitoring/monitoring.k8s-monitoring.helm-release.yaml` | 4.5.2 | **4.5.3** |
| `infrastructure/base/traefik/traefik.helm-release.yaml` | 41.6.0 | **41.6.1** |
| `infrastructure/base/traefik-external/traefik.helm-release.yaml` | 41.6.0 | **41.6.1** |
| `infrastructure/base/prometheus-operator-crds/prometheus-operator-crds.helm-release.yaml` | 32.0.0 | **32.0.1** |
| `apps/base/repositories/immich.yaml` (OCIRepository `spec.ref.tag`) | 0.13.2 | **0.13.4** |
| `infrastructure/base/cloudnative-pg/kustomization.yaml` (remote URL) | cloudnative-pg v1.30.0 / barman-cloud v0.15.0 | **v1.30.1 / v0.15.1** |
| `infrastructure/base/system-upgrade-controller/system-upgrade-controller.yaml:269` | `rancher/system-upgrade-controller:v0.20.1` | **v0.20.2** |

변경 없음(확인 완료): cert-manager v1.21.2, sealed-secrets 2.20.0, kyverno 3.9.1, mariadb-operator(+crds) 26.10.1, juicefs-csi-driver 0.33.0, redis-operator 0.26.1, reflector 10.0.65, open-web-ui chart 16.6.0, cilium 1.20.2(+bundle), multus v4.3.1-thick.

### 컨테이너 이미지

| 파일 | 현재 | 최신 |
|---|---|---|
| `apps/base/n8n/n8n.deployment.yaml` | n8nio/n8n 2.40.5 | **2.43.1** |
| `apps/base/n8n/n8n.task-runner.deployment.yaml` | n8nio/runners 2.40.5 | **2.43.1** |
| `apps/base/immich/app/values.yaml` (server + machine-learning) | v3.2.2 (+digest) | **v3.3.0** (+새 digest) |
| `apps/base/home-assistant/home-assistant.deployment.yaml` | 2026.9.3 / zigbee2mqtt 2.14.1 / mosquitto 2.0.22 | **2026.10.0 / 2.14.2 / 2.1.2** |
| `apps/base/searxng/searxng.deployment.yaml` | 2026.9.21-f372096fb | 2026.10.7-6671d89be |
| `apps/base/karakeep/karakeep.meilisearch.deployment.yaml` | getmeili/meilisearch v1.54.0 | v1.54.3 |
| `apps/base/openwebui/openwebui.values.yaml` (tika) | 4.0.0-full | 4.1.0-full |
| `infrastructure/base/cloudflared/cloudflared.deployment.yaml` | 2026.9.1 | 2026.10.0 |
| `apps/base/cliproxyapi/cliproxyapi.deployment.yaml` | eceasy/cli-proxy-api v8.0.10 | v8.0.20 |
| `apps/base/vivident-tailscale-router/vivident-tailscale-router.statefulset.yaml` (2곳: 32, 66행) | tailscale/tailscale v1.102.4 | v1.104.1 |
| `apps/base/guacamole/guacamole.database-init.yaml` | postgres 17.6-bookworm | 17.11-bookworm |

변경 없음: karakeep 0.33.2, karakeep-chrome, rustdesk-server-s6 1.1.16, guacd 1.6.0, opstree/redis v8.10.1, CNPG operand(17.11 / 18.6), vchord-scratch pg18-v1.1.1, busybox 1.38.0, python 3.14-alpine, open-webui app v0.11.4.

> **차트가 관리하는 이미지는 수동으로 고정하지 않는다.** monitoring 차트 업그레이드 시 grafana 13.1.1→13.2.3, alloy v1.19.2→v1.20.1, alloy-operator 1.12.1→1.13.0이 함께 이동한다. Longhorn 서브 이미지, traefik v3.7.13, cilium 이미지, valkey, redis, sealed-secrets-controller 0.40.0도 동일.
> 단, `infrastructure/base/monitoring/monitoring.stack.values.yaml`의 grafana-image-renderer 태그(v5.12.3)는 명시적으로 박혀 있으므로 차트 업그레이드 시 함께 검토한다.

### 노드 / 호스트

| 항목 | 현재 | 최신 |
|---|---|---|
| K3s | v1.36.4+k3s1 | **v1.37.1+k3s1** (v1.36.5+k3s1 선택지도 존재) |
| `infrastructure/base/k3s-upgrade/k3s-server-plan.yaml` | `version: v1.36.4+k3s1` | `v1.37.1+k3s1` |
| `ansible/roles/setup_k3s_server/defaults/main.yml` | `setup_k3s_server_version: v1.36.4+k3s1` | `v1.37.1+k3s1` |

K3s 번들 컴포넌트(coredns 1.14.6, metrics-server v0.9.0, local-path-provisioner v0.0.37, kubectl v1.36.4)는 노드 업그레이드에 따라 함께 이동하므로 별도 조치 없음.

---

## Approach

**웨이브 단위 스테이징.** 리스크가 낮고 되돌리기 쉬운 것부터, 데이터 손실 가능성이 있는 것일수록 나중에 배치한다.
각 웨이브는 `main`에 커밋 1개로 푸시하고, Flux가 reconcile할 때까지 기다린 뒤 검증한 다음 다음 웨이브로 넘어간다.

```
Wave 0  안전망 확인 (커밋 없음)
Wave 1  Flux 컨트롤러          ─ 저위험, 자기 자신을 업그레이드
Wave 2  무상태 인프라 차트      ─ traefik / monitoring / CRD-only
Wave 3  플랫폼 + 스토리지       ─ CNPG, SUC, Longhorn  ← 고위험 (모든 PVC 영향)
Wave 4  앱 이미지 4a → 4b      ─ 4b는 DB 마이그레이션 수반
Wave 5  K3s 노드 업그레이드     ─ 최고위험, 단일 노드 전면 재시작
```

핵심 원칙:
- **한 웨이브 = 한 커밋** → 문제 발생 시 해당 커밋만 `git revert` + `flux reconcile`로 되돌린다.
- **되돌릴 수 없는 것**(DB 마이그레이션, Longhorn engine/CRD)은 가장 뒤에, 가장 검증된 상태에서 수행한다.
- 모든 이미지 bump에서 **`@sha256:` digest를 반드시 갱신**한다 (repo 정책: `pinDigests`).

---

## Files to modify

**Wave 1**
- `clusters/production/flux-system/gotk-components.yaml`

**Wave 2**
- `infrastructure/base/traefik/traefik.helm-release.yaml`
- `infrastructure/base/traefik-external/traefik.helm-release.yaml`
- `infrastructure/base/prometheus-operator-crds/prometheus-operator-crds.helm-release.yaml`
- `infrastructure/base/monitoring/monitoring.k8s-monitoring.helm-release.yaml`
- `infrastructure/base/monitoring/monitoring.stack.helm-release.yaml`
- (필요 시) `infrastructure/base/monitoring/monitoring.stack.values.yaml`

**Wave 3**
- `infrastructure/base/cloudnative-pg/kustomization.yaml`
- `infrastructure/base/cloudnative-pg/cnpg-controller-manager.deployment.patch.yaml` (patch가 더 이상 매칭되지 않을 경우)
- `infrastructure/base/system-upgrade-controller/system-upgrade-controller.yaml`
- `infrastructure/base/system-upgrade-controller/crd.yaml` (upstream CRD와 diff 후 필요 시)
- `infrastructure/base/longhorn/install/longhorn.helm-release.yaml`
- (검증만) `infrastructure/base/longhorn/crds/longhorn.{system-backup,volume-backup,clean-up}.yaml`

**Wave 4a**
- `apps/base/cliproxyapi/cliproxyapi.deployment.yaml`
- `apps/base/vivident-tailscale-router/vivident-tailscale-router.statefulset.yaml`
- `apps/base/searxng/searxng.deployment.yaml`
- `apps/base/karakeep/karakeep.meilisearch.deployment.yaml`
- `infrastructure/base/cloudflared/cloudflared.deployment.yaml`
- `apps/base/openwebui/openwebui.values.yaml`

**Wave 4b**
- `apps/base/n8n/n8n.deployment.yaml`, `apps/base/n8n/n8n.task-runner.deployment.yaml`
- `apps/base/repositories/immich.yaml`, `apps/base/immich/app/values.yaml`
- `apps/base/home-assistant/home-assistant.deployment.yaml`
- `apps/base/guacamole/guacamole.database-init.yaml`

**Wave 5**
- `infrastructure/base/k3s-upgrade/k3s-server-plan.yaml`
- `ansible/roles/setup_k3s_server/defaults/main.yml`

**문서**
- `plans/update-all-resources.md` (본 문서)
- `readme.md` — 수동 스윕 런북 섹션 추가 (Wave 5 이후)

---

## Reuse

새 스크립트를 만들지 않고 이미 검증된 명령·자산을 재사용한다.

- **Flux 매니페스트 재생성**: `flux install --version=... --components=... --export` (로컬 flux CLI가 이미 2.9.6). `clusters/production/flux-system/gotk-components.yaml`은 upstream 원본 그대로(`DO NOT EDIT` 헤더)이므로 재생성 안전 — 로컬 커스터마이즈는 `clusters/production/flux-system/kustomization.yaml`의 별도 patch 파일들(`flux-system.namespace.patch.yaml`, `allow-*.network-policy.patch.yaml`, `controller-resources.deployment.patch.yaml`)이 담당한다.
- **digest 조회**: `docker buildx imagetools inspect <ref> --format '{{.Manifest.Digest}}'` (repo의 기존 `@sha256:` pin과 동일한 값 산출 확인됨). podman은 이 환경에서 사용 불가.
- **차트 최신 버전 조회**: `helm search repo <repo>/<chart> --versions` + `/tmp/hmrepo` 로컬 repo 캐시.
- **기존 백업 자산**: Longhorn RecurringJob 3종(`infrastructure/base/longhorn/crds/longhorn.{system-backup,volume-backup,clean-up}.yaml`)과 CNPG `ScheduledBackup` + `barmanObjectName` 7개 클러스터 — 새 백업 잡을 만들지 않고 이것들을 게이트로 사용한다.
- **기존 검증 절차**: AGENTS.md의 `kubectl kustomize ./apps/overlays/production`, `kubectl kustomize ./infrastructure/overlays/production`, 베이스별 `kubectl kustomize ./infrastructure/base/<name>`. `./clusters/production`은 kustomize 루트가 아니다.
- **기존 운영 도구**: `system-upgrade-controller` + `k3s-server` Plan이 이미 노드 업그레이드 경로다. Ansible(`ansible/`)은 부트스트랩/복구 전용이라 이번 인플레이스 업그레이드에는 실행하지 않는다(기본값만 최신으로 맞춰 향후 재구축 시 일관성 유지).
- **Kyverno 백업 보호**: `infrastructure/base/backup-cleanup/backup-cleanup.configmap.yaml`의 `backup-cleanup-control` 스위치 — 업그레이드 중 백업 삭제 정책을 잠시 끄고 싶을 때 재사용.

---

## Steps

### Wave 0 — 안전망 확인 (커밋 없음)

- [x] 롤백 기준점 기록: `git rev-parse HEAD` → `5e4d17d` (main, clean)
- [x] 전체 상태 확인: `flux --context homelab get kustomizations -A` → 52개 모두 `Ready`
- [x] 소스 확인: `flux --context homelab get source git flux-system` → `Ready` @ main@sha1:5e4d17d
- [x] Longhorn 백업 확인: `kubectl --context homelab -n longhorn-system get systembackups.longhorn.io -o wide` → `longhorn-system-backup`의 가장 최근 SystemBackup이 `Ready`
- [x] Longhorn 볼륨 백업 확인: `kubectl --context homelab -n longhorn-system get recurringjob` → `system-backup`/`backup`/`snapshot-cleanup` 존재
- [x] CNPG 백업 확인: `kubectl --context homelab get backup -A` + `kubectl --context homelab get cluster -A` → 7개 클러스터(cliproxyapi, davinci-resolve-project-server, guacamole, immich, issuary, n8n, openwebui) 최근 백업 `completed`, Cluster `Cluster in healthy state`
- [x] 웨이브 3 이전에 한 번 더: 백업을 강제 실행해 "업그레이드 직전 스냅샷" 확보
      ```bash
      kubectl --context homelab -n longhorn-system create job --from=cronjob/... # 또는
      kubectl --context homelab -n <ns> create job --from=cronjob/<scheduled-backup-name> backup-now-<app>
      ```
- [x] 게이트 통과 못 하면 **중단**하고 백업 문제부터 해결

### Wave 1 — Flux 컨트롤러 v2.9.5 → v2.9.6

- [ ] 재생성:
      ```bash
      flux install --version=v2.9.6 \
        --components=source-controller,kustomize-controller,helm-controller,notification-controller,image-reflector-controller,image-automation-controller \
        --export > clusters/production/flux-system/gotk-components.yaml
      ```
- [x] diff 검토: `git diff clusters/production/flux-system/gotk-components.yaml`
      → 기대: 헤더 버전, image tag, RBAC `app.kubernetes.io/version` 라벨만 변경. 그 외 대량 변경이면 원인 확인 후 진행.
- [x] 로컬 검증: `kubectl kustomize ./clusters/production/flux-system` (flux-system 서브디렉터리는 kustomize 루트다)
- [x] 커밋 & 푸시: `chore(flux): upgrade controllers to v2.9.6`
- [x] 재조정 & 검증:
      ```bash
      flux --context homelab reconcile source git flux-system
      flux --context homelab reconcile kustomization flux-system
      flux --context homelab -n flux-system get pods
      flux --context homelab get kustomizations -A
      ```
      → source/kustomize v1.9.6, helm v1.6.5, 나머지 동일. 52개 Kustomization 다시 `Ready`.
- [x] (선택) `flux --context homelab check` 로 전체 사전점검

### Wave 2 — 무상태 인프라 차트

- [x] `infrastructure/base/traefik/traefik.helm-release.yaml` → `41.6.1`
- [x] `infrastructure/base/traefik-external/traefik.helm-release.yaml` → `41.6.1`
- [x] `infrastructure/base/prometheus-operator-crds/prometheus-operator-crds.helm-release.yaml` → `32.0.1`
- [x] `infrastructure/base/monitoring/monitoring.k8s-monitoring.helm-release.yaml` → `4.5.3`
- [x] `infrastructure/base/monitoring/monitoring.stack.helm-release.yaml` → `0.95.2`
- [x] **값 키 호환성 확인** (0.93.0 → 0.95.2는 마이너 2단계): 새 차트를 로컬에서 렌더해 기존 values가 무시/오류 없이 소비되는지 확인
      ```bash
      helm template monitoring-stack <repo>/victoria-metrics-k8s-stack --version 0.95.2 \
        -f infrastructure/base/monitoring/monitoring.stack.values.yaml --kube-version 1.37.1 | head -50
      ```
      경고/에러가 나오는 키는 `infrastructure/base/monitoring/monitoring.stack.values.yaml`에서 새 이름으로 교체. 특히 `grafana-image-renderer` 태그(v5.12.3) 확인.
- [x] 차트가 끌고 가는 이미지(grafana 13.2.3, alloy v1.20.1, alloy-operator 1.13.0)가 새 차트 기본값과 맞는지 렌더 결과로 확인 — **수동 pin은 하지 않는다**
- [x] 검증: `kubectl kustomize ./infrastructure/overlays/production` 및 `kubectl kustomize ./infrastructure/base/monitoring`, `.../traefik`, `.../traefik-external`, `.../prometheus-operator-crds`
- [x] 커밋 & 푸시: `chore(infra): bump traefik, monitoring, prometheus-operator-crds charts`
- [x] 재조정 & 검증:
      ```bash
      flux --context homelab reconcile kustomization infrastructure --with-source
      flux --context homelab get helmreleases -A
      kubectl --context homelab -n traefik-system get pods
      kubectl --context homelab -n traefik-external-system get pods
      kubectl --context homelab -n monitoring-system get pods
      ```
      → 외부/내부 진입점 HTTP 응답 확인, Grafana 접속 확인, VictoriaMetrics 타깃 정상

### Wave 3 — 플랫폼 컨트롤러 + 스토리지 (고위험)

**선행: Wave 0의 백업 게이트를 다시 통과시킬 것.**

- [x] **3a. CNPG + Barman plugin**
      - `infrastructure/base/cloudnative-pg/kustomization.yaml`의 remote URL: `v1.30.0` → `v1.30.1`, `plugin-barman-cloud` `v0.15.0` → `v0.15.1`
      - `cnpg-controller-manager.deployment.patch.yaml`의 selector/target이 여전히 매칭되는지 확인 (컨트롤러 Deployment 이름/라벨 변경 여부)
      - 검증: `kubectl kustomize ./infrastructure/base/cloudnative-pg` (네트워크 필요)
      - 배포 후: `kubectl --context homelab -n cnpg-system get deploy,pods`, `kubectl --context homelab get cluster -A` → 7개 모두 healthy, ScheduledBackup 계속 동작
- [x] **3b. system-upgrade-controller v0.20.1 → v0.20.2**
      - upstream 릴리스 매니페스트는 **이미지 태그 한 줄만** 다르다(검증 완료: 동일 6851 bytes, `<2` diff는 `rancher/system-upgrade-controller:v0.20.1` → `:v0.20.2`)
      - `infrastructure/base/system-upgrade-controller/system-upgrade-controller.yaml:269`의 태그만 `v0.20.2`로 변경 (로컬 커스터마이즈된 `default-controller-env` ConfigMap은 그대로 유지)
      - `crd.yaml`은 **upstream 릴리스 매니페스트에 포함되지 않는다**(릴리스 yaml 내 CRD 0개, 로컬 crd.yaml에 CRD 1개). 별도 출처에서 벤더링된 파일이므로 `https://github.com/rancher/system-upgrade-controller` v0.20.2의 CRD와 diff하여 변경이 있을 때만 반영
      - 검증: `kubectl kustomize ./infrastructure/base/system-upgrade-controller`
      - 배포 후: `kubectl --context homelab -n system-upgrade get deploy,pods` 정상, 기존 Plan/Job에 영향 없는지 확인
- [x] **3c. Longhorn 1.12.1 → 1.13.0**
      - `infrastructure/base/longhorn/install/longhorn.helm-release.yaml` 의 chart version만 `1.13.0`으로 변경
      - **CRD는 별도 작업 불필요**: Longhorn 1.13.0 차트는 CRD 28개를 `templates/crds.yaml`에 포함하고 있어(`controller-gen v0.19.0`) Helm upgrade 시 함께 적용된다. `infrastructure/base/longhorn/crds/*.yaml`은 CRD가 아니라 **Longhorn RecurringJob 커스텀 리소스**(`longhorn.io/v1beta2`)이므로 손대지 않는다
      - `preUpgradeChecker.jobEnabled: true` / `upgradeVersionCheck: true` 상태 → 업그레이드 전 pre-upgrade Job이 실행된다. GitOps 도구 사용 시 비활성화를 권장하는 upstream 안내가 있으므로, Job이 Flux와 충돌하면 `longhorn.values.yaml`에서 `preUpgradeChecker.jobEnabled: false`로 전환하고 그 사유를 커밋 메시지에 남긴다
      - 배포 전 백업 재확인 (Wave 0 게이트)
      - 검증:
        ```bash
        flux --context homelab reconcile kustomization longhorn-install --with-source
        kubectl --context homelab -n longhorn-system get pods
        kubectl --context homelab -n longhorn-system get settings.longhorn.io
        kubectl --context homelab api-resources --api-group=longhorn.io
        kubectl --context homelab -n longhorn-system get recurringjob
        kubectl --context homelab -n longhorn-system get systembackup,backupvolume
        kubectl --context homelab get pvc -A
        ```
      - 확인 항목: `longhorn.io/v1beta2`의 `RecurringJob`/`SystemBackup`/`BackupVolume`이 여전히 served, 3개 RecurringJob 그대로 존재, 모든 PVC `Bound`, Longhorn UI에서 볼륨 `degraded` 아님, engine 이미지가 1.13.0으로 순차 교체되는지
      - 커밋 (3a/3b/3c는 **각각 별도 커밋**으로 분리해 되돌리기 쉽게): `chore(cnpg): bump operator to v1.30.1`, `chore(suc): bump image to v0.20.2`, `chore(longhorn): upgrade to 1.13.0`

### Wave 4 — 애플리케이션 이미지

> 모든 이미지 변경에서 `@sha256:` digest를 갱신한다:
> `docker buildx imagetools inspect <ref> --format '{{.Manifest.Digest}}'`

**4a — 무상태 (저위험)**
- [x] `apps/base/cliproxyapi/cliproxyapi.deployment.yaml`: `eceasy/cli-proxy-api` v8.0.10 → v8.0.20 (+digest)
- [x] `apps/base/vivident-tailscale-router/vivident-tailscale-router.statefulset.yaml`: tailscale v1.102.4 → v1.104.1 (**32행, 66행 두 곳 모두** + digest)
- [x] `apps/base/searxng/searxng.deployment.yaml`: 2026.9.21-f372096fb → 2026.10.7-6671d89be (+digest)
- [x] `apps/base/karakeep/karakeep.meilisearch.deployment.yaml`: meilisearch v1.54.0 → v1.54.3 (+digest)
- [x] `infrastructure/base/cloudflared/cloudflared.deployment.yaml`: 2026.9.1 → 2026.10.0 (+digest)
- [x] `apps/base/openwebui/openwebui.values.yaml`: tika 4.0.0-full → 4.1.0-full (+digest)
- [x] 검증: `kubectl kustomize ./apps/overlays/production` + `kubectl kustomize ./apps/base/<name>` 각각
- [x] 커밋 & 푸시: `chore(apps): bump stateless images`
- [x] 사후 확인: 각 네임스페이스 파드 `Running`, tailscale 라우터 연결 유지, Cloudflare 터널 유지, karakeep 검색 동작

**4b — 상태 저장 / DB 마이그레이션 동반 (고위험)**
- [ ] **선행: CNPG 백업 게이트 재확인**
- [x] n8n + task runner: `apps/base/n8n/n8n.deployment.yaml`, `apps/base/n8n/n8n.task-runner.deployment.yaml` → 2.40.5 → **2.43.1** (+digest, 두 파일의 버전 일치 유지)
- [x] Immich: `apps/base/repositories/immich.yaml`의 OCIRepository `spec.ref.tag` 0.13.2 → **0.13.4**, `apps/base/immich/app/values.yaml`의 immich-server / immich-machine-learning 태그 v3.2.2 → **v3.3.0** (+새 digest). Immich는 차트와 앱 버전이 짝을 이룬다 — 순서: 차트 먼저 → 앱 이미지
      - 배포 전 Immich 전용 백업 확인: `kubectl --context homelab -n immich-system get backup,cluster`(immich CNPG) + Longhorn 볼륨 백업
- [x] Home Assistant: `apps/base/home-assistant/home-assistant.deployment.yaml` 2026.9.3 → **2026.10.0** (월 릴리스, 되돌리기 어려운 자동 마이그레이션 존재) — 배포 전 HA 설정 디렉터리(Longhorn PVC) 백업 확인
- [x] zigbee2mqtt 2.14.1 → 2.14.2, mosquitto 2.0.22 → **2.1.2** (2.0 → 2.1은 config/동작 의미 변화 가능 → `apps/base/home-assistant/`의 mosquitto 설정 확인 후 진행)
- [x] guacamole DB init 이미지: `apps/base/guacamole/guacamole.database-init.yaml` postgres 17.6-bookworm → 17.11-bookworm
      - **주의**: 이 파일은 초기화용이며, 실제 DB는 CNPG operand 이미지(17.11-standard-bookworm)가 담당한다. 이미 운영 중인 클러스터에 영향이 없는지(init job이 재실행되지 않는지) 확인
- [x] 검증: `kubectl kustomize ./apps/overlays/production`, 각 앱 스모크 테스트 (로그인, 핵심 기능 1개)
- [x] 커밋 & 푸시: `chore(apps): bump n8n, immich, home-assistant stack`
- [x] 사후 확인:
      ```bash
      kubectl --context homelab get pods -A | grep -vE "Running|Completed"
      kubectl --context homelab get cluster -A
      flux --context homelab get kustomizations -A
      ```

### Wave 5 — K3s v1.36.4+k3s1 → v1.37.1+k3s1

- [x] `infrastructure/base/k3s-upgrade/k3s-server-plan.yaml`: `version: v1.36.4+k3s1` → `version: v1.37.1+k3s1`
- [x] `ansible/roles/setup_k3s_server/defaults/main.yml`: `setup_k3s_server_version: v1.36.4+k3s1` → `v1.37.1+k3s1` (부트스트랩 재현성 유지용)
- [x] **최종 백업 게이트**: Longhorn system backup + 7개 CNPG 백업 최신 강제 확인 (되돌릴 수 없는 단계)
- [x] 컨테이너 이미지 정책 결정 (아래 두 옵션 중 택1, 커밋 메시지에 사유 기록)
      - **A. 현행 유지**: `upgrade.image: rancher/k3s-upgrade` (untagged) — Renovate `customManagers`의 K3s 정규식(`version: (?<currentValue>v\d+\.\d+\.\d+\+k3s\d+)`)이 그대로 동작하고 변경 최소
      - **B. 재현성 강화 (선택)**: `upgrade.image: rancher/k3s-upgrade:v1.37.1-k3s1`로 고정 — 대신 기존 Renovate 정규식이 이 줄을 갱신하지 못하므로 이미지 태그는 수동 관리 대상이 된다
      - 권장: **A 유지**. `version:` 필드가 실제 업그레이드 대상을 결정하므로 실익이 크고, 결정 4(Renovate 불변)와 충돌하지 않는다
- [x] 로컬 검증: `kubectl kustomize ./infrastructure/base/k3s-upgrade`
- [x] 커밋 & 푸시: `chore(k3s): upgrade plan to v1.37.1+k3s1`
- [ ] 업그레이드 진행 관찰:
      ```bash
      kubectl --context homelab -n system-upgrade get plan,job
      kubectl --context homelab -n system-upgrade get jobs -w
      kubectl --context homelab get nodes
      kubectl --context homelab -n system-upgrade logs -l upgrade.cattle.io/plan=k3s-server
      ```
- [ ] 노드 업그레이드 완료 후 확인:
      ```bash
      kubectl --context homelab get node -o wide          # v1.37.1+k3s1, Ready, uncordoned
      kubectl --context homelab get kustomizations -A     # 전부 Ready
      kubectl --context homelab get pods -A | grep -v Running
      kubectl --context homelab get cluster -A            # CNPG 7개 healthy
      kubectl --context homelab -n longhorn-system get pods
      ```
- [ ] 긴급 시 되돌리기: Plan `version`을 이전 값으로 되돌려 재실행 (`k3s-upgrade`는 다운그레이드도 동일 경로로 수행 가능)

### Wave 6 — 운영 문서화 (수동 스윕 런북)

- [ ] `readme.md`에 "주기적 버전 스윕" 섹션 추가, 다음을 담는다:
      - Renovate는 현재 GitHub에 PR/Dashboard가 없어 **동작하지 않는다**는 사실과 그 확인 방법(`gh issue list`, `gh pr list`, `.github/workflows` 부재)
      - 스윕 체크리스트: Flux는 `flux install --export` 비교, 차트는 `helm search repo --versions`, 이미지는 `docker buildx imagetools inspect`, 노드는 K3s GitHub releases
      - Renovate를 되살리려면 별도 결정이 필요하다는 메모(이번 범위 밖)
- [ ] `renovate.json5`는 **변경하지 않는다**
- [ ] 커밋 & 푸시: `docs: add manual version sweep runbook`

---

## Verification

웨이브마다 아래를 순서대로 확인한다.

1. **렌더 검증** (푸시 전)
   - `kubectl kustomize ./apps/overlays/production`
   - `kubectl kustomize ./infrastructure/overlays/production`
   - 변경한 베이스: `kubectl kustomize ./infrastructure/base/<name>` / `./apps/base/<name>`
   - 예외: `./clusters/production`은 kustomize 루트가 아니다 (AGENTS.md). `./clusters/production/flux-system`은 루트다.
   - `infrastructure/base/cloudnative-pg`는 원격 URL을 당기므로 네트워크가 필요하다.
2. **Flux 검증** (푸시 후)
   - `flux --context homelab reconcile source git flux-system`
   - `flux --context homelab reconcile kustomization <name> --with-source`
   - `flux --context homelab get kustomizations -A` → 전부 `Ready`, `Applied revision`이 새 커밋 SHA
   - `flux --context homelab get helmreleases -A` → 새 차트 버전, `Ready`
   - `flux --context homelab events --all-namespaces` 로 경고 확인
3. **워크로드 검증**
   - `kubectl --context homelab get pods -A | grep -vE "Running|Completed"`
   - `kubectl --context homelab get cluster -A` (CNPG 7개 healthy)
   - `kubectl --context homelab -n longhorn-system get systembackup,recurringjob,volume`
   - `kubectl --context homelab get pvc -A` → 전부 `Bound`
4. **기능 검증** (수동 스모크)
   - Traefik 내부/외부 진입점 HTTP 200, TLS 인증서 유효
   - Grafana 접속 및 대시보드 데이터 수신 (monitoring 웨이브)
   - Immich 업로드/조회, n8n 워크플로 1개 수동 실행, Home Assistant UI + zigbee 디바이스 상태, karakeep 검색, Cloudflare 터널 경유 서비스 1개
   - 백업 파이프라인 재가동 확인: 업그레이드 후 첫 RecurringJob/CNPG ScheduledBackup이 `Ready`로 완료되는지

---

## Rollback

| 웨이브 | 되돌리는 방법 | 완전 복구 가능? |
|---|---|---|
| 1 Flux | `git revert <sha>` + `flux reconcile source git flux-system` — Flux가 자기 자신을 이전 버전으로 재배포 | 가능 (CRD/RBAC 하위 호환) |
| 2 차트 | `git revert <sha>` — Helm은 직전 리비전으로 롤백 | 가능 |
| 3a CNPG | `git revert <sha>` — 컨트롤러만 되돌아감, CRD는 남을 수 있음 | 대체로 가능 |
| 3b SUC | `git revert <sha>` | 가능 |
| 3c Longhorn | `git revert <sha>` — 차트는 되돌아가지만 **CRD/engine 이미지 업그레이드는 되돌아가지 않는다** | 부분적. 볼륨 데이터는 유지되지만 downgrade는 비권장 |
| 4a 무상태 | `git revert <sha>` | 가능 |
| 4b 상태 저장 | `git revert <sha>` — **DB 마이그레이션은 되돌아가지 않는다** | 부분적. 필요 시 CNPG Barman S3 + Longhorn 백업에서 복원 |
| 5 K3s | Plan `version`을 이전 값으로 되돌려 재실행 | 가능 (k3s-upgrade가 다운그레이드 지원) |

**전체 롤백**: `git revert` 후 `flux --context homelab reconcile source git flux-system` + 각 Kustomization reconcile. 단, Wave 3c/4b 이후는 백업 복원 경로(`readme.md`의 복구 절차)를 따라야 한다.

---

## Risks

| 리스크 | 영향 | 완화 |
|---|---|---|
| **단일 노드 드레인/재시작** (Wave 5) | API 일시 단절, 전체 워크로드 재시작, Longhorn 볼륨 detach/reattach | Wave 3·4 이후 가장 안정된 시점에 수행, 백업 직후 실행, `concurrency: 1` 유지. `cordon: true`는 단일 노드에서 실익이 제한적이므로 업그레이드 중 스케줄링 차단이 문제가 되면 제거 검토 |
| **Longhorn 1.12 → 1.13** | 모든 PVC가 이 스토리지 위에 있음. 재시작 중 볼륨 I/O 중단, engine 이미지 교체 | 백업 게이트 통과 후 진행, `preUpgradeChecker` 활성 상태 활용, 배포 후 `volume`/`backupvolume` 상태 확인. 문제 시 데이터 유지 + 컨트롤러 리비전만 롤백 |
| **n8n / Immich / Home Assistant 마이그레이션** | 앱 자체 DB 스키마 마이그레이션은 되돌릴 수 없음 | CNPG Barman S3 + Longhorn 백업 최신 확인 후 진행, 한 번에 한 앱씩, 4b는 별도 커밋 |
| **mosquitto 2.0.22 → 2.1.2** | 2.x 마이너 업그레이드에서 설정/동작 의미 변경 가능 (zigbee2mqtt 연동 영향) | 배포 전 mosquitto 설정 파일 검토, 배포 직후 zigbee2mqtt 연결 로그 확인 |
| **monitoring 0.93 → 0.95 값 키 변경** | 차트 values 개명으로 일부 설정(스크레이핑, 이미지 렌더러)이 조용히 무시될 수 있음 | `helm template`으로 렌더 검증, 경고 확인, Grafana/VM 타깃 스크레이핑 정상 여부 수동 확인 |
| **`@sha256:` digest 미갱신** | 태그와 digest 불일치 → 배포 실패 또는 의도치 않은 이미지 | 모든 이미지 bump에서 `docker buildx imagetools inspect`로 digest 재생성, 푸시 전 diff 검토 |
| **Flux gotk-components 재생성 오류** | Flux 컨트롤러가 잘못된 매니페스트로 배포되어 GitOps 전체 정지 | 재생성 후 반드시 diff 검토(버전/RBAC 라벨만 변경되는지), `kubectl kustomize ./clusters/production/flux-system` 선검증, 문제 시 `git revert` 1회로 복구 |
| **SUC `crd.yaml` 출처 불명** | 업스트림 릴리스 매니페스트에 CRD가 없어 로컬 CRD가 어느 리비전인지 불확실 | v0.20.2 업스트림 CRD와 diff, 차이 없으면 미변경, 차이가 있으면 그 차이만 반영 |
| **K3s 번들 컴포넌트 자동 이동** | coredns/metrics-server/local-path-provisioner/kubectl이 노드와 함께 버전 이동 | 의도된 동작. 업그레이드 후 파드 정상 여부만 확인 |
| **CNPG operand 이미지(17.11/18.6)와 컨트롤러 v1.30.1 호환** | 마이너 업그레이드라 대체로 안전하지만 operator↔operand 이미지 매트릭스 확인 필요 | 배포 후 7개 Cluster healthy 및 ScheduledBackup 성공 확인 |

---

## Open Questions

1. **K3s 버전 선택**: `v1.37.1+k3s1`(최신) vs `v1.36.5+k3s1`(현재 마이너의 패치). 최신을 권장하지만 안정성 우선이면 패치만 올리는 선택지도 있다.
2. **`upgrade.image` 고정 여부** (Wave 5 옵션 A/B): 현행 유지(권장) vs 태그 고정으로 재현성 강화.
3. **Longhorn `preUpgradeChecker.jobEnabled`**: 현행 `true` 유지 vs GitOps 친화적으로 `false` 전환. `true` 유지 시 pre-upgrade Job이 Flux와 충돌하지 않는지 실제 실행에서 확인 필요.
4. **Wave 순서 재확인**: Wave 3(Longhorn)과 Wave 4b(Immich: `apps/base/immich/app`에도 tika/이미지가 있어 Immich가 Longhorn과 monitoring 양쪽에 걸침)의 순서를 지금 안대로 갈지, 아니면 Longhorn을 Wave 4b 뒤로 미룰지.
