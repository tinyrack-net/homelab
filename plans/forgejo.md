# Plan: Forgejo 배포 (git.winetree94.com) — 실행 완료 (2026-11-03)

## Context

홈랩 `homelab` 클러스터에 Forgejo를 배포해 개인 Git 호스팅을 제공한다.

- 주소: `https://git.winetree94.com`. 외부에서는 Cloudflare Tunnel로, 내부에서는 OPNsense split DNS로 `traefik-external` LB(`10.132.246.2`)에 직접 붙는다.
- **Git 전송은 HTTPS로만 한다.** Cloudflare Tunnel은 SSH를 중계하지 않으므로 SSH 서버를 완전히 끈다.
- 인증은 Issuary(`auth.winetree94.com`) OIDC를 쓴다.

### 확정된 결정

| # | 항목 | 결정 |
|---|------|------|
| 1 | 저장소 데이터 | Git 저장소는 **Longhorn RWO**(`longhorn-strict-local`)에 둔다. LFS·첨부·패키지·아바타는 **Garage S3**(Forgejo 내장 `minio` 스토리지)에 둔다 |
| 2 | 로그인 정책 | **OIDC 전용, 수동 연결**: 자동 가입은 끄고, 관리자가 미리 만든 계정에 사용자가 직접 연결한다 |
| 3 | 부가 기능 | Git LFS, Package/Container Registry, SMTP 알림. Actions는 **이번 범위에서 제외**한다 |
| 4 | 공개 범위 | 공개 인스턴스. 로그인하지 않아도 공개 저장소를 열람하고 clone할 수 있다 |

---

## 아키텍처

```
Internet ──► Cloudflare (git.winetree94.com, 100MB body limit)
              └─► cloudflared ──► traefik-external-cloudflare:443 ─┐
LAN/VPN ──► OPNsense Unbound override → 10.132.246.2 (websecure) ──┤
                                                                     ▼
                                          forgejo-system / forgejo:3000 (HTTP)
                                            ├─ PVC forgejo-data (Longhorn, repos + indexers + queues)
                                            ├─ CNPG forgejo-database-cluster (PG 18, Barman → Garage)
                                            ├─ Garage S3 bucket tinyrack-homelab-forgejo-storage
                                            │    (via traefik-system → storage.intranet.winetree94.com)
                                            ├─ OIDC → auth.winetree94.com (traefik-external 8443)
                                            └─ SMTP → mail.winetree94.com:587
```

이 구조는 기존 `outline` 패턴을 그대로 따른다. 네임스페이스는 isolation을 켜고, Cilium 정책은 앱 쪽 정책과 traefik 쪽 `route-*` 정책으로 나눈다.

---

## 저장소 레이아웃

```
apps/base/forgejo/
  database/   namespace, CNPG Cluster/Database/ObjectStore/ScheduledBackup, user secret, CNP
  app/        HelmRelease(또는 raw), values, secrets, IngressRoute, PVC, CNP(app + traefik route)
apps/base/repositories/forgejo.yaml        # OCI HelmRepository: code.forgejo.org/forgejo-helm
apps/overlays/production/forgejo.yaml      # Flux Kustomization: forgejo-database → forgejo-deployment
apps/overlays/production/kustomization.yaml  (+ forgejo.yaml)
apps/base/issuary/issuary.config.yaml      (+ forgejo client)
apps/base/issuary/issuary.secrets.yaml     (+ ISSUARY_FORGEJO_CLIENT_SECRET, kubeseal --merge-into)
```

**배포 방식은 공식 `forgejo-helm` 차트(OCI)를 권장한다.**

- `gitea.config`로 app.ini를 선언적으로 관리할 수 있다.
- `gitea.oauth[]`에 `existingSecret`을 지정하면 Issuary 인증 소스를 자동으로 등록한다. 이 기능 때문에 CLI로 수동 등록하는 단계가 필요 없다.
- `gitea.admin.existingSecret`으로 비상용 로컬 관리자 계정을 만든다.
- 번들 서브차트(postgresql, valkey)는 모두 끄고 CNPG를 사용한다.
- rootless 이미지를 쓰며, Forgejo **v17.0.1**(현재 최신)으로 고정한다. 정확한 차트 버전은 구현 시점에 확인하고 digest로 고정한다.

