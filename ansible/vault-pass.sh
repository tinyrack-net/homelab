#!/bin/sh
# Ansible Vault password client.
# Prints ANSIBLE_VAULT_PASSWORD when set, otherwise the gitignored .vault_pass file.
# A script (instead of a plain password file) keeps working on WSL drvfs mounts,
# where every file looks executable and Ansible would try to run .vault_pass itself.
set -eu
if [ -n "${ANSIBLE_VAULT_PASSWORD:-}" ]; then
  printf '%s\n' "$ANSIBLE_VAULT_PASSWORD"
  exit 0
fi
file="$(dirname "$0")/.vault_pass"
if [ ! -f "$file" ]; then
  echo "vault-pass.sh: set ANSIBLE_VAULT_PASSWORD or create $file" >&2
  exit 1
fi
tr -d '\r\n' < "$file"
printf '\n'
