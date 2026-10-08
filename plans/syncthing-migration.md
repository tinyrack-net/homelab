# Plan: Syncthing 클러스터 배포 (OMV 인스턴스 대체)

## Context

OpenMediaVault 호스트(`10.132.245.8`)의 Docker 컨테이너로 운영하던 Syncthing을
`production` 클러스터로 옮긴다. 기기 26개 항목 / 12대 연결 설정을 다시 페어링하지
않도록 **OMV 컨테이너의 config(설정·device ID·인증서)와 폴더 데이터를 그대로
복사**하며, 복사가 끝날 때까지 클러스터의 Syncthing은 `replicas: 0`으로 잠가 둔다.

## 구성

| 계층 | 위치 | 내용 |
|---|---|---|
| 데이터 | `apps/base/syncthing/storage` | StorageClass `syncthing-juicefs`, PVC `syncthing-data` (1Ti RWX, Garage 버킷 `tinyrack-homelab-syncthing-storage`) |
| 설정 | `apps/base/syncthing/app` | PVC `syncthing-home` (Longhorn 10Gi) — config·cert·index |
| 메타데이터 | `apps/base/syncthing/database` | CNPG `syncthing-database-cluster` (PG18 1 instance) + `Database`(`juicefs` 스키마) + Barman `ObjectStore`(30d, 4시간 `ScheduledBackup`) |
| 네트워크 | `apps/base/syncthing/app` | macvlan `syncthing-lan` `10.132.246.251/22` (LAN 직결 22000/21027), 내부 Traefik IngressRoute `syncthing.intranet.winetree94.com` |
| 정책 | `apps/base/syncthing/*` | `app-syncthing`, `route-syncthing`, `database-syncthing` CiliumNetworkPolicy |

- LB IP 풀은 `10.132.246.250`에서 멈춘다(`cilium-load-balancer`). `.251` 이상은
  macvlan 정적 Pod 주소용으로 남긴다. 기존 LB IP`.1/.2/.3/.5`는 변하지 않는다.
- JuiceFS mount pod 프로필 `storage.tinyrack.net/profile: syncthing`은
  `infrastructure/base/juicefs/values.yaml`의 `mountPodPatch`에 정의한다
  (cache 50Gi, free-space-ratio 0.2, max-uploads 2, GOMEMLIMIT 1600MiB).
- Flux Kustomization 3개(`syncthing-database` → `syncthing-storage` →
  `syncthing-deployment`)로 분리해 **DB와 `juicefs` 스키마가 준비된 뒤에만**
  JuiceFS 볼륨을 포맷하도록 순서를 고정한다.

## 비밀

`bw` 항목 `Kubernetes Secrets (Homelab)` (id `192c82cd-8e3e-4cb9-be46-b39001022d61`)
에 hidden 필드로 기록돼 있다. 저장소에는 SealedSecret만 커밋한다.

- `syncthing-database-password` → `syncthing-database-user-secret`
- `syncthing-garage-access-key`, `syncthing-garage-secret-key` → `syncthing-juicefs-secret`

Garage 버킷/키는 `openmediavault`의 `garage-garaged-1` 컨테이너에서 발급했다
(bucket `tinyrack-homelab-syncthing-storage`, key `syncthing-juicefs`, RWO).

## 마이그레이션 절차

1. Flux가 `syncthing-database`를 적용해 CNPG가 healthy하고 `juicefs` 스키마가
   생성될 때까지 기다린다. 그다음 `syncthing-storage`, `syncthing-deployment`가
   순서대로 적용된다.
2. 두 PVC(`syncthing-home`, `syncthing-data`)가 Bound인지 확인한다.
3. **사용자가 OMV UI에서 Syncthing 서비스를 중지한다.** 같은 device ID가 두 곳에서
   동시에 돌면 안 된다.
4. 임시 Pod으로 OMV `/config` → `syncthing-home`(`/var/syncthing/config`),
   OMV `/data/Obsidian` → `syncthing-data`(`/data/Obsidian`)로 복사하고
   `chown -R 1000:100` 한다.
