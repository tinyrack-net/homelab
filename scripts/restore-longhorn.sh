#!/usr/bin/env bash
set -euo pipefail

CONTEXT="homelab"
MODE="--check"
MAX_AGE_HOURS="13"
INVENTORY="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/recovery/volume-inventory.yaml"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --context)
      CONTEXT="$2"
      shift 2
      ;;
    --inventory)
      INVENTORY="$2"
      shift 2
      ;;
    --max-age-hours)
      MAX_AGE_HOURS="$2"
      shift 2
      ;;
    --check|--apply)
      MODE="$1"
      shift
      ;;
    *)
      printf 'usage: %s [--context CONTEXT] [--inventory FILE] [--max-age-hours HOURS] [--check|--apply]\n' "$0" >&2
      exit 2
      ;;
  esac
done

command -v kubectl >/dev/null || { printf 'kubectl is required\n' >&2; exit 1; }
command -v jq >/dev/null || { printf 'jq is required\n' >&2; exit 1; }
[ -r "$INVENTORY" ] || { printf 'inventory not found: %s\n' "$INVENTORY" >&2; exit 1; }
[[ "$MAX_AGE_HOURS" =~ ^[0-9]+$ ]] || { printf 'max age must be a non-negative integer\n' >&2; exit 2; }

inventory_rows() {
  awk '
    $1 == "-" && $2 == "namespace:" { namespace=$3 }
    $1 == "pvc:" { pvc=$2 }
    $1 == "targetVolume:" { target=$2 }
    $1 == "storageClass:" { print namespace "\t" pvc "\t" target "\t" $2 }
  ' "$INVENTORY"
}

backups_json="$(kubectl --context "$CONTEXT" -n longhorn-system get backups.longhorn.io -o json)"
backup_volumes_json="$(kubectl --context "$CONTEXT" -n longhorn-system get backupvolumes.longhorn.io -o json)"

declare -A latest_backups=()
while IFS=$'\t' read -r backup_key backup_json; do
  latest_backups["$backup_key"]="$backup_json"