---

## 핵심 설정 (app.ini 요지)

```ini
[server]
DOMAIN = git.winetree94.com
ROOT_URL = https://git.winetree94.com/
PROTOCOL = http
HTTP_PORT = 3000
DISABLE_SSH = true            ; clone URL에 SSH가 나오지 않음
START_SSH_SERVER = false
LFS_START_SERVER = true

[repository]
DISABLED_REPO_UNITS =          ; 필요시
; 기본 clone URL은 HTTPS만 노출됨 (DISABLE_SSH)

[database]
DB_TYPE = postgres
HOST = forgejo-database-cluster-rw.forgejo-system.svc:5432
SSL_MODE = disable

[service]
DISABLE_REGISTRATION = true            ; 로컬/외부 신규 가입 모두 차단
REQUIRE_SIGNIN_VIEW = false            ; 익명 열람 허용
ENABLE_NOTIFY_MAIL = true

[oauth2_client]
ENABLE_AUTO_REGISTRATION = false
ACCOUNT_LINKING = login                ; 최초 1회 로컬 비번으로 연결
OPENID_CONNECT_SCOPES = openid profile email
USERNAME = preferred_username

[openid]
ENABLE_OPENID_SIGNIN = false
ENABLE_OPENID_SIGNUP = false

[oauth2]
ENABLE = true                          ; git-credential-oauth 용 내장 OAuth2 provider

[storage]                              ; LFS/attachments/packages/avatars 공통
STORAGE_TYPE = minio
MINIO_ENDPOINT = storage.intranet.winetree94.com
MINIO_USE_SSL = true
MINIO_BUCKET = tinyrack-homelab-forgejo-storage
MINIO_LOCATION = <garage region>
; 키는 secret(env)로 주입

[lfs]
STORAGE_TYPE = minio
MINIO_BASE_PATH = lfs/

[packages]
ENABLED = true

[actions]
ENABLED = false

[mailer]
ENABLED = true
PROTOCOL = smtp+starttls
SMTP_ADDR = mail.winetree94.com
SMTP_PORT = 587
FROM = Forgejo <notify@winetree94.com>
USER = notify@winetree94.com

[cache] / [queue] / [session]
; 단일 replica이므로 Redis 없이 memory 캐시와 level 큐, db 세션을 쓴다
```

인증 소스 이름은 `issuary`로 한다. 이 이름이 콜백 경로를 결정한다. Auto Discovery URL은 `https://auth.winetree94.com/.well-known/openid-configuration`이며, 응답이 정상인 것을 확인했다.

### Issuary 클라이언트

```yaml
- id: forgejo
  name: Forgejo
  client_id: forgejo
  client_secret: ${ISSUARY_FORGEJO_CLIENT_SECRET}
  redirect_uris:
    - https://git.winetree94.com/user/oauth2/issuary/callback
  response_types: [code]
  grant_types: [authorization_code, refresh_token]
  scope: openid profile email
  skip_consent: true
```

---

## 비밀 (Bitwarden에 원본을 저장하고 SealedSecret으로 배포)

| Secret | 키 |
|---|---|
| `forgejo-database-user-secret` | username / password (basic-auth) |
| `forgejo-admin-secret` | username / password (비상용 로컬 관리자) |
| `forgejo-oauth-secret` | key=`forgejo`, secret=`<client secret>` |
| `forgejo-secrets` (env-to-ini) | `SECRET_KEY`, `INTERNAL_TOKEN`, `JWT_SECRET`(oauth2), `LFS_JWT_SECRET`, MINIO 키, SMTP 비밀번호 |
| `issuary-secrets` | `ISSUARY_FORGEJO_CLIENT_SECRET`를 추가한다. 기존 키는 `kubeseal --merge-into`로 유지한다 |