5. `apps/base/syncthing/app/syncthing.deployment.yaml`의 `replicas`를 `1`로 바꿔
   커밋한다.
6. 기기 12대가 재연결되고 `Obsidian` 폴더가 Up to Date가 되면 OMV UI에서 서비스를
   제거한다. **(남은 작업: OMV UI에서 서비스 제거만 남음)**

## 검증

```bash
kubectl --context homelab -n syncthing-system get pods,pvc,ingressroute
kubectl --context homelab -n syncthing-system get cluster,databases.postgresql.cnpg.io
kubectl --context homelab -n syncthing-system get backups.postgresql.cnpg.io
kubectl --context homelab -n syncthing-system port-forward svc/syncthing 8080:8384  # http://localhost:8080
```

- Pod readiness: `/rest/noauth/health`
- JuiceFS mount pod 로그에서 format/원격 저장소 접속 성공 확인, Garage 버킷에
  오브젝트가 생기는지 확인
- LAN 기기에서 `10.132.246.251` ping 및 22000 직결(relay 아님) 확인
- CNPG `Backup` 1회 Ready, JuiceFS quota 1Ti 반영 확인

## 주의

- `syncthing-data`는 JuiceFS(네트워크 파일시스템)이므로 Syncthing의 파일 감시자가
  완전하지 않다. OMV와 동일하게 **주기 스캔 폴백**을 전제로 한다.
- macvlan 구간은 Cilium 정책이 적용되지 않아 OMV와 같은 LAN 노출 수준을 유지한다.
- Syncthing egress는 앱 정책에서 DNS, LAN 전체, `world` TCP 443·22067(TCP/UDP QUIC)을
  열고, 네임스페이스 공통 격리 정책이 내부 대역을 제외한 공인 egress를 함께
  허용한다(정책은 additive). 따라서 LAN·공인망 피어 모두 22000 직결이 가능하고,
  `lan` CIDR group 같은 내부 대역은 열어 둔 포트만 통과한다.
- OMV나 CNPG가 죽으면 동기화 데이터에 접근할 수 없다. 복구는 Garage 객체와
  CNPG Barman 백업을 함께 복원해야 한다.

## 완료 기록 (2026-10-08)

- 사용자가 OMV UI에서 `syncthing` 컨테이너를 중지(`Exited (0)`)한 뒤 마이그레이션을
  수행했다. 복사는 임시 Pod으로 tar를 스트리밍해 중간 평문 저장 없이 옮겼다.
- `/config` → `syncthing-home`(`/var/syncthing/config`): `config.xml` sha256 일치,
  `cert.pem`·`key.pem`·`https-*.pem`·`index-v2` 포함.
- `/data/Obsidian` → `syncthing-data`(`/data/Obsidian`): 943 files / 216 dirs /
  117,989,361 bytes로 원본과 일치. `.stfolder` 마커와 `.stignore`도 함께 복사됐다.
- `replicas: 1`로 전환 후 검증:
  - device ID `XPIMBVJ-PQPJGOH-IIOFHXK-I3GHSS3-3QPCG3H-ROWF3RC-AUVIQCG-QSWJSQ2`
    (OMV 원본과 동일, 재페어링 없음)
  - 폴더 `lqgdq-zq5vo` `Obsidian`: `state=idle`, `needFiles=0`, `errors=0` → Up to Date
  - `localFiles=163` vs `globalFiles=224` 차이는 `.stversions`(763 files)와
    `.obsidian/syncthing-ignore.txt` ignore 목록 때문이며 정상이다.
  - 피어 5/11 접속: LAN 3대는 `22000/tcp` 직결, 공인망 2대는 relay(`22067`).
  - 신규 파일 1건 생성 시 5초 내 LAN 피어로 전송됨(`needItems` 67→68→67).
  - 내부 Traefik: `https://syncthing.intranet.winetree94.com/rest/noauth/health` 200,
    미인증 `/rest/system/status` 403(기존 GUI 계정 유지), macvlan `10.132.246.251`
    ping/22000/8384 응답.
