# Plan: Nextcloud 클러스터 배포

## Context

`cloud.winetree94.com`으로 서비스할 Nextcloud를 `production` 클러스터의
`nextcloud-system` 네임스페이스에 새로 설치한다(기존 인스턴스에서의 마이그레이션 없음).
파일 본문은 **Garage S3를 primary object storage**로 두고, PVC에는 앱 코드·설정
(`config.php`, `instanceid`, apps, themes, log)만 남긴다.

- 차트: `ghcr.io/nextcloud/helm/nextcloud:9.4.0` (appVersion 35.0.1, **Apache flavor**)
- 진입점: `apps/overlays/production/nextcloud.yaml` (Kustomization 3개)

## 구성

| 계층 | 위치 | 내용 |
|---|---|---|
| 앱 | `apps/base/nextcloud/app` | HelmRelease(`nextcloud`), `nextcloud-values` ConfigMap, SealedSecret `nextcloud-admin-secret`, IngressRoute `cloud.winetree94.com`, CiliumNetworkPolicy |
| 설정 저장 | `apps/base/nextcloud/app` | PVC `nextcloud-nextcloud` (16Gi **RWX** `longhorn-rwx`) |
| 데이터베이스 | `apps/base/nextcloud/database` | CNPG `nextcloud-database-cluster` (PG18 1 instance) + Barman `ObjectStore`(30d, 4시간 `ScheduledBackup`) |
| 캐시/락 | `apps/base/nextcloud/redis` | opstree `Redis` CR `nextcloud-redis` (v1beta2, 1Gi `longhorn-strict-local`) |
| 오브젝트 스토리지 | 외부 (Garage S3) | 버킷 `tinyrack-homelab-nextcloud-storage` |
| 인증 | 외부 (Issuary OIDC) | 클라이언트 `nextcloud` |
| 정책 | `apps/base/nextcloud/*` | `app-nextcloud`, `route-nextcloud`, `database-nextcloud` CiliumNetworkPolicy |

Flux Kustomization 순서는 `nextcloud-database` → `nextcloud-redis` → `nextcloud-deployment`다.

## 영속성

```yaml
persistence:
  enabled: true
  storageClass: longhorn-rwx
  accessMode: ReadWriteMany
  size: 16Gi
  labels:                                     # annotation 아님
    recurring-job.longhorn.io/source: enabled
    recurring-job-group.longhorn.io/longhorn-backup: enabled
  nextcloudData:
    enabled: false
```

- Longhorn 1.13은 PVC **라벨**을 볼륨으로 동기화하며, `recurring-job.longhorn.io/source: enabled`가
  있어야만 동기화한다. 이 라벨이 반복 작업 `longhorn-volume-backup`
  (cron `30 3,15 * * *`, retain 14) 그룹에 연결돼 `config.php`/`instanceid`가 매일 백업된다.
  annotation으로 넣으면 백업이 걸리지 않는다.
- 차트가 만든 PVC에는 `helm.sh/resource-policy: keep`이 내장돼 uninstall 후에도 남는다.
- S3가 primary storage이므로 별도 `nextcloudData` PVC는 쓰지 않는다. on-PVC `data/`는
  `nextcloud.log`·업데이터 스테이징 용도다.
- `nextcloud.extraVolumes`/`extraVolumeMounts`로 `/tmp`를 `emptyDir(sizeLimit: 20Gi)`에 고정한다.
  기본값 `/tmp`는 노드 루트 파일시스템이라 대용량 zip/업로드가 노드 디스크를 채울 수 있다.

## 백엔드 연결 값

- DB: `externalDatabase` + `nextcloud-database-user-secret` (username/password),
  `internalDatabase.enabled: false`, `mariadb.enabled: false`, `postgresql.enabled: false`.
- Redis: `externalRedis` + `nextcloud-redis-secret`, `redis.enabled: false`.
- S3: `nextcloud.objectStore.s3` (host `storage.intranet.winetree94.com`, port `443`, region `home`,
  `usePathStyle: true`, `autoCreate: false`) + 기존 `tinyrack-homelab-s3-secret`
  (reflector가 `nextcloud-system`에도 반사).
- OIDC 리다이렉트는 `https://cloud.winetree94.com/apps/user_oidc/code`이며, 앱 파드는
  `auth.winetree94.com`을 내부 `traefik-external` LB로 해석해 접근한다.
- 프록시: `nextcloud.configs.proxy.config.php`에 `trusted_proxies`(pod/service CIDR),
  `overwritehost`/`overwriteprotocol`/`overwrite.cli.url`을 지정한다.
- 공개 진입은 `ingress.enabled: false` + `IngressRoute`(className `traefik-external`,
  entryPoints `websecure`/`cloudflare`, tls `letsencrypt-cert`)다.
- 메트릭: `nextcloud.openmetrics.allowedClients`, `metrics.enabled`, `prometheus.serviceMonitor.enabled`.
  Alloy가 앱 `:80`(openmetrics)와 exporter `:9205`를 스크레이프한다.