`tinyrack-homelab-s3-secret`은 reflector로 복제되는 기존 Barman 자격증명을 재사용한다. 자격증명이 forgejo 네임스페이스에도 복제되는지 확인해야 한다.

---

## Cilium 네트워크 정책

- **app**
  - ingress: traefik-external·traefik의 `:3000`
  - egress:
    - CNPG `:5432`
    - traefik-system `:8443`(Garage S3)
    - traefik-external `:8443`(OIDC)
    - 외부 `:587`(SMTP)
    - 외부 `:443`(pull mirror, 선택)
- **database**: outline 정책을 복제한다. JuiceFS 항목은 제외한다.
- **traefik route**:
  - `traefik-external-system/route-forgejo`: `git.winetree94.com`. forgejo pod의 OIDC ingress를 허용한다.
  - `traefik-system/route-forgejo`: S3. forgejo pod와 CNPG pod를 허용한다.

---

## 외부 인프라 (GitOps 밖, 수동)

1. **Garage**: `tinyrack-homelab-forgejo-storage` 버킷과 전용 키를 만든다. `rclone lsd homelab_garage:`로 확인한다.
2. **Cloudflare DNS**: `git` CNAME → `e26196aa-…cfargotunnel.com`(proxied).
3. **Cloudflare Tunnel ingress**: `git.winetree94.com` → `https://traefik-external-cloudflare.traefik-external-system.svc.cluster.local:443`, `originServerName: git.winetree94.com`. 이 규칙은 `http_status:404` catch-all보다 앞에 둔다.
4. **OPNsense Unbound**: host override `git.winetree94.com A 10.132.246.2`. 설명은 "Forgejo (traefik-external)"로 단다. 변경 전에 config 백업을 남긴다.
5. **Cloudflare 보안 설정**: Bot Fight Mode와 WAF가 `git/` UA 요청이나 `/info/refs` 요청을 차단하지 않는지 확인한다.
6. **TLS**: IngressRoute의 `letsencrypt-cert`가 `git.winetree94.com`을 포함하는지 확인한다(와일드카드 여부).

---

## ⚠️ Cloudflare 경유 시 제약과 대응

| 제약 | 영향 | 대응 |
|---|---|---|
| 요청 본문 100MB | 큰 `git push`(pack), 100MB를 넘는 LFS 객체, 큰 컨테이너 레이어 push가 외부에서 실패한다(413) | 대용량 push는 **LAN/VPN에서 한다**(split DNS 덕분에 터널을 거치지 않음). 큰 저장소는 첫 push를 커밋 범위로 나눈다. Forgejo 쪽 `LFS_MAX_FILE_SIZE`는 내부 사용을 고려해 넉넉하게 둔다 |
| 응답 대기 100초(524) | 큰 저장소의 첫 clone에서 pack 생성이 오래 걸리면 끊길 수 있다 | `[git] … pack.threads` 등 기본값으로 시작하고, 문제가 생기면 내부망으로 clone한다 |
| SSH 불가 | — | `DISABLE_SSH=true`로 SSH를 끄고 UI에 HTTPS clone URL만 노출한다 |

**HTTPS 인증:** OIDC로 연결한 계정은 git 비밀번호로 쓸 값이 없다. 다음 중 하나를 사용한다.

- **PAT**(Settings → Applications)를 발급해 credential helper에 저장한다.
- **`git-credential-oauth`**를 쓴다. Forgejo 내장 OAuth2 provider를 이용해 브라우저 로그인으로 토큰을 발급받는다. 권장 방식이며, 이를 위해 `[oauth2] ENABLE=true`를 켠다.

---

## 백업 / 복구

- **DB**: CNPG Barman → `s3://tinyrack-homelab/apps/forgejo/database-18`
  - `ScheduledBackup`을 4시간 주기로 돌린다.
  - 첫 백업이 완료되면 `bootstrap.recovery` 매니페스트로 전환한다. 이는 bifrost(`85832a0`)와 같은 패턴이다.
  - readme의 recovery 목록을 갱신한다.
