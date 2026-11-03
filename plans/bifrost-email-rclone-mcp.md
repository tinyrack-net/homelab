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

- **Garage 키 `GK45d4…`에는 버킷 생성 권한이 없다**(`not allowed to create buckets`). `homelab_garage`에서 버킷을 만들려면 Garage에서 `garage key allow --create-bucket <key>`를 실행해야 한다. 기존 버킷 안의 객체는 읽고 쓸 수 있다.
- **Hetzner는 버킷 생성·삭제가 eventual consistency다.** `mkdir` 직후 PutObject를 하면 `NoSuchBucket`이 나고, `purge` 직후 목록에는 버킷이 잠시 남아 있다. 10–20초 뒤에는 정상이다.
- rclone-mcp에는 health endpoint가 없다(`/mcp` 이외는 404). 그래서 tcpSocket probe를 쓴다.
- `rclone rcd`는 `RCLONE_RC_PASS`를 환경변수에서 읽는다. 그래서 args에 비밀번호를 넣지 않는다.
- email-mcp 0.6.0 스키마에는 계정별 `save_to_sent`/`sent_mailbox`가 없다(main 브랜치에만 있다). 전역 `save_to_sent=false`가 기본이다. Stalwart는 서버가 보낸 메일함에 사본을 저장하지 않으므로, MCP로 보낸 메일은 Sent 폴더에 남지 않는다.
- email-mcp 계정 이름에 `@`이 들어가도 동작한다(himalaya 이름과 같다).
- Bifrost `GET /api/mcp/clients`는 기본 `limit=25`로 페이지를 나눈다. 전체를 보려면 `?limit=100`을 붙인다.
- 남은 일: `email-management` 스킬 등 에이전트 지침에 Bifrost `email`·`rclone` 서버 사용법을 반영할지 정한다.