## 비밀

`bw` 항목 `Kubernetes Secrets (Homelab)` (id `192c82cd-8e3e-4cb9-be46-b39001022d61`)
hidden 필드 기준. 저장소에는 SealedSecret만 커밋한다.

- `cloud.winetree94.com` 항목의 password → `nextcloud-admin-secret`(`password`), 관리자 username `nextcloud`
- `nextcloud-admin-token` → `nextcloud-admin-secret`(`nextcloud-token`, serverinfo 토큰)
- `nextcloud-database-password` → `nextcloud-database-user-secret`
- `nextcloud-redis-password` → `nextcloud-redis-secret`
- `issuary-nextcloud-client-secret` → `issuary-secrets`(`ISSUARY_NEXTCLOUD_CLIENT_SECRET`)

Garage 버킷 `tinyrack-homelab-nextcloud-storage`는 기존 키 `tinyrack-homelab`에 RW로 부여했다.

## 배포 후 수동 단계 (occ)

```bash
POD=$(kubectl --context homelab -n nextcloud-system get pod \
  -l app.kubernetes.io/name=nextcloud,app.kubernetes.io/component=app -o name | head -1)

# 1) user_oidc 앱 설치/활성화 후 provider 등록
kubectl --context homelab -n nextcloud-system exec -it "$POD" -- occ app:install user_oidc
kubectl --context homelab -n nextcloud-system exec -it "$POD" -- occ user_oidc:provider issuary \
  --clientid=nextcloud --clientsecret=<issuary-nextcloud-client-secret> \
  --discoveryuri=https://auth.winetree94.com/.well-known/openid-configuration \
  --scope="openid profile email"

# 2) OIDC 전용 전환 (Nextcloud 35 + user_oidc 8.11은 /login만 리다이렉트한다)
kubectl --context homelab -n nextcloud-system exec -it "$POD" -- \
  occ config:app:set user_oidc allow_multiple_user_backends --value=0

# 3) 메트릭 exporter 토큰 등록
kubectl --context homelab -n nextcloud-system exec -it "$POD" -- \
  occ config:app:set serverinfo token --value=<nextcloud-admin-token>

# 4) 초기 파일 스캔
kubectl --context homelab -n nextcloud-system exec -it "$POD" -- occ files:scan --all

# 5) 로컬 로그인 차단: 로컬 admin 계정 비활성화
#    allow_multiple_user_backends=0은 /login만 user_oidc로 리다이렉트할 뿐,
#    /login?direct=1로 들어오는 비밀번호 로그인은 그대로 통과한다(실측 확인).
#    남아 있는 로컬 계정을 비활성화해야 web·DAV·OCS 어디서도 비밀번호 인증이 막힌다.
kubectl --context homelab -n nextcloud-system exec -it "$POD" -- occ user:disable nextcloud
```

`occ list user_oidc`로 실제 플래그 이름을 먼저 확인한다.
`occ`는 파드 안에서 `su -s /bin/sh www-data -c "php occ ..."` 형태로 실행한다(아래 참고).

브레이크글래스는 로컬 계정을 되살리는 절차다. IdP 장애 시에도 쿠버네티스에서 직접 실행할 수 있다.

```bash
kubectl --context homelab -n nextcloud-system exec -it "$POD" -- \
  su -s /bin/sh www-data -c "php occ user:enable nextcloud"
# 비밀번호를 모르면 함께 재설정한다.
kubectl --context homelab -n nextcloud-system exec -it "$POD" -- \
  su -s /bin/sh www-data -c "php occ user:resetpassword nextcloud"
```

`configs/sso-only.config.php`(`hide_login_form`, `lost_password_link`)는 UI에서 비밀번호 폼과
비밀번호 재설정 링크를 감추는 보조 장치다. `?direct=1`에서는 폼이 계속 렌더되므로 위 브레이크글래스가
그대로 동작한다.

## 검증

- 레이어 빌드: `kubectl kustomize ./apps/base/nextcloud/{database,redis,app}`,
  `./apps/overlays/production`, `./infrastructure/base/monitoring`, `./apps/base/issuary`.
- `flux get ks -A`, `kubectl --context homelab -n nextcloud-system get hr,pvc,pod`.
- PVC 라벨 2개 확인 → `longhorn-system` 볼륨 라벨 반영 → 다음 03:30 이후
  `backups.longhorn.io` 생성 여부.
- `occ status`, `occ config:system:get objectstore`, 파일 업로드 후 Garage 버킷에 객체 생성 +
  PVC 사용량(`df -h /var/www/html/data`)이 늘지 않는지 확인.
- `?direct=1`에서 비밀번호 폼이 렌더되는지(브레이크글래스 유지), 같은 폼으로 로컬 계정
  자격증명을 넣었을 때 인증이 거부되는지(`303 → /login?direct=1&user=...`), 정상 OIDC 리다이렉트,
  Alloy 타깃 `up`, Cloudflare 경유 외부 접속.
