# Bifrost 메인 LLM 게이트웨이 전환 계획

상태: 전환 및 검증 완료 (2026-10-31).

## 목표

- Bifrost를 메인 LLM·MCP 게이트웨이로 운영한다.
- Bifrost 외부 주소: `llm.winetree94.com`
- Bifrost 내부 관리 주소: `llm.intranet.winetree94.com`
- CLIProxyAPI는 OAuth 모델용 보조 upstream으로 축소한다.
- CLIProxyAPI 관리 주소는 `cliproxyapi.intranet.winetree94.com`만 유지하고 외부 공개를 제거한다.
- 기존 CLIProxyAPI 데이터·OAuth 자격증명과 Bifrost 설정·MCP 연결을 보존한다.

## 조사 시점의 현황

실제 전환 직전에 다시 확인한다. 실행 설정은 Git 초기 설정과 다를 수 있다.

### Bifrost

- 매니페스트: `apps/base/bifrost/`
- Flux: `apps/overlays/production/bifrost.yaml`
- 내부 주소: `mcp.intranet.winetree94.com` — 관리 UI·전체 API
- 외부 주소: `mcp.winetree94.com` — `/mcp*`, `/v1*`, `/health`
- StatefulSet 1개, 정상 동작.
- 10Gi PVC에 SQLite 설정 DB·로그 DB 저장. WAL 사용 중.
- 공식 Node·Astral initContainer에서 npx·uvx 런타임 주입.
- LLM provider: `deepseek`, `opencode-go`
- 관리자 인증 활성화, Virtual Key `dev` 1개.
- MCP 서버 9개, 도구 205개 조회됨.
- 실행 설정의 `mcp_disable_auto_tool_inject=false`.
- ConfigMap의 config.json은 PVC에 파일이 없을 때만 복사된다. ConfigMap 수정만으로 기존 실행 설정에 반영되지 않는다.
- 현재 매니페스트에 정기 SQLite 백업 구성은 확인되지 않았다.

### CLIProxyAPI

- 매니페스트: `apps/base/cliproxyapi/`
- Flux: `apps/overlays/production/cliproxyapi.yaml`
- 내부 주소: `llm.intranet.winetree94.com` — 관리 UI·전체 API
- 외부 주소: `llm.winetree94.com` — 관리 경로를 제외하고 공개
- 앱·usage exporter 정상, CNPG 정상.
- PostgreSQL 및 S3 정기 백업 구성.
- API 키 1개.
- OAuth 인증 파일 11개: Antigravity 4개, Claude 6개, Codex 1개.
- OAuth 상태: active 5개, error 6개. 기존 오류를 전환 장애와 구분해야 한다.
- 일반 API upstream: DeepSeek, OpenCode Go, 홈랩 Qwen.
- 실행 설정은 `request-retry: 10`으로 Git bootstrap 값과 다르다.
- usage exporter를 통한 기존 메트릭 수집 유지 중.

### DNS·소비자

- Cloudflare에 `llm.winetree94.com`, `mcp.winetree94.com`의 DNS·Tunnel 경로가 모두 존재한다.
- 내부 DNS에서 `llm.winetree94.com`은 외부 Traefik 내부 주소로 해석된다.
- `llm.intranet.winetree94.com`, `mcp.intranet.winetree94.com`, `cliproxyapi.intranet.winetree94.com`은 내부 Traefik 주소로 해석된다.
- Pi의 다음 파일에서 기존 `https://llm.winetree94.com` 사용 확인:
  - `~/.config/pi/agent/cliproxyapi.json`
  - `~/.config/pi/agent/auth.json`
  - `~/.config/pi/agent/cliproxyapi-models.json`
- Pi 모델 캐시 53개. `/backend-api/` 및 CLIProxyAPI 모델 조회 경로도 참조한다.
- Open WebUI Deployment에는 기본 OpenAI URL이 보인다. DB에 저장된 UI 설정 등 다른 소비자는 추가 확인이 필요하다.
- 기존 CLIProxyAPI API 키·모델 ID·전용 경로는 Bifrost에서 자동 호환되지 않는다.

## 목표 구조

```text
클라이언트
  └─ Bifrost
       ├─ llm.winetree94.com           외부 추론·MCP API
       ├─ llm.intranet.winetree94.com  내부 관리 UI·전체 API
       ├─ DeepSeek API                직접 연결
       ├─ OpenCode Go API             직접 연결
       ├─ 홈랩 Qwen                   직접 연결
       └─ CLIProxyAPI                 OAuth 모델 전용 upstream
            ├─ cliproxyapi.intranet.winetree94.com  내부 관리
            ├─ Claude OAuth
            ├─ Codex OAuth
            └─ Antigravity OAuth
```

