#!/usr/bin/env bash
# Generate ansible/inventory.yml from the tracked template.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TEMPLATE="${REPO_ROOT}/ansible/inventory.yml.template"
OUTPUT="${REPO_ROOT}/ansible/inventory.yml"

if [[ ! -f "$TEMPLATE" ]]; then
  echo "Error: template not found at $TEMPLATE" >&2
  exit 1
fi

if [[ -f "$OUTPUT" ]]; then
  echo "Inventory already exists at $OUTPUT"
  read -rp "Overwrite? [y/N] " answer
  if [[ ! "$answer" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
  fi
fi

echo "Open Car Fleet Ansible inventory setup"
echo "--------------------------------------"

read -rp "Server IP or hostname: " server_ip
read -rp "SSH user [root]: " ssh_user
ssh_user="${ssh_user:-root}"
read -erp "SSH private key path [~/.ssh/id_rsa]: " ssh_key
ssh_key="${ssh_key:-$HOME/.ssh/id_rsa}"
read -rp "Remote app directory [/opt/open-car-fleet]: " app_dir
app_dir="${app_dir:-/opt/open-car-fleet}"
read -erp "Local env file [./src/.env.production]: " env_file
env_file="${env_file:-./src/.env.production}"

# Expand ~ in ssh_key for the inventory file.
ssh_key="${ssh_key/#\~/$HOME}"

cp "$TEMPLATE" "$OUTPUT"

# Use Python to rewrite YAML values while preserving structure.
python3 - "$OUTPUT" <<PY
from pathlib import Path

path = Path(r"$OUTPUT")
text = path.read_text()

text = text.replace('your_server_ip', r"$server_ip", 1)
text = text.replace('ansible_user: root', 'ansible_user: ' + r"$ssh_user")
text = text.replace('ansible_ssh_private_key_file: ~/.ssh/id_rsa', 'ansible_ssh_private_key_file: ' + r"$ssh_key")
text = text.replace('app_dir: /opt/open-car-fleet', 'app_dir: ' + r"$app_dir")
text = text.replace('env_file: ./src/.env.production', 'env_file: ' + r"$env_file")

path.write_text(text)
PY

echo ""
echo "Wrote $OUTPUT"
echo "Next steps:"
echo "  1) Verify SSH: make ansible-ping"
echo "  2) Prepare env: scripts/prepare-env.sh --hanko-api-url ..."
echo "  3) Deploy: make ansible-deploy"