done < <(jq -r '
  [.items[]
    | select(.status.state == "Completed")
    | . as $backup
    | (($backup.spec.labels.KubernetesStatus // "{}") | fromjson?) as $kubernetes
    | select($kubernetes.namespace != null and $kubernetes.pvcName != null)
    | {key: ($kubernetes.namespace + "/" + $kubernetes.pvcName), backup: $backup}]
  | sort_by(.key, .backup.status.snapshotCreatedAt)
  | group_by(.key)[]
  | last
  | [.key, (.backup | @base64)]
  | @tsv
' <<<"$backups_json")

restore_volume() {
  local namespace="$1" pvc="$2" target="$3" storage_class="$4" backup="$5"
  local backup_url source_volume backup_volume_size data_locality
  backup_url="$(jq -r '.status.url' <<<"$backup")"
  source_volume="$(jq -r '.status.volumeName' <<<"$backup")"
  backup_volume_size="$(jq -r --arg source "$source_volume" '[.items[] | select(.spec.volumeName==$source) | .status.size] | first // empty' <<<"$backup_volumes_json")"
  [ -n "$backup_volume_size" ] || { printf 'missing provisioned size for %s/%s\n' "$namespace" "$pvc" >&2; return 1; }
  data_locality="disabled"
  [ "$storage_class" = "longhorn-strict-local" ] && data_locality="strict-local"

  kubectl --context "$CONTEXT" get namespace "$namespace" >/dev/null 2>&1 || \
    kubectl --context "$CONTEXT" create namespace "$namespace"
  kubectl --context "$CONTEXT" -n "$namespace" get pvc "$pvc" >/dev/null 2>&1 && {
    printf 'refusing to overwrite existing PVC %s/%s\n' "$namespace" "$pvc" >&2
    return 1
  }
  kubectl --context "$CONTEXT" get pv "$target" >/dev/null 2>&1 && {
    printf 'refusing to overwrite existing PV %s\n' "$target" >&2
    return 1
  }
  kubectl --context "$CONTEXT" -n longhorn-system get volumes.longhorn.io "$target" >/dev/null 2>&1 && {
    printf 'refusing to overwrite existing Longhorn volume %s\n' "$target" >&2
    return 1
  }

  kubectl --context "$CONTEXT" apply -f - <<EOF
apiVersion: longhorn.io/v1beta2
kind: Volume
metadata:
  name: ${target}
  namespace: longhorn-system
spec:
  accessMode: rwo
  dataLocality: ${data_locality}
  frontend: blockdev
  fromBackup: ${backup_url}
  numberOfReplicas: 1
  size: "${backup_volume_size}"
EOF

  kubectl --context "$CONTEXT" -n longhorn-system wait --for=jsonpath='{.status.robustness}'=healthy \
    "volumes.longhorn.io/${target}" --timeout=30m

  kubectl --context "$CONTEXT" apply -f - <<EOF
apiVersion: v1
kind: PersistentVolume
metadata:
  name: ${target}
spec:
  accessModes:
    - ReadWriteOnce
  capacity:
    storage: ${backup_volume_size}
  csi:
    driver: driver.longhorn.io
    fsType: ext4
    volumeHandle: ${target}
  persistentVolumeReclaimPolicy: Retain
  storageClassName: ${storage_class}
  volumeMode: Filesystem
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: ${pvc}
  namespace: ${namespace}
  annotations:
    kustomize.toolkit.fluxcd.io/prune: disabled
  labels:
    recurring-job.longhorn.io/source: enabled
    recurring-job-group.longhorn.io/longhorn-backup: enabled
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: ${backup_volume_size}
  storageClassName: ${storage_class}
  volumeMode: Filesystem
  volumeName: ${target}
EOF
  kubectl --context "$CONTEXT" -n "$namespace" wait --for=jsonpath='{.status.phase}'=Bound "pvc/${pvc}" --timeout=5m
}

failures=0
inventory_count=0
now_epoch="$(date -u +%s)"
while IFS=$'\t' read -r namespace pvc target storage_class; do
  inventory_count=$((inventory_count + 1))
  backup_base64="${latest_backups["$namespace/$pvc"]:-}"
  backup=""
  [ -z "$backup_base64" ] || backup="$(base64 --decode <<<"$backup_base64")"
  if [ -z "$backup" ]; then
    printf 'FAIL no completed backup for %s/%s\n' "$namespace" "$pvc" >&2
    failures=$((failures + 1))
    continue
  fi
  created_at="$(jq -r '.status.snapshotCreatedAt' <<<"$backup")"
  created_epoch="$(date -u -d "$created_at" +%s)"
  age_hours=$(((now_epoch - created_epoch) / 3600))
  if [ "$age_hours" -gt "$MAX_AGE_HOURS" ]; then
    printf 'FAIL stale backup for %s/%s: age=%sh max=%sh\n' \
      "$namespace" "$pvc" "$age_hours" "$MAX_AGE_HOURS" >&2
    failures=$((failures + 1))
    continue
  fi
  printf 'OK   %s/%s backup=%s created=%s target=%s\n' \
    "$namespace" "$pvc" "$(jq -r '.metadata.name' <<<"$backup")" \
    "$created_at" "$target"
  if [ "$MODE" = "--apply" ]; then
    restore_volume "$namespace" "$pvc" "$target" "$storage_class" "$backup" || failures=$((failures + 1))
  fi
done < <(inventory_rows)

if [ "$inventory_count" -ne 10 ]; then
  printf 'Longhorn recovery inventory must contain exactly 10 volumes, found %s\n' "$inventory_count" >&2
  exit 1
fi

if [ "$failures" -ne 0 ]; then
  printf 'Longhorn recovery failed: %s volume(s) failed\n' "$failures" >&2
  exit 1
fi
printf 'Longhorn recovery %s passed\n' "$MODE"
