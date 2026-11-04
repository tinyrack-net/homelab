# Plan: Bifrost에 이메일·S3 MCP 추가 (email-mcp, rclone-mcp) — 실행 완료 (2026-11-03)

## Context

Bifrost(`bifrost-system`)에 두 MCP 서버를 추가해, 에이전트가 himalaya·rclone 없이도 다중 메일 계정과 다중 S3 저장소를 다루게 한다.

- **이메일**: [`codefuturist/email-mcp`](https://github.com/codefuturist/email-mcp) `0.6.0`. 다중 IMAP/SMTP 계정을 지원하고 도구가 52개다. Streamable HTTP를 내장하고 공식 이미지를 제공한다.
- **S3**: [`rclone-ui/rclone-mcp`](https://github.com/rclone-ui/rclone-mcp) `2.0.0`과 `rclone rcd`(≥ 1.75.2) 조합. rclone remote 단위로 다중 저장소를 다루고, 버킷은 `operations_mkdir`/`operations_rmdir`(`remote:bucket`)로 생성·삭제한다.
- 자격증명은 로컬 himalaya·rclone 설정을 그대로 옮긴다.

### 확정된 결정

| # | 항목 | 결정 |
|---|------|------|
| 1 | 배포 형태 | 기존 `gcp-mcp` 패턴을 따른다. 전용 네임스페이스(isolation 켬)에 Deployment를 두고, Service는 ClusterIP만 만든다. 외부 IngressRoute는 만들지 않는다 |
| 2 | 인증 | 서버마다 Bearer 토큰을 쓴다. Bifrost에는 `Authorization` 헤더로 등록한다. 토큰 원본은 Bitwarden에 둔다 |
| 3 | 이메일 계정 | 로컬 himalaya 13개 계정을 전부 옮긴다. 대상은 Stalwart 11개(winetree94.com 5, tinyrack.net 6)와 `gmail-personal`, `gmail-vivident`다. 계정 이름은 himalaya와 같게 맞춘다 |
| 4 | 이메일 쓰기 권한 | 13개 계정 모두 쓰기를 허용한다(`MCP_EMAIL_READ_ONLY=false`). 발송·이동·삭제까지 쓴다 |
| 5 | S3 remote | 로컬 4개를 옮기고 **모두 쓰기를 허용한다**. 대상은 `homelab_garage`, `hetzner_fsn`, `hetzner_hel`, `vivident_intranet_s3`다. `vivident_intranet_s3`도 버킷 생성·삭제를 허용한다 |
| 6 | rclone 도구 범위 | `RCLONE_TOOLSETS=default,dangerous`를 쓴다. `operations_purge`를 열어 비어 있지 않은 버킷도 삭제할 수 있게 한다. 그 결과 `config_dump`·`core_command`·`job_batch` 같은 도구도 함께 노출된다. 이 위험은 감수한다. 그래서 Bifrost 토큰과 네트워크 정책이 유일한 경계다 |
| 7 | 로컬 자격증명 | `secrets.zsh`의 S3 키는 지금 그대로 둔다. Bitwarden으로 옮기지 않고 교체도 하지 않는다 |
| 8 | Bifrost 서버 이름 | `email`, `rclone` |

---

## 아키텍처

```
bifrost-system / bifrost ──(Bearer)──┬─► email-mcp-system / email-mcp:8000 (/mcp)
                                     │     ├─ ConfigMap config.toml (13 accounts, password = "env:…")
                                     │     ├─ SealedSecret (account passwords, HTTP token)
                                     │     ├─ PVC email-mcp-state (state + cache)
                                     │     └─► mail.winetree94.com:993/465, imap/smtp.gmail.com:993/465 (public)
                                     │
                                     └─► rclone-mcp-system / rclone-mcp:8000 (/mcp)
                                           pod: rclone-mcp (node) ──127.0.0.1:5572──► rclone rcd (sidecar)
                                           ├─ ConfigMap rclone.conf (endpoint/region only, env_auth)
                                           ├─ SealedSecret (RCLONE_CONFIG_*_ACCESS_KEY_ID/SECRET, MCP token, rc pass)
                                           ├─► traefik-system:8443 → storage.intranet.winetree94.com (Garage)
                                           └─► Hetzner fsn1/hel1, AWS S3 ap-northeast-2 (public :443)
```

---

## 저장소 레이아웃

```
apps/base/email-mcp/
  kustomization.yaml
  email-mcp.namespace.yaml              # networking.tinyrack.net/isolation: enabled
  email-mcp.configmap.yaml              # config.toml (no secrets)
  email-mcp.secret.yaml                 # SealedSecret: MAIL_*_PASSWORD, EMAIL_MCP_HTTP_TOKEN
  email-mcp.pvc.yaml                    # longhorn, 1Gi (state + cache)
  email-mcp.deployment.yaml
  email-mcp.service.yaml
  email-mcp.cilium-network-policy.yaml
apps/base/rclone-mcp/
  kustomization.yaml
  rclone-mcp.namespace.yaml
  rclone-mcp.configmap.yaml             # rclone.conf (no secrets)
  rclone-mcp.secret.yaml                # SealedSecret: RCLONE_CONFIG_*, RCLONE_MCP_TOKEN, RCLONE_RC_PASS
  rclone-mcp.deployment.yaml            # rclone rcd + rclone-mcp
  rclone-mcp.service.yaml
  rclone-mcp.cilium-network-policy.yaml # app + traefik-system/route-rclone-mcp (Garage)
apps/overlays/production/email-mcp.yaml   # Flux Kustomization (dependsOn: sealed-secrets)
apps/overlays/production/rclone-mcp.yaml
apps/overlays/production/kustomization.yaml          (+ 2 entries)
apps/base/bifrost/bifrost.cilium-network-policy.yaml (+ egress to both namespaces :8000)
```

---

## 서버별 설정

### email-mcp

- 이미지: `ghcr.io/codefuturist/email-mcp:0.6.0@sha256:<index digest>`. 구현 시 digest를 확인한다.
- 실행: `email-mcp http --host 0.0.0.0 --port 8000 --path /mcp`
- env:
  - `EMAIL_MCP_HTTP_TOKEN`(secret)
  - `EMAIL_MCP_HTTP_ALLOWED_HOSTS=email-mcp.email-mcp-system.svc.cluster.local,email-mcp.email-mcp-system.svc`
  - `MCP_EMAIL_READ_ONLY=false`
  - `XDG_CONFIG_HOME`/`XDG_STATE_HOME`/`XDG_CACHE_HOME` 경로를 지정한다.
- 볼륨:
  - `config.toml`은 ConfigMap에서 read-only로 마운트한다.
  - state와 cache는 PVC에 둔다. state에 예약 발송 큐가 있어 재시작 후에도 유지해야 한다.
- probe: `GET /healthz`
- `config.toml` 생성 규칙(himalaya → email-mcp):
  - `imap.server = "imaps://H:P"`는 `[accounts.imap] host=H, port=P, tls=true`로 옮긴다.
  - `smtp.server = "smtps://H:465"`는 `[accounts.smtp] host=H, port=465, tls=true, starttls=false`로 옮긴다.
  - `email`과 `display-name`은 `email`과 `full_name`으로 옮긴다.
  - `password.command = ['bw-secret', <vault>, <id>, <field>]`는 `password = "env:MAIL_<N>_PASSWORD"`로 바꾼다. 값은 `bw`로 조회해 SealedSecret에 넣는다. vivident vault 항목은 `bw-vivident`로 조회한다.
  - 불필요한 기능은 끈다. 데스크톱 알림·클립보드·첨부 저장 디렉터리가 해당된다.
- 변환은 일회성 스크립트로 한다. 비밀값은 파이프로만 `kubeseal`에 넘기고 디스크에 평문으로 남기지 않는다.

### rclone-mcp

- 컨테이너 `rclone`:
  - 이미지: `docker.io/rclone/rclone:1.75.2@sha256:<digest>`
  - 실행: `rclone rcd --rc-addr 127.0.0.1:5572 --rc-user mcp --rc-pass $(RCLONE_RC_PASS) --config /config/rclone.conf`
  - `rclone.conf`는 initContainer가 ConfigMap에서 emptyDir로 복사한다. `config_create`/`update`가 쓰기에 실패해도 되지만, rclone이 설정을 저장하려 할 때 에러가 나지 않게 하기 위해서다.
  - env: `RCLONE_CONFIG_<REMOTE>_ACCESS_KEY_ID`/`_SECRET_ACCESS_KEY` 8개(secret). 로컬 `~/.config/zsh/secrets.zsh`와 같은 방식이다.
- 컨테이너 `rclone-mcp`:
  - 실행: `gcp-mcp`처럼 `node:22-alpine` initContainer에서 `npm install rclone-mcp@2.0.0` 후 `rclone-mcp http --host 0.0.0.0 --port 8000`
  - env:
    - `RCLONE_URL=http://127.0.0.1:5572`
    - `RCLONE_USER=mcp`
    - `RCLONE_PASS`(secret)
    - `RCLONE_MCP_TOKEN`(secret)
    - `RCLONE_TOOLSETS=default,dangerous`
- `rclone.conf`는 로컬 파일을 그대로 쓴다. 파일 안에는 `endpoint`/`region`/`acl`/`env_auth`만 있고 비밀은 없다.

---

## 비밀 (Bitwarden 원본 → SealedSecret)

| Secret | 키 | 원본 |
|---|---|---|
| `email-mcp-secrets` | `EMAIL_MCP_HTTP_TOKEN` | 새로 생성한 뒤 Bitwarden에 저장한다(id를 이 문서에 기록) |
| | `MAIL_<N>_PASSWORD` ×13 | himalaya `password.command`가 가리키는 Bitwarden 항목·필드 |
| `rclone-mcp-secrets` | `RCLONE_MCP_TOKEN`, `RCLONE_RC_PASS` | 새로 생성한 뒤 Bitwarden에 저장한다 |
| | `RCLONE_CONFIG_*_ACCESS_KEY_ID` / `_SECRET_ACCESS_KEY` ×4 remote | 로컬 `secrets.zsh`의 값(vivident는 `VIVIDENT_AWS_*`) |

> S3 키는 로컬 `secrets.zsh` 값을 그대로 SealedSecret으로 만든다. 이번 범위에서는 Bitwarden으로 옮기지 않는다(결정 #7).

---

## Cilium 네트워크 정책

- **bifrost** (`bifrost.cilium-network-policy.yaml`): egress를 `email-mcp-system/app=email-mcp:8000`과 `rclone-mcp-system/app=rclone-mcp:8000`에 추가한다.
- **email-mcp**:
  - ingress: bifrost `:8000`만 받는다.
  - egress: 외부 IMAP/SMTP는 공인 대역이라 `isolated-namespaces`가 이미 허용한다. 추가 규칙이 필요 없다.
- **rclone-mcp**:
  - ingress: bifrost `:8000`만 받는다.
  - egress: traefik-system `:8443`(Garage)을 추가한다. Hetzner와 AWS는 공인 대역이라 이미 허용된다.
  - npm registry는 initContainer가 쓰며, 공인 대역이라 이미 허용된다.
- **traefik route**: `traefik-system/route-rclone-mcp`(`networking.tinyrack.net/hosts: storage.intranet.winetree94.com`)를 만든다. outline/personal-data 패턴을 따라 rclone-mcp pod의 `:8443` ingress를 허용한다.

---

## 실행 단계

1. **로컬 사전 검증**(클러스터 밖)
   - `email-mcp`: 변환한 `config.toml`로 `npx @codefuturist/email-mcp@0.6.0 test`를 실행해 13개 계정 모두 연결되는지 확인한다.
   - `rclone-mcp`: `RCLONE_TOOLSETS=default,dangerous npx rclone-mcp@2.0.0 http`(로컬 rclone 사용)로 실행한다. `config_listremotes`, `operations_list`, `operations_mkdir` / `operations_rmdir` / `operations_purge`로 `homelab_garage:`에 테스트 버킷을 만들고 지운다.
2. **비밀 준비**: 토큰 3종을 생성해 Bitwarden에 저장한다. SealedSecret 2종을 만든다(README의 `kubeseal --cert` 패턴).
3. **email-mcp 커밋**
   - base, overlay, bifrost CNP egress를 추가한다.
   - 검증: `kubectl kustomize ./apps/base/email-mcp`, `kubectl kustomize ./apps/overlays/production`
   - reconcile 후 pod Ready, `/healthz`, 토큰 없는 요청에 401이 오는지 확인한다.
4. **rclone-mcp 커밋**
   - base, overlay, traefik route CNP, bifrost CNP egress를 추가한다.
   - 검증: `kubectl kustomize ./apps/base/rclone-mcp`
5. **Bifrost 등록**(UI, 수동): config_store(Postgres)에 저장된다.
   - `email` → `http://email-mcp.email-mcp-system.svc.cluster.local:8000/mcp`
   - `rclone` → `http://rclone-mcp.rclone-mcp-system.svc.cluster.local:8000/mcp`
   - 두 서버 모두 Streamable HTTP로, `Authorization: Bearer <token>` 헤더를 붙여 등록한다.
6. **기능 검증**(`codemode` → `tools.mcp__bifrost__*`)
   - `listToolFiles`에 `email.pyi`와 `rclone.pyi`가 보이는지 확인한다.
   - email: 계정 목록 13개를 확인한다. `stalwart-me@winetree94.com` INBOX 조회·검색, `stalwart-tester@tinyrack.net`에서 자기 자신에게 테스트 발송 → 수신 → 삭제를 해 본다. Gmail 계정 1개도 조회한다.
   - rclone: remote 4개 목록을 확인한다. 각 remote에서 `lsd`를 실행한다. `homelab_garage:`에서 테스트 버킷 생성·객체 업로드 후 `operations_purge`로 비어 있지 않은 버킷을 삭제해 본다.
   - drop 확인: `hubble observe --verdict DROPPED -n email-mcp-system` / `-n rclone-mcp-system`
7. **후속**
   - 지침과 스킬을 갱신한다. `email-management` 스킬에 Bifrost `email` 서버 우선 사용을 추가할지 정한다. rclone 사용 지침도 정리한다(`agent-configuration` 스킬 절차를 따른다).
   - Renovate가 `email-mcp`/`rclone` 이미지와 `rclone-mcp` npm 버전을 추적하는지 확인한다.

---

## 미확인 / 구현 시 검증할 것

- email-mcp의 계정 `name`에 `@`과 `.`이 들어가도 되는지 확인한다. 안 되면 `stalwart-me-winetree94` 형태로 바꾸고 매핑표를 남긴다.
- email-mcp 이미지의 실행 UID와 홈 경로(`/home/node/...`)를 확인하고, `securityContext`와 PVC `fsGroup`을 맞춘다.
- 13개 계정의 IMAP 연결 수와 메모리 사용량을 확인한다. 계정별 IDLE/동기화 기본값을 확인하고, 필요하면 watcher를 끈다.
- Bifrost가 보내는 `Host` 헤더를 확인한다. `ALLOWED_HOSTS` 설정이 맞지 않으면 403이 난다.
- rclone-mcp 2.0.0 HTTP 모드에 health endpoint가 있는지 확인한다. 없으면 tcpSocket probe를 쓴다.
- `homelab_garage` endpoint(`storage.intranet.winetree94.com`)가 클러스터 안에서 traefik-system LB로 해석되는지 확인한다. 기존 Barman·JuiceFS 경로와 같다.
- Garage에서 `mkdir remote:bucket`이 버킷을 만드는지 확인한다. Garage 키에 `--create-bucket` 권한이 있어야 한다. Hetzner와 AWS IAM 권한도 확인한다.
- `vivident_intranet_s3` 키의 IAM 권한에 `s3:CreateBucket`/`s3:DeleteBucket`이 있는지 확인한다. 없으면 MCP가 아니라 IAM 쪽 제약이다.
- `dangerous` 묶음이 기본 묶음 없이 단독으로만 켜지는지 확인한다. `default,dangerous` 조합이 동작하는지 로컬 단계에서 본다.

---

## 실행 결과 (2026-11-03)

| 항목 | 결과 |
|---|---|
| email-mcp | `ghcr.io/codefuturist/email-mcp:0.6.0`(digest 고정). 13개 계정 IMAP 연결. PVC `email-mcp-data`(5Gi). 기동 직후 메모리는 약 250–430Mi여서 requests 512Mi, limits 2Gi로 정했다 |
| rclone-mcp | `rclone/rclone:1.75.2` + `rclone-mcp@2.0.0`(node 22). `RCLONE_TOOLSETS=default,dangerous`로 도구 68개 |
| Bitwarden | `344e14cc-213f-410a-9273-b4f700a68590` — `bifrost-mcp (homelab secrets)`. 필드는 `EMAIL_MCP_HTTP_TOKEN`, `RCLONE_MCP_TOKEN`, `RCLONE_RC_PASS`. 메일 비밀번호는 himalaya가 참조하는 기존 항목을 그대로 쓴다 |
| Bifrost 클라이언트 | `email`, `rclone`(code mode, headers 인증, `tools_to_execute=["*"]`)을 관리자 API(`POST /api/mcp/client`)로 등록했다 |
| Bifrost 권한 | 접근 권한은 VK `mcp_configs`가 아니라 **Virtual MCP**로 준다. `dev`(id 2)와 `personal`(id 4) Virtual MCP에 두 클라이언트를 추가했다. `vivident_admin`에는 추가하지 않았다 |
| 검증 | email: 계정 13개 확인, Stalwart·Gmail 목록 조회, tester→tester 발송·검색·영구 삭제. rclone: remote 4개 `lsd` 성공(Garage는 Traefik 경유). `hetzner_fsn`에서 버킷 생성→업로드→`purge` 성공. Cilium drop 없음 |

### 계획과 달라진 점 / 운영 메모

- Garage 키 `GK45d4…`(이름 `dev`)에는 원래 버킷 생성 권한이 없었다. 2026-11-03에 `garage key allow --create-bucket`으로 권한을 줬다(OMV의 `garage-garaged-1` 컨테이너). 그 뒤 Bifrost `rclone`으로 버킷 생성→업로드→`purge`가 되는 것을 확인했다.
- **Hetzner는 버킷 생성·삭제가 eventual consistency다.** `mkdir` 직후 PutObject를 하면 `NoSuchBucket`이 나고, `purge` 직후 목록에는 버킷이 잠시 남아 있다. 10–20초 뒤에는 정상이다.
- rclone-mcp에는 health endpoint가 없다(`/mcp` 이외는 404). 그래서 tcpSocket probe를 쓴다.
- `rclone rcd`는 `RCLONE_RC_PASS`를 환경변수에서 읽는다. 그래서 args에 비밀번호를 넣지 않는다.
- 보낸 메일 사본: `[settings.send] save_to_sent = true`(2026-11-03 추가). Stalwart 계정은 \Sent 폴더(`Sent Items`)에 사본이 저장된다. 배포된 0.6.0 이미지는 Gmail 계정을 자동으로 건너뛴다(git 태그 v0.6.0 소스와 다르다). Gmail에서 사본이 중복되지 않는 것도 확인했다. config는 `email-mcp.config.toml` + `configMapGenerator`로 관리하므로, 바꾸면 pod가 자동으로 재시작된다.
- email-mcp 계정 이름에 `@`이 들어가도 동작한다(himalaya 이름과 같다).
- Bifrost `GET /api/mcp/clients`는 기본 `limit=25`로 페이지를 나눈다. 전체를 보려면 `?limit=100`을 붙인다.
- `email-management` 스킬을 Bifrost `email` 우선, Himalaya는 대체 수단으로 갱신했다(2026-11-03).

---

## rclone-system 이전과 Web GUI 추가 (2026-11-03)

위 계획의 `rclone-mcp-system`과 `apps/base/rclone-mcp`는 **`rclone-system`과 `apps/base/rclone`으로 바꿨다.** 이전 경로는 Flux prune으로 삭제됐다.

```
rclone-system / deploy rclone (pod 하나)
  ├─ rclone gui        :5522  Web GUI(rclone 내장, rclone-web 1.1.11)
  │                    :5572  RC API (--rc-baseurl=/api, --rc-htpasswd: admin, mcp)
  └─ rclone-mcp        :8000  /mcp (Bearer) → RCLONE_URL=http://127.0.0.1:5572/api, user mcp
Service rclone(5522, 5572), Service rclone-mcp(8000)
IngressRoute rclone.intranet.winetree94.com
  ├─ /api/ → :5572
  └─ /     → :5522        (둘 다 Traefik basicAuth `rclone-basic-auth`, admin만)
```

| 항목 | 내용 |
|---|---|
| 접속 | `https://rclone.intranet.winetree94.com/login?url=https://rclone.intranet.winetree94.com/api/` (내부 Traefik, LAN/VPN 전용) |
| 로그인 | `admin` / Bitwarden `344e14cc-…` 필드 `RCLONE_WEB_ADMIN_PASS`. 브라우저 Basic 인증 창과 GUI 로그인 폼에 같은 값을 넣는다 |
| 비밀 | `rclone-secrets`: S3 키, `RCLONE_MCP_TOKEN`, `RCLONE_RC_PASS`(mcp 로그인), `htpasswd`(admin+mcp). `rclone-basic-auth`: `users`(admin). Traefik basicAuth는 키가 하나뿐인 Secret만 받는다 |
| Bifrost | `rclone` 클라이언트를 새로 만들었다. `connection_string`은 수정할 수 없어서 삭제 후 재등록했다. 주소는 `http://rclone-mcp.rclone-system.svc.cluster.local:8000/mcp`. `dev`·`personal` Virtual MCP에 다시 연결했다 |
| 설정 | `rclone.conf`는 `configMapGenerator`로 관리한다. GUI·MCP에서 remote를 바꾸면 pod 안의 사본(emptyDir)에만 저장되고, 재시작하면 ConfigMap 내용으로 돌아간다 |

### 결정과 이유

- **프로세스 하나**: 공식 문서(rclone.org/gui)의 `rclone gui`가 GUI와 RC API를 함께 띄운다. rclone-mcp가 같은 RC API를 쓰므로 GUI와 MCP의 remote·작업(Transfers)·serve 목록이 같다.
- **Traefik basicAuth**: rclone RC는 401에 `WWW-Authenticate: Basic`을 붙인다. GUI의 연결 확인 fetch가 이 응답을 받으면 브라우저 로그인 창이 떠서 "Connecting..."에서 멈춘다. 그래서 호스트 전체를 Traefik basicAuth로 막아 브라우저가 먼저 admin 자격 증명을 기억하게 했다. GUI 정적 파일도 인증 뒤에 둔다.
- **업로드**: GUI 업로드는 `operations/uploadfile`(multipart)이라 Ingress 경유로 동작한다. 3MB 바이너리 업로드도 확인했다.

### 제약

- **GUI의 Download 버튼은 동작하지 않는다.** 이 버튼은 `serve/start`로 pod 안 임의 포트(`:0`)에 HTTP serve를 열고, 브라우저가 `https://rclone.intranet…:<port>`로 직접 받는다. 그 포트는 Ingress로 노출되지 않는다. `rclone gui`는 `--rc-serve` 경로(`/[remote:path]/file`)도 처리하지 않는다(`rclone rcd`에서는 동작). 다운로드는 다음 중 하나로 한다.
  - Bifrost `rclone.operations_publiclink(fs, remote, expire="1h")`로 presigned URL을 받는다.
  - 로컬 `rclone copy`를 쓴다.
- BrowserOS로 GUI를 자동 조작할 때는 BrowserOS 오버레이가 버튼을 가리는 경우가 있다. Connect는 비밀번호 칸에서 Enter로 제출한다.

---

## rclone Web GUI 제거 (2026-11-03, 실행 완료)

Web GUI는 쓰지 않기로 했다. `rclone gui`를 다시 **`rclone rcd`(loopback 전용)**로 되돌리고, 외부에 노출하던 것을 모두 걷어낸다. **namespace `rclone-system`, 경로 `apps/base/rclone`, Bifrost `rclone` 서버는 그대로 둔다.**

### 바뀌는 것

| 대상 | 현재 | 변경 후 |
|---|---|---|
| `rclone` 컨테이너 | `gui --addr=:5522 --api-addr=:5572 --rc-baseurl=/api --rc-htpasswd` | `rcd --rc-addr=127.0.0.1:5572 --rc-user=mcp`. 비밀번호는 env `RCLONE_RC_PASS`에서 읽는다(GUI 추가 전 방식) |
| probe | gui `:5522` httpGet + api tcpSocket | rclone 컨테이너 probe 제거(loopback이라 kubelet이 닿지 않는다). rclone-mcp의 tcpSocket probe만 남긴다 |
| `rclone-mcp` env | `RCLONE_URL=http://127.0.0.1:5572/api` | `http://127.0.0.1:5572` |
| Service `rclone`(5522, 5572) | 있음 | **삭제**. `rclone-mcp`(8000)만 남긴다 |
| IngressRoute, Middleware `rclone-basic-auth` | 있음 | **삭제** (`rclone.ingress-route.yaml`) |
| SealedSecret `rclone-basic-auth` | 있음 | **삭제** (`rclone.basic-auth.secret.yaml`) |
| SealedSecret `rclone-secrets` | `htpasswd` 키 포함 | `htpasswd` 키를 빼고 다시 봉인한다. 나머지 키(S3, `RCLONE_MCP_TOKEN`, `RCLONE_RC_PASS`)는 그대로 둔다 |
| secrets 볼륨 마운트 | `/secrets/htpasswd` | 삭제 |
| CNP `app-rclone` | ingress: bifrost `:8000` + traefik `:5522/:5572` | ingress: bifrost `:8000`만 남긴다. egress(traefik `:8443`, Garage)는 그대로 둔다 |
| CNP `traefik-system/route-rclone` | hosts `rclone.intranet…,storage.intranet…`. ingress(Garage) + egress(rclone svc) | hosts는 `storage.intranet.winetree94.com`만 남긴다. egress(→ rclone svc) 규칙은 삭제하고, ingress(rclone pod → `:8443`)는 남긴다 |
| Bitwarden `344e14cc-…` | 필드 `RCLONE_WEB_ADMIN_PASS` 있음 | 필드 삭제 |
| 이 문서 | "rclone-system 이전과 Web GUI 추가" 절 | 그대로 둔다(이력). 아래에 결과를 추가한다 |

바뀌지 않는 것:
- Bifrost `rclone` 클라이언트 주소는 그대로다(`rclone-mcp.rclone-system.svc…:8000/mcp`). 재등록이 필요 없다.
- `rclone.conf`(configMapGenerator), init 컨테이너, `RCLONE_TOOLSETS=default,dangerous`, 리소스 설정도 그대로다.

DNS: `rclone.intranet.winetree94.com`은 별도 레코드 없이 `*.intranet` 와일드카드로 내부 Traefik에 붙어 있었다. 따라서 IngressRoute만 지우면 404가 된다. 지울 DNS 레코드는 없다(실행 시 OPNsense override가 없는지 한 번 확인한다).

### 실행 단계

1. **secret 재봉인**: `rclone-secrets`에서 `htpasswd`를 빼고 `kubeseal`로 다시 만든다. 값은 Bitwarden과 로그인 셸 env에서 파이프로만 넘긴다.
2. **매니페스트 수정**
   - `rclone.deployment.yaml`: args, probe, `RCLONE_URL`, secrets 볼륨을 고친다. 상단 주석도 고친다.
   - `rclone.service.yaml`: Service `rclone`을 삭제한다.
   - `rclone.ingress-route.yaml`, `rclone.basic-auth.secret.yaml`: 삭제하고 `kustomization.yaml`에서 뺀다.
   - CNP 두 개를 위 표대로 고친다.
3. **검증(로컬)**
   - `kubectl kustomize ./apps/base/rclone`을 실행한다. 렌더링 결과에 `5522`, `htpasswd`, `basic-auth`가 남아 있지 않은지 `grep`으로 확인한다.
   - `kubectl kustomize ./apps/overlays/production`도 실행한다.
4. **커밋·배포**: `feat(rclone): drop the web GUI and keep rcd on loopback`. push 후 `flux reconcile`한다. 지운 리소스(Service, IngressRoute, Middleware, SealedSecret)는 prune된다.
5. **검증(클러스터)**
   - pod `2/2 Running`, 로그에 `Serving remote control on http://127.0.0.1:5572/`가 보이는지 확인한다.
   - `rclone-system`에 남은 리소스가 Service `rclone-mcp`와 SealedSecret `rclone-secrets`뿐인지 본다. `traefik-system/route-rclone`의 hosts도 확인한다.
   - `https://rclone.intranet.winetree94.com/`이 404를 반환하는지 확인한다.
   - Bifrost `rclone`으로 `config_listremotes`, `homelab_garage:`/`hetzner_fsn:` `lsd`를 실행한다. Garage에서 테스트 버킷 생성 → 업로드 → `purge`까지 해 본다.
   - `hubble observe --verdict DROPPED -n rclone-system`에 drop이 없는지 본다.
6. **정리**
   - Bitwarden에서 `RCLONE_WEB_ADMIN_PASS` 필드를 지운다.
   - 이 문서에 실행 결과를 기록한다.

### 위험·되돌리기

- 실패하면 `git revert`로 GUI 구성(커밋 `b645868`)으로 돌아간다. 그 경우 `RCLONE_WEB_ADMIN_PASS`는 Bitwarden에 아직 있어야 하므로, **필드 삭제는 검증이 끝난 뒤 마지막에 한다.**
- 바뀌는 것은 MCP가 rclone에 붙는 주소(`/api` 제거)와 인증 방식(htpasswd → `--rc-user/--rc-pass`)이다. 둘 다 GUI 추가 전에 쓰던 값이라 위험이 낮다.

### 실행 결과 (2026-11-03)

| 항목 | 결과 |
|---|---|
| 커밋 | `9a45471` feat(rclone): drop the web GUI and keep rcd on loopback |
| pod | `rclone` 2/2 Running. `rclone rcd`가 `http://127.0.0.1:5572/`에서 동작하고, rclone-mcp는 같은 주소로 붙는다(도구 68개) |
| 남은 리소스 | `rclone-system`: Service `rclone-mcp`, SealedSecret `rclone-secrets`(키 10개, `htpasswd` 없음), ConfigMap `rclone-config-*`, CNP `app-rclone`. `traefik-system/route-rclone`의 hosts는 `storage.intranet.winetree94.com`만 남았다. Service `rclone`, IngressRoute, Middleware, `rclone-basic-auth`는 prune됐다 |
| 외부 | `https://rclone.intranet.winetree94.com/`과 `/api/` 모두 404. OPNsense `config.xml`에 rclone 항목 없음 |
| Bifrost | `rclone` 클라이언트 그대로. remote 4개, Garage·Hetzner `lsd`, Garage 버킷 생성→업로드→`purge` 성공 |
| Cilium | `rclone-system` drop 없음 |
| Bitwarden | `344e14cc-…`에서 `RCLONE_WEB_ADMIN_PASS` 필드 삭제. 남은 필드는 `EMAIL_MCP_HTTP_TOKEN`, `RCLONE_MCP_TOKEN`, `RCLONE_RC_PASS` |

S3를 브라우저로 다뤄야 하면 사람이 직접 쓰는 도구로 해결한다. 로컬 `rclone`, Garage는 `garage-webui`(OMV), Hetzner·AWS는 각 콘솔을 쓴다. 클러스터에는 UI를 두지 않는다.

---

## 계획: rclone·rclone-mcp 클러스터 제거 (2026-11-03, 미실행)

클러스터의 rclone과 rclone-mcp를 쓰지 않기로 했다. Bifrost `rclone` 서버와 `rclone-system`을 모두 걷어낸다. **email-mcp와 로컬 `rclone` CLI는 그대로 둔다.**

### 제거 대상

| 위치 | 대상 | 방법 |
|---|---|---|
| Bifrost (config store, GitOps 밖) | Virtual MCP `dev`(id 2)·`personal`(id 4)의 `rclone` 연결 | 관리자 API `PUT /api/mcp/virtual-mcps/{id}`에서 `tools`에서 뺀다 |
| | MCP 클라이언트 `rclone`(현재 id `7f625574-…`) | `DELETE /api/mcp/client/{id}` |
| 저장소 | `apps/base/rclone/` 전체(8개 파일) | `git rm -r` |
| | `apps/overlays/production/rclone.yaml` | `git rm` |
| | `apps/overlays/production/kustomization.yaml`의 `- rclone.yaml` | 줄 삭제 |
| | `apps/base/bifrost/bifrost.cilium-network-policy.yaml`의 rclone egress 블록 | 블록 삭제 |
| 클러스터 | Kustomization `rclone-production`, namespace `rclone-system`(Deployment, Service, SealedSecret, ConfigMap, CNP), `traefik-system/route-rclone` | overlay에서 빠지면 `apps` Kustomization이 prune한다. `rclone-production`이 사라지면서 그 하위 리소스도 prune된다 |
| Bitwarden `344e14cc-…` | 필드 `RCLONE_MCP_TOKEN`, `RCLONE_RC_PASS` | 필드 삭제. 항목 이름 `bifrost-mcp (homelab secrets)`과 `EMAIL_MCP_HTTP_TOKEN`은 그대로 둔다 |

남기는 것:
- **S3 키 원본**(로컬 `secrets.zsh`)과 로컬 `rclone.conf`. 로컬 rclone이 계속 쓴다.
- **Garage 키 `GK45d4…`의 `--create-bucket` 권한.** 로컬 rclone도 같은 키를 쓴다. 회수하려면 `garage key deny --create-bucket GK45d4…`를 실행한다(선택, 아래 확인 사항).
- **에이전트 지침·스킬.** Bifrost `rclone`을 언급하는 곳이 없어 고칠 것이 없다(`~/.agents` 검색 결과 0건).

### 실행 단계

1. **Bifrost 정리(먼저)**: 클러스터 서버를 지우기 전에 연결을 끊는다. 그래야 Bifrost에 unhealthy 클라이언트와 재연결 오류가 남지 않는다.
   - Virtual MCP `dev`·`personal`에서 `rclone`을 뺀다. 응답의 `virtual_key_ids`가 그대로인지 확인한다.
   - 클라이언트 `rclone`을 삭제한다.
   - `GET /api/mcp/clients?limit=100`에 `rclone`이 없는지 본다. 새 세션의 `listToolFiles`에서 `rclone.pyi`가 사라졌는지도 본다.
2. **매니페스트 제거**: 위 표의 저장소 항목을 처리한다.
3. **검증(로컬)**
   - `kubectl kustomize ./apps/overlays/production`과 `kubectl kustomize ./apps/base/bifrost`를 실행한다.
   - `rg -n rclone apps infrastructure`에 남는 것이 `email-mcp.config.toml` 주석(계획 문서 이름)뿐인지 확인한다.
4. **커밋·배포**: `feat(rclone): remove rclone and rclone-mcp from the cluster`. push 후 `flux reconcile kustomization apps`를 실행한다.
5. **검증(클러스터)**
   - `kubectl --context homelab -n flux-system get kustomization rclone-production`이 NotFound인지 본다.
   - `kubectl --context homelab get ns rclone-system`이 NotFound(Terminating 후 삭제)인지 본다.
   - `kubectl --context homelab -n traefik-system get cnp route-rclone`이 NotFound인지 본다.
   - Bifrost pod 로그에 rclone 관련 연결 오류가 없는지 본다.
   - 회귀 확인: Bifrost `email.list_accounts()`가 정상인지 본다. bifrost CNP가 바뀌었으므로 다른 MCP 하나(`gcp_personal` 등)도 호출해 본다.
6. **정리**
   - Bitwarden 필드 2개를 삭제한다(검증이 끝난 뒤, 되돌리기 대비로 마지막에).
   - 이 문서에 실행 결과를 기록한다.

### 되돌리기

- 매니페스트: `git revert` 후 reconcile하면 `9a45471` 상태로 돌아간다. SealedSecret은 같은 클러스터 키로 봉인돼 있어 그대로 복호화된다.
- Bifrost: 클라이언트를 재등록하고 Virtual MCP 두 곳에 다시 연결한다. 등록에는 `RCLONE_MCP_TOKEN`이 필요하므로 Bitwarden 필드 삭제를 마지막에 둔다.

### 실행 전 확인할 것

- Garage 키의 버킷 생성 권한을 회수할지(로컬 rclone에서도 버킷을 못 만들게 된다).
