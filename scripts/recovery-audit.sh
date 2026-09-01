#!/usr/bin/env bash
set -euo pipefail

CONTEXT="homelab"
MAX_AGE_HOURS=13

while [ "$#" -gt 0 ]; do
  case "$1" in
    --context)
      CONTEXT="$2"
      shift 2
      ;;
    --max-age-hours)
      MAX_AGE_HOURS="$2"
      shift 2
      ;;
    *)
      printf 'usage: %s [--context CONTEXT] [--max-age-hours HOURS]\n' "$0" >&2
      exit 2
      ;;
  esac
done

command -v kubectl >/dev/null || { printf 'kubectl is required\n' >&2; exit 1; }
command -v jq >/dev/null || { printf 'jq is required\n' >&2; exit 1; }
[[ "$MAX_AGE_HOURS" =~ ^[0-9]+$ ]] || { printf 'max age must be a non-negative integer\n' >&2; exit 2; }

now_epoch="$(date -u +%s)"
max_age_seconds="$((MAX_AGE_HOURS * 3600))"
failures=0

check_database() {
  local namespace="$1" cluster="$2" expected_server="$3"
  local cluster_json effective_server latest_backup stopped_at stopped_epoch age
  cluster_json="$(kubectl --context "$CONTEXT" -n "$namespace" get clusters.postgresql.cnpg.io "$cluster" -o json)" || return 1
  effective_server="$(jq -r --arg cluster "$cluster" '[.spec.plugins[] | select(.name=="barman-cloud.cloudnative-pg.io") | .parameters.serverName][0] // $cluster' <<<"$cluster_json")"
  if [ "$effective_server" != "$expected_server" ]; then
    printf 'FAIL database %s/%s archive server is %s, expected %s\n' "$namespace" "$cluster" "$effective_server" "$expected_server" >&2
    failures=$((failures + 1))
  fi
  latest_backup="$(kubectl --context "$CONTEXT" -n "$namespace" get backups.postgresql.cnpg.io -o json | jq -c --arg cluster "$cluster" '[.items[] | select(.spec.cluster.name==$cluster and .status.phase=="completed")] | sort_by(.status.stoppedAt) | last // empty')"
  if [ -z "$latest_backup" ]; then
    printf 'FAIL database %s/%s has no completed backup\n' "$namespace" "$cluster" >&2
    failures=$((failures + 1))
    return
  fi
  stopped_at="$(jq -r '.status.stoppedAt' <<<"$latest_backup")"
  stopped_epoch="$(date -u -d "$stopped_at" +%s)"
  age=$((now_epoch - stopped_epoch))
  if [ "$age" -gt "$max_age_seconds" ]; then
    printf 'FAIL database %s/%s backup is older than %sh: %s\n' "$namespace" "$cluster" "$MAX_AGE_HOURS" "$stopped_at" >&2
    failures=$((failures + 1))
  else
    printf 'OK   database %s/%s backup=%s stopped=%s\n' "$namespace" "$cluster" "$(jq -r '.metadata.name' <<<"$latest_backup")" "$stopped_at"
  fi
  kubectl --context "$CONTEXT" -n "$namespace" get secret tinyrack-homelab-s3-secret >/dev/null || failures=$((failures + 1))
}

check_database davinci-resolve-system davinci-resolve-database-cluster davinci-resolve-database-pg18
check_database guacamole-system guacamole-database-cluster guacamole-database-cluster
check_database infisical-system infisical-database-cluster infisical-database-cluster
check_database issuary-system issuary-database-cluster issuary-database-cluster
check_database litellm-system litellm-database-cluster litellm-database-cluster
check_database n8n-system n8n-database-cluster n8n-database-cluster
check_database openwebui-system openwebui-database-cluster openwebui-database-cluster

backup_target_available="$(kubectl --context "$CONTEXT" -n longhorn-system get backuptargets.longhorn.io default -o jsonpath='{.status.available}')"
if [ "$backup_target_available" != "true" ]; then
  printf 'FAIL Longhorn backup target is unavailable\n' >&2
  failures=$((failures + 1))
else
  printf 'OK   Longhorn backup target is available\n'
fi

if [ "$failures" -ne 0 ]; then
  printf 'recovery audit failed: %s check(s) failed\n' "$failures" >&2
  exit 1
fi
printf 'recovery audit passed\n'