Bifrost → CLIProxyAPI는 다음 클러스터 내부 Service를 권장한다.

```text
http://cliproxyapi-service.cliproxyapi-system.svc.cluster.local:8317/v1
```

관리자는 내부 호스트명으로 접속하고 서비스 간 통신은 DNS·Traefik에 불필요하게 의존하지 않는다.

## 실행 계획

### 1. 전환 전 백업·기준 상태 기록

- [x] Git 변경 사항과 Flux 상태를 확인한다.
- [x] Bifrost 설정·로그 DB를 일관성 있게 백업한다. 실행 중인 SQLite 파일만 단순 복사하지 않는다. SQLite 온라인 백업 또는 정지 후 DB·WAL 처리 등 검증된 방식을 사용한다.
- [x] CLIProxyAPI 실행 설정·모델 목록·자격증명 상태를 기록한다.
- [x] PostgreSQL 최근 백업과 복구 가능성을 확인한다.
- [x] OAuth error 6개를 원인별로 분류하고 기준 상태를 남긴다.
- [x] 비밀값은 로그·계획 문서·Git에 출력하지 않는다.

### 2. CLIProxyAPI 새 내부 주소 추가

- [x] `cliproxyapi.intranet.winetree94.com` 내부 IngressRoute를 추가한다.
- [x] 관리 UI·모델 목록·OAuth 인증 절차를 확인한다.
- [x] OAuth callback에 이전 호스트명이 쓰이는지 확인한다.
- [x] 이 단계에서는 기존 llm 주소를 유지한다.

### 3. Bifrost upstream 준비

- [x] 기존 `deepseek`, `opencode-go`의 모델·키·호출 성공을 확인한다. 등록 여부만으로 정상으로 판단하지 않는다.
- [x] 홈랩 Qwen을 Bifrost에 직접 등록한다.
- [x] CLIProxyAPI를 OpenAI 호환 custom provider로 등록한다.
- [x] CLIProxyAPI API 키를 upstream 자격증명으로 사용한다. 사용자 클라이언트는 Bifrost Virtual Key를 사용하도록 분리한다.
- [x] provider별 모델 ID·별칭·라우팅을 정의하고 `/v1/models` 결과를 검증한다.
- [x] 스트리밍·tool calling·Responses API 등 실제 소비자에 필요한 호환성을 확인한다.
- [x] Bifrost와 CLIProxyAPI의 이중 재시도로 대기 시간이 폭증하지 않도록 timeout·retry 책임을 분리한다.
- [x] 일반 LLM 요청에 MCP 도구가 의도치 않게 자동 주입되지 않도록 정책을 정한다.
- [x] 일반 API upstream은 Bifrost 직결 검증 후에만 CLIProxyAPI에서 제거한다.

### 4. 네트워크 정책

- [x] Bifrost → CLIProxyAPI TCP 8317 egress 및 상대 ingress를 최소 권한으로 허용한다.
- [x] Bifrost → 홈랩 모델 서버의 필요한 포트만 허용한다.
- [x] 기존 MCP 내부망 접근 정책을 보존한다.
- [x] 주소 전환 시 CLIProxyAPI의 외부 Traefik 인입·route 정책을 제거한다.
- [x] 내부 관리용 Traefik·모니터링·DB·백업 통신을 유지한다.

### 5. 주소 소유권 전환

- [x] CLIProxyAPI에서 기존 llm 호스트 라우트를 제거한다.
- [x] Bifrost에 `llm.winetree94.com`, `llm.intranet.winetree94.com` 라우트를 연결한다.
- [x] 동일 호스트·경로를 두 서비스가 동시에 소유하지 않도록 커밋·reconcile 순서를 관리한다.
- [x] 외부는 필요한 추론·MCP 경로만 허용하고 관리 UI·관리 API는 차단한다.
- [x] `/v1`, `/mcp` 등의 정확한 경로 경계를 사용한다. 느슨한 `PathPrefix('/v1')`만으로 유사 경로까지 허용하지 않는다.
- [x] OpenAI·Anthropic 등 필요한 호환 API 경로를 실제 배포 버전 기준으로 확인한다. 내부 API 전체를 외부에 열지 않는다.
- [x] 기존 Cloudflare llm DNS·Tunnel 경로를 재사용한다.
- [x] 기존 mcp 주소 소비자를 확인한다. 필요하면 일시적으로 동일 서비스 별칭을 유지한 뒤 제거한다. MCP 클라이언트에 HTTP 리다이렉트를 강요하지 않는다.
- [x] 최종적으로 기존 mcp DNS·Tunnel·IngressRoute를 정리한다.
- [x] 현재 와일드카드 인증서가 새 호스트들을 포함하는지 검증한다.

