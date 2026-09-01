#!/usr/bin/env bash
set -euo pipefail

K3S_VERSION="v1.36.4+k3s1"
K3S_INSTALLER_URL="https://get.k3s.io"
K3S_INSTALLER_SHA256="ed01f89fd977bf20ac1516bbebf8370bf3ddbaa55dac8aba610956a4c78cc00b"
EXPECTED_NODE_NAME="${EXPECTED_NODE_NAME:-xeon}"
BACKUP_ENDPOINT="${BACKUP_ENDPOINT:-https://storage.winetree94.com}"
MODE="${1:---check}"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

check_platform() {
  [ "$(dpkg --print-architecture)" = "amd64" ] || fail "amd64 Ubuntu is required"
  # /etc/os-release is a standard file provided by Ubuntu.
  # shellcheck disable=SC1091
  . /etc/os-release
  [ "${ID:-}" = "ubuntu" ] || fail "Ubuntu is required"
  [ "${VERSION_ID:-}" = "24.04" ] || fail "Ubuntu 24.04 is required"
  [ "$(hostname -s)" = "$EXPECTED_NODE_NAME" ] || fail "hostname must be $EXPECTED_NODE_NAME"
}

check_packages() {
  local package
  for package in curl ca-certificates jq open-iscsi nfs-common cryptsetup; do
    dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q 'install ok installed' || \
      fail "missing package: $package"
  done
  modprobe -n overlay >/dev/null 2>&1 || fail "overlay kernel module is unavailable"
  modprobe -n br_netfilter >/dev/null 2>&1 || fail "br_netfilter kernel module is unavailable"
  systemctl is-enabled --quiet iscsid.socket || fail "iscsid socket is not enabled"
  systemctl is-active --quiet iscsid || fail "iscsid is not active"
}

check_backup_endpoint() {
  local status
  status="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' "$BACKUP_ENDPOINT")"
  [ "$status" != "000" ] || fail "backup endpoint is unreachable: $BACKUP_ENDPOINT"
}

check_k3s() {
  command -v k3s >/dev/null 2>&1 || fail "k3s is not installed"
  k3s --version | grep -Fq "$K3S_VERSION" || fail "k3s version is not $K3S_VERSION"
  local unit
  unit="$(systemctl cat k3s)"
  grep -Fq -- '--cluster-cidr=10.61.0.0/16' <<<"$unit" || fail "cluster CIDR differs"
  grep -Fq -- '--service-cidr=10.62.0.0/16' <<<"$unit" || fail "service CIDR differs"
  grep -Fq "'traefik'" <<<"$unit" || fail "traefik is not disabled"
  grep -Fq "'servicelb'" <<<"$unit" || fail "servicelb is not disabled"
}

check_platform

case "$MODE" in
  --check)
    check_packages
    check_backup_endpoint
    check_k3s
    printf 'node bootstrap preflight passed\n'
    ;;
  --install)
    [ "$(id -u)" -eq 0 ] || fail "--install must run as root"
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
      curl ca-certificates jq open-iscsi nfs-common cryptsetup
    modprobe overlay
    modprobe br_netfilter
    systemctl enable --now iscsid.socket
    systemctl start iscsid

    installer_file="$(mktemp)"
    trap 'rm -f "$installer_file"' EXIT
    curl -fsSL "$K3S_INSTALLER_URL" -o "$installer_file"
    printf '%s  %s\n' "$K3S_INSTALLER_SHA256" "$installer_file" | sha256sum --check --status || \
      fail "K3s installer checksum mismatch"
    INSTALL_K3S_VERSION="$K3S_VERSION" sh "$installer_file" server \
      --cluster-init \
      --cluster-cidr=10.61.0.0/16 \
      --service-cidr=10.62.0.0/16 \
      --disable traefik \
      --disable servicelb
    check_packages
    check_backup_endpoint
    check_k3s
    ;;
  *)
    fail "usage: $0 [--check|--install]"
    ;;
esac