- **Git 저장소 PVC**: `recurring-job-group.longhorn.io/longhorn-backup: enabled` 라벨을 붙여 하루 2회 백업하고 14개를 보관한다.
  - DB 백업 시점과 저장소 백업 시점이 어긋날 수 있다.
  - 복구 후에는 `forgejo doctor check --all`로 정합성을 확인한다.
- **S3 객체**: Garage에 저장되므로 OMV borgmatic 백업 범위에 들어간다.

---

## 실행 단계

1. **사전 준비**(수동)
   - Garage 버킷과 키를 만든다.
   - Bitwarden에 비밀을 생성한다.
   - SealedSecret 4종을 만들고 issuary-secrets에 키를 병합한다.
2. **Issuary 커밋**: forgejo 클라이언트를 추가한다. reconcile 후 discovery와 authorize 엔드포인트가 동작하는지 확인한다.
3. **Forgejo DB 커밋**: namespace, CNPG, CNP를 추가한다. `forgejo-database` Kustomization이 Ready가 되고 첫 Backup이 completed가 되는지 확인한다.
4. **Forgejo 앱 커밋**: HelmRepository, HelmRelease, PVC, IngressRoute, CNP, overlay 항목을 추가한다.
   - 검증: `kubectl kustomize ./apps/overlays/production`
   - 검증: `kubectl kustomize ./apps/base/forgejo/{database,app}`
5. **네트워크**: OPNsense override를 추가한 뒤 Cloudflare tunnel ingress와 DNS를 추가한다.
6. **기능 검증**
   - 익명 사용자로 공개 저장소를 열람하고 clone한다(내부·외부 각각).
   - 관리자가 로컬 계정을 생성하고, 사용자가 Issuary로 로그인해 계정을 연결한 뒤 이후 OIDC만으로 로그인되는지 확인한다.
   - HTTPS push를 PAT와 git-credential-oauth로 각각 확인한다.
   - LFS 객체를 push한 뒤 Garage 버킷에 `lfs/` 객체가 생기는지 확인한다.
   - `docker login git.winetree94.com` 후 작은 이미지를 push/pull한다.
   - 메일 알림(테스트 메일)이 발송되는지 확인한다.
   - UI에 SSH clone URL이 노출되지 않는지 확인한다.
   - Cilium drop이 없는지 `hubble observe --verdict DROPPED -n forgejo-system`로 확인한다.
7. **후속**
   - DB를 `bootstrap.recovery`로 전환하고 readme를 갱신한다.
   - Grafana 대시보드와 알림을 추가한다(Forgejo `/metrics`, `[metrics] ENABLED=true` + 토큰).
   - Renovate가 차트와 이미지를 추적하는지 확인한다.

---

## 미확인 / 구현 시 검증할 것

- `ACCOUNT_LINKING=login`과 `DISABLE_REGISTRATION=true`를 함께 설정했을 때 OIDC 콜백에서 "계정 연결" 화면이 정상으로 뜨는지 확인한다.
  - 뜨지 않으면 대안을 쓴다: `ENABLE_AUTO_REGISTRATION=true` + `ACCOUNT_LINKING=auto` + 동일 username/email로 사전 생성. 이 경우 Issuary는 가입이 닫혀 있으므로 계정 범위가 Issuary 사용자로 한정된다.
- 클러스터 내부에서 `auth.winetree94.com`이 `10.132.246.2`로 해석되는지 확인한다. outline은 이 경로로 동작 중이다.
- `letsencrypt-cert`가 커버하는 호스트를 확인한다.
- forgejo-helm 차트 최신 버전과 Forgejo 17 호환성, rootless 이미지의 UID/fsGroup을 확인한다.

---

## 실행 결과 (2026-11-03)

