# Homelab K3s Ansible

Ubuntu Server 24.04 amd64 단일 노드에 homelab K3s 서버를 구성하고 검증한다. Inventory는 로컬 SSH
설정의 `homelab` 별칭을 사용하며, 현재 K3s와 Flux가 동작하는 기존 서버는 변경하지 않는다.

## 준비

저장소에 포함되지 않는 `.vault_pass`는 최초 구성 시 `openssl rand -hex 48`로 생성된다. 파일 권한은
`0600`이며, 이 파일을 잃으면 커밋된 Vault를 복호화할 수 없다. become 비밀번호는 암호화된 Vault에서
자리표시자로 시작하므로 실제 값을 먼저 입력한다.

```bash
cd ansible
make vault-edit
```

편집기에서 아래 두 자리표시자를 실제 값으로 교체한다. 개인 키는 PEM의 BEGIN/END 줄을 포함한 전체
내용을 YAML block scalar 안에 들여쓰기해 넣는다. 공개 인증서는 저장소 루트에 커밋된
`tinyrack-homelab-secret-key.crt`를 사용한다.

```yaml
vault_homelab_become_password: "CHANGE_ME"
vault_sealed_secrets_tls_key: |-
  -----BEGIN PRIVATE KEY-----
  ...
  -----END PRIVATE KEY-----
```

비밀번호와 TLS 개인 키를 셸 인자, 명령 기록 또는 평문 파일에 넣지 않는다. `make preflight`는 Vault의
개인 키가 커밋된 인증서와 짝이 맞는지 메모리 안에서 검증한다.

## 사용법

먼저 연결과 구성을 검증하고 check mode의 변경 내용을 확인한 뒤 적용한다.

```bash
make ping
make syntax
make lint
make preflight
make check
make apply
make apply  # changed=0인지 확인
make verify
```

`make apply`는 Ubuntu 24.04 amd64를 확인하고 Longhorn 필수 패키지와 iSCSI를 구성한 뒤 K3s
`v1.36.4+k3s1`을 설치한다. Pod CIDR은 `10.61.0.0/16`, Service CIDR은 `10.62.0.0/16`이며 기본
Traefik과 ServiceLB는 비활성화한다. `/etc/sysctl.d/90-k3s-inotify.conf`에서 inotify instance 8192개,
watch 1048576개, queue event 32768개를 영구 관리한다. K3s 노드가 Ready가 되면 커밋된 인증서와 Vault의
개인 키를 원격 임시 파일 없이 `sealed-secrets/sealed-secrets-key` Secret으로 복원하고 active key
label을 설정한다.

`make verify`까지 성공한 뒤 저장소 루트에서 Flux를 bootstrap한다. Flux bootstrap은 Ansible 범위에
포함하지 않는다.

```bash
cd ..
flux bootstrap github \
  --repository=homelab \
  --branch=main \
  --path=./clusters/production \
  --owner=tinyrack-net
```

OS 전체 업그레이드와 재부팅은 수행하지 않는다.

특정 호스트나 추가 Ansible 인자를 넘길 때는 다음처럼 사용한다.

```bash
make check ANSIBLE_ARGS="--limit homelab"
```