- 노드 재부팅 후 파드·RWX 재마운트, Longhorn 백업에서 config/app 복구 리허설.

## 가정과 한계

- 단일 노드 k3s, pod CIDR `10.61.0.0/16`, service CIDR `10.62.0.0/16`, Longhorn 1.13.
- SMTP·Collabora·imaginary 미사용, `replicaCount 1`, HPA 미사용.
- Garage 자체와 그 데이터 백업은 이 저장소 범위 밖이다. Longhorn 백업은 config/app만 보호하고,
  사용자 파일은 S3 백업 정책에 의존한다.
- RWX는 볼륨당 share-manager 파드 1개이며 노드 장애 시 90초 NFS grace 동안 I/O가 막힌다.
  `rwx-volume-fast-failover`는 실험적이라 off로 둔다.

## 배포 중 발생한 문제와 수정

- k3s kubelet `max-pods`가 110이라 노드가 포화되어 CNPG가 Pending이 됐다.
  `ansible/roles/setup_k3s_server`에 `kubelet-arg: max-pods=200`을 추가해 200으로 올렸다.
- Longhorn `storageOverProvisioningPercentage`가 100이라 nominal 412Gi가 상한(≈425Gi)을 넘겨
  PVC 스케줄링이 실패했다. `infrastructure/base/longhorn/install/longhorn.values.yaml`에서 150으로
  올렸다.
- 최초 기동이 RWX 볼륨으로 코드를 복사하느라 ~7분 걸려 차트 기본 liveness에 죽었다.
  `startupProbe`를 켜서 최초 성공 전까지 liveness를 막는다.
- 네임스페이스 격리로 Redis 파드에 default-deny가 적용돼 앱→Redis 통신이 막혔다.
  `app-nextcloud` CNP에 Redis ingress(6379, app·cronjob)를 추가했다.
- CronJob 파드가 root로 떠서 `config/config.php`(uid 33) 소유자 검사에 걸렸다.
  `cronjob.cronjob.securityContext`로 uid/gid 33 + `runAsNonRoot`를 지정했다.
- traefik-external → 앱 egress가 Service 포트(8080)만 허용했는데, Cilium은 **DNAT된 백엔드
  포트(80)** 기준으로 판정해 공개 요청이 30초 후 504가 됐다. `route-nextcloud`
  (traefik-external-system) egress에 80을 추가했다.
- metrics exporter(serverinfo API)가 앱 파드 ingress에 없어 스크레이프가 타임아웃했다.
  `app-nextcloud` ingress에 `component: metrics`를 추가하고 `serverinfo token`을 설정했으며,
  잘못된 토큰으로 누적된 bruteforce 지연은 `occ security:bruteforce:reset`으로 풀었다.
- OIDC discovery가 `auth.winetree94.com`(내부 LB 사설 IP)에서 실패했다. Nextcloud HTTP 클라이언트가
  사설 주소를 거부하므로 `local-server.config.php`에 `allow_local_remote_servers => true`를 추가했다.
- 첫 설치가 중단되며 `Templates/Photo book.odt.part`(fileid 40)가 오브젝트 없는 상태로 남아
  미리보기 오류를 냈다. `occ files:delete 40 --skip-trash`로 정리했다.

`occ`는 파드 안에서 `su -s /bin/sh www-data -c "php occ ..."`로 실행한다(루트로 실행하면
config.php 소유자 검사에 걸린다).

## 검증 결과 (2026-10-10)

- HelmRelease `nextcloud` Ready, Deployment `nextcloud` 1/1, CNPG·Redis·metrics 모두 Running.
- `kubectl kustomize ./apps/base/nextcloud/{database,redis,app}`, `./apps/overlays/production`,
  `./infrastructure/base/monitoring` 빌드 통과.
- 공개 접속: `https://cloud.winetree94.com/status.php` 200, `/login` 302 → Issuary authorize 303.
- SSO 전용: `/login?direct=1`은 200으로 폼을 렌더하지만, 유효한 로컬 비밀번호로 POST하면
  `303 → /login?direct=1&user=nextcloud`로 되돌아온다(로컬 `nextcloud` 계정 비활성화). OIDC
  계정은 admin 그룹을 유지한다.
- 오브젝트 스토리지: `occ files:object:list` 55건, 미리보기 객체 생성 확인.
- 메트릭: VictoriaMetrics에서 `up{job=~"nextcloud.*"}` = 1 (앱 `:80` openmetrics, exporter `:9205`).
- CronJob: uid 33 적용 후 5분 주기 Job이 Complete.
- 아직 미검증: 다음 03:30/15:30 KST `backups.longhorn.io` 생성, 노드 재부팅 후 RWX 재마운트,
  Longhorn 백업에서의 복구 리허설.
