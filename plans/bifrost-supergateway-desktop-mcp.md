# Plan: Bifrost에 desktop·mbp의 cua-driver·marionette MCP 등록 (supergateway) — 운영 중 (2026-11-04)

## Context

`cua-driver`(데스크톱 자동화)와 `marionette_mcp`(Flutter 앱 조작)는 그 기기의 GUI 세션에서만 동작하는 stdio MCP 서버다. 지금까지는 각 에이전트(pi, Codex CLI, opencode, Antigravity CLI)가 기기마다 로컬 stdio로 띄웠다.

이 두 서버를 각 기기에서 [supergateway](https://www.npmjs.com/package/supergateway)로 HTTP로 노출하고, Bifrost에 등록한다. 에이전트는 어느 기기에서든 Bifrost 하나만 연결하면 두 기기의 서버를 모두 쓸 수 있다.

### 확정된 결정

| # | 항목 | 결정 |
|---|------|------|
| 1 | 인증 | 없음. LAN 안에서만 쓰므로 supergateway `--apiKey`와 호스트 방화벽 제한을 두지 않는다. Bifrost 쪽 egress는 Cilium으로 두 호스트의 두 포트만 연다 |
| 2 | Bifrost 서버 이름 | `marionette_desktop`, `cua_driver_desktop`, `marionette_mbp`, `cua_driver_mbp` |
| 3 | 호스트 IP | 두 기기 모두 OPNsense DHCP 예약으로 고정. desktop `10.132.247.31`, mbp `10.132.247.35` |
| 4 | 로컬 stdio 설정 | 모든 에이전트 설정에서 제거한다 |
| 5 | 동시 사용 | 혼자 쓴다. stateful 세션마다 자식 프로세스가 따로 뜨므로 marionette 연결 상태는 Bifrost 세션 단위로 유지된다 |

---

## 아키텍처

```
bifrost-system / bifrost ──(http, no auth)──┬─► desktop 10.132.247.31
                                             │     :18100/mcp  supergateway → marionette_mcp.bat
                                             │     :18101/mcp  supergateway → cua-driver.exe mcp
                                             └─► mbp 10.132.247.35
                                                   :18100/mcp  supergateway → marionette_mcp
                                                   :18101/mcp  supergateway → cua-driver mcp (CuaDriver.app 데몬에 붙음)
```

- 출력 transport는 **stateful Streamable HTTP**다(`--outputTransport streamableHttp --stateful`, 경로 `/mcp`).
- SSE 출력은 쓰지 않는다. Bifrost는 연결할 때 `server/discover`를 먼저 보낸다. supergateway 4.2 SSE 모드는 첫 메시지가 `initialize`가 아니면 자식을 직접 initialize한다. 그 뒤 Bifrost가 보내는 `initialize`를 `marionette_mcp`는 `Received duplicate initialize request`로 거부한다. cua-driver는 SSE로도 붙지만 두 서버의 방식을 맞춘다.
- Streamable HTTP stateful 모드는 세션 ID 없는 `server/discover`에 400을 돌려준다. 그러면 Bifrost는 일반 `initialize`로 넘어간다.

---

## 기기별 구성

supergateway는 `npx -y`를 쓰지 않는다. 부팅할 때 npm에 의존하지 않도록 기기별 전용 디렉터리에 `supergateway@4.2.1`을 고정 설치한다. 업그레이드도 이 디렉터리에서 `npm install --prefix <dir> supergateway@<ver>`로 한다.

### desktop (Windows)

| 항목 | 위치 |
|------|------|
| supergateway | `%LOCALAPPDATA%\supergateway\app` |
| 런처 | `%USERPROFILE%\.config\supergateway\launcher.ps1` (`-Name -Port -Stdio`, 종료되면 10초 뒤 재시작, 로그 10MB에서 교체) |
| 작업 등록 스크립트 | `%USERPROFILE%\.config\supergateway\register-tasks.ps1` (다시 실행하면 갱신된다) |
| 작업 스케줄러 | `Supergateway-marionette`, `Supergateway-cua-driver`. 로그온 트리거, Interactive, Limited, `conhost --headless`로 창 없이 실행 |
| 로그 | `%LOCALAPPDATA%\supergateway\logs\<name>.log` |

- 데스크톱 GUI를 조작해야 하므로 세션 0("로그온 여부와 관계없이 실행")으로 돌리지 않는다.
- 포트 8000은 `OpenTerminal`(open-terminal)이 쓴다.
- 방화벽은 기존 `node.exe` 인바운드 허용 규칙으로 열려 있다. 따로 규칙을 추가하지 않았다.
- 같은 기기의 WSL에서는 `10.132.247.31`로 접속할 수 없다. WSL에서 테스트할 때는 `localhost:18100`을 쓴다.

### mbp (macOS)

| 항목 | 위치 |
|------|------|
| supergateway | `~/.local/share/supergateway/app` |
| 런처 | `~/.local/share/supergateway/launcher.sh <port> <stdio command>`. PATH에 mise의 `node/24`, `dart/latest`, `flutter/latest` 별칭을 넣는다 |
| LaunchAgent | `~/Library/LaunchAgents/net.tinyrack.supergateway.{marionette,cua-driver}.plist`. `RunAtLoad`, `KeepAlive`, `ThrottleInterval 10`, `ProcessType Interactive` |
| 로그 | `~/Library/Logs/supergateway/<name>.log` |

- GUI 세션 권한이 필요하므로 LaunchDaemon이 아닌 LaunchAgent로 만든다. `cua-driver mcp`는 이미 떠 있는 CuaDriver.app 데몬에 붙으므로, 그 앱이 받은 손쉬운 사용·화면 기록 권한을 그대로 쓴다.
- 재시작: `launchctl kickstart -k gui/$(id -u)/net.tinyrack.supergateway.<name>`

---

## 저장소 변경

- `infrastructure/base/network-security/hosts.cilium-cidr-group.yaml`: `mbp` CIDR 그룹(`10.132.247.35/32`)을 추가했다. `desktop`은 이미 있었다.
- `apps/base/bifrost/bifrost.cilium-network-policy.yaml`: `desktop`·`mbp`로 가는 TCP 18100–18101 egress를 추가했다.

## Bifrost (config store, GitOps 밖)

- 관리자 API `POST /api/mcp/client`로 4개를 등록했다. 설정은 `connection_type=http`, `connection_string=http://<host>:<port>/mcp`, `auth_type=none`, code mode, `tools_to_execute=["*"]`이다.
- Virtual MCP `dev`(id 2)·`personal`(id 4)에 4개를 연결했다(`PUT /api/mcp/virtual-mcps/{id}`). 회사용 `vivident_admin`에는 넣지 않았다.
- 파드 안의 `wget`은 BusyBox라 `--method`를 지원하지 않는다. 관리자 API는 파드 안 `/tools/bin/node`의 `fetch`로 호출한다. 인증은 `BIFROST_ADMIN_USERNAME`/`BIFROST_ADMIN_PASSWORD` 환경 변수로 Basic 헤더를 만든다.

## 로컬 에이전트 설정

WSL, Windows(`C:\Users\winetree94`), mbp 세 곳에서 `cua-driver`·`marionette` 항목을 지웠다. 원본은 `<file>.bak-20261104`로 남겼다.

- pi: `~/.config/pi/agent/mcp.json`
- opencode: `~/.config/opencode/opencode.jsonc`
- Antigravity CLI: `~/.gemini/config/mcp_config.json`
- Codex CLI: `~/.codex/config.toml`

---

## 검증 결과 (2026-11-04)

| 항목 | 결과 |
|------|------|
| 각 엔드포인트 initialize → tools/list | marionette 20개, cua-driver 59개(desktop 0.34.0), 60개(mbp 0.35.4) |
| bifrost-0 → 4개 엔드포인트 | Cilium 반영 후 연결된다 |
| Bifrost `executeToolCode` | `cua_driver_*.get_screen_size()` 정상. `marionette_*.get_logs()`는 앱 미연결 오류로 정상 응답 |
| 프로세스 강제 종료 | desktop은 런처 루프가 10초 뒤, mbp는 KeepAlive가 재시작한다 |
| 로그온 자동 시작 | 작업 스케줄러 로그온 트리거와 LaunchAgent `RunAtLoad`로 구성했다. 실제 재로그온 검증은 하지 않았다 |

## 운영 메모

- 기기 IP를 바꾸면 Cilium CIDR 그룹과 Bifrost 클라이언트 주소를 함께 바꾼다. Bifrost `connection_string`은 수정할 수 없어 삭제 후 재등록해야 한다. 재등록하면 Virtual MCP 연결도 다시 해야 한다.
- 상태 확인: desktop `Get-ScheduledTask Supergateway-*`, mbp `launchctl list | grep supergateway`.