### 6. 소비자·운영 전환

- [x] Pi 키를 Bifrost Virtual Key로 전환한다.
- [x] Pi 모델 캐시·모델 ID·CLIProxyAPI 전용 모델 조회 경로를 교체한다.
- [x] 확인 가능한 다른 소비자와 DB 저장 설정을 조사하고 전환한다.
- [x] Bifrost MCP 외부 URL·허용 Origin·필요한 callback 주소를 갱신한다.
- [x] PVC에 저장된 실행 설정은 API 또는 지원되는 관리 절차로 갱신한다. Git ConfigMap만 수정하고 끝내지 않는다.
- [x] Bitwarden 관리 URL과 관련 운영 문서 링크를 갱신한다.
- [x] CLIProxyAPI usage exporter는 OAuth upstream 관측용으로 유지한다.
- [x] Bifrost 전체 트래픽의 메트릭·로그와 정기 백업을 보강한다.
- [x] 기존 Virtual MCP 구성은 별도 요구가 없으면 변경하지 않는다.

## 검증·완료 기준

- [x] `kubectl --context homelab kustomize ./apps/base/bifrost`
- [x] `kubectl --context homelab kustomize ./apps/base/cliproxyapi`
- [x] `kubectl --context homelab kustomize ./apps/overlays/production`
- [x] `kubectl --context homelab kustomize ./infrastructure/overlays/production`
- [x] 내부 llm 주소에서 Bifrost 로그인·관리 정상.
- [x] 외부 llm 주소에서 관리 UI·API 접근 불가.
- [x] 잘못된 키 또는 키 없는 추론·MCP 요청 거부.
- [x] DeepSeek·OpenCode Go·Qwen·OAuth 모델 각각 실제 추론 성공.
- [x] 스트리밍·도구 호출·Responses API 등 필요한 기능 정상.
- [x] 기존 MCP 9개 연결과 도구 목록 유지.
- [x] CLIProxyAPI는 새 내부 주소에서만 관리 가능.
- [x] Pi 모델 조회·추론 정상.
- [x] Cloudflare 경유와 내부 DNS 우회 경로 모두 검증.
- [x] 재시작 후 Bifrost 설정·키·MCP 연결 유지.
- [x] 백업과 복구 절차 확인.

## 롤백

- 주소 전환 전 Bifrost·CLIProxyAPI 설정 백업과 Git 리비전을 기록한다.
- 전환 실패 시 llm 라우트를 기존 CLIProxyAPI로 복구하고 Pi 인증·모델 설정을 원복한다.
- 필요하면 Bifrost의 기존 mcp 주소 별칭을 복구한다.
- Cloudflare·DNS 변경은 Git 롤백과 별개이므로 따로 원복한다.
- 직접 API 변경한 provider·실행 설정 역시 Git 롤백만으로 복원되지 않으므로 별도 기록·복구한다.
- 일반 API upstream은 검증 전 삭제하지 않아 롤백 경로를 보존한다.

## 주요 변경 대상

- `apps/base/bifrost/bifrost.ingress-route.yaml`
- `apps/base/bifrost/bifrost.cilium-network-policy.yaml`
- `apps/base/bifrost/bifrost.configmap.yaml` 및 PVC의 실제 실행 설정
- 필요 시 Bifrost 저장소·백업·모니터링 리소스
- `apps/base/cliproxyapi/cliproxyapi.ingress-route.yaml`
- `apps/base/cliproxyapi/cliproxyapi.cilium-network-policy.yaml`
- CLIProxyAPI PostgreSQL에 저장된 실제 upstream 설정
- Cloudflare DNS·Tunnel
- Pi 및 다른 소비자의 키·모델·접속 설정

## 비밀 관리

- Bifrost 관리자·암호화 키 Bitwarden 항목 ID: `34757a54-9c7e-4867-ae3d-b4f30110b528`
- Kubernetes 비밀은 기존 SealedSecret 패턴을 유지한다.
- 문서에는 토큰·비밀번호·공인 IP를 기록하지 않는다.