| 항목 | 결과 |
|---|---|
| 차트 / 이미지 | forgejo-helm `17.3.2`, `forgejo:17.0.1-rootless` (digest 고정). 17.0.0의 push 불가 버그(#14866)는 17.0.1에서 수정됨 |
| Garage | 버킷 `tinyrack-homelab-forgejo-storage`, 전용 키 `forgejo` |
| Bitwarden | `ef50cbda-817a-4985-9518-b4f7009538fa`(관리자 `me`), `31997b29-000d-4eeb-a9af-b4f700954132`(인프라 시크릿 원본), `9829213e-c3ea-4a48-b3d0-b4bf00700c3a` 필드 `app password (forgejo)`(SMTP) |
| Issuary | 클라이언트 `forgejo`, `ISSUARY_FORGEJO_CLIENT_SECRET` 병합 |
| OPNsense | Unbound host override `git.winetree94.com → 10.132.246.2` |
| Cloudflare | Tunnel ingress(catch-all 앞), proxied CNAME `git` |
| CNPG | 첫 base backup 완료 후 `bootstrap.recovery` 로 전환, readme 갱신 |
| 검증 | 익명 clone, HTTPS push(PAT), LFS(Garage), generic 패키지, OCI push/pull, SMTP 수신, UI에 SSH URL 미노출, 외부(Cloudflare)·내부 경로 200 |

### 계획과 달라진 점 / 운영 메모

- `[lfs]`에 `STORAGE_TYPE`을 직접 쓰면 `[storage]` 상속이 끊겨 MinIO endpoint가 비고 서버가 죽는다. `[lfs]`는 비워 두고 상속받는다(기본 prefix `lfs/`).
- `[oauth2] ENABLE`은 deprecated → `ENABLED`.
- 차트의 env-to-ini는 app.ini에 키를 **추가/수정만** 하고 삭제하지 않는다. values에서 키를 지웠다면 PVC의 `/data/gitea/conf/app.ini`에서도 직접 지워야 한다. Helm도 Secret `stringData`에서 빠진 키(`forgejo-inline-config`의 `data.*`)를 지우지 못하므로 함께 정리한다.
- OIDC 인증 소스(`issuary`)와 관리자 계정은 차트 init 컨테이너가 매 기동 시 동기화한다.
- 남은 확인: 사용자가 Issuary로 처음 로그인했을 때 `ACCOUNT_LINKING=login` 연결 화면이 정상 동작하는지(사람만 할 수 있는 단계).

### 로컬 로그인 비활성화 (2026-11-03)

`me` 계정이 Issuary와 연결된 것을 확인한 뒤 `[service] ENABLE_INTERNAL_SIGNIN=false`, `ENABLE_BASIC_AUTHENTICATION=false`를 적용했다.

- 웹 로그인은 "Sign in with issuary"만 남는다(`POST /user/login`은 403).
- Git·API는 비밀번호 Basic 인증을 거부한다. PAT 또는 `git-credential-oauth` 토큰만 쓴다.
- 로컬 비밀번호(Bitwarden `ef50cbda-…`)는 차트 init 컨테이너가 계속 동기화하지만 로그인에는 쓸 수 없다.
- **비상 접근**(Issuary 장애 시): `kubectl -n forgejo-system exec deploy/forgejo -c forgejo -- forgejo admin user generate-access-token --username me --token-name emergency --scopes all`로 토큰을 발급해 API를 쓴다. 웹 UI가 필요하면 values에서 `ENABLE_INTERNAL_SIGNIN`을 일시적으로 `true`로 되돌린다.

### 사고 기록: DB 비밀번호 초기화 (2026-11-03)

`bootstrap.recovery`로 바꿀 때 `secret`을 빼자 CNPG가 `forgejo-database-cluster-app`을 새로 만들고 `forgejo` 역할 비밀번호를 그 값으로 바꿨다. 그 결과 다음 롤아웃에서 Forgejo가 DB에 접속하지 못했다(`password authentication failed`). 이미 실행 중이던 파드는 기존 연결을 유지해 바로 드러나지 않았다.

- `recovery.secret: forgejo-database-user-secret`을 복원했다(`dc3787c`).
- `ALTER ROLE forgejo PASSWORD …`로 비밀번호를 sealed secret 값으로 되돌렸다.
- bifrost는 앱이 `*-database-user-secret`을 쓰면서 recovery에 `secret`이 없어 같은 위험이 있는지 별도로 확인할 것.
