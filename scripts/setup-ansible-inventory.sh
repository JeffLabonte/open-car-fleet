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

read -rp "Use Tailscale for this host? [Y/n]: " use_tailscale
use_tailscale="${use_tailscale:-Y}"

if [[ "$use_tailscale" =~ ^[Yy]$ ]]; then
  echo ""
  echo "Make sure you are logged into Tailscale first:"
  echo "  tailscale up"
  echo "  (open the provided link and authenticate with your credentials)"
  echo ""
  read -rp "Tailscale hostname or IP [xps-server.kanyu-bluegill.ts.net]: " server_ip
  server_ip="${server_ip:-xps-server.kanyu-bluegill.ts.net}"
  read -rp "SSH user [root]: " ssh_user
  ssh_user="${ssh_user:-root}"

  read -rp "Use Tailscale SSH (no private key required)? [y/N]: " use_tailscale_ssh
  use_tailscale_ssh="${use_tailscale_ssh:-N}"
  if [[ "$use_tailscale_ssh" =~ ^[Yy]$ ]]; then
    ssh_key=""
  else
    read -erp "SSH private key path [~/.ssh/id_rsa]: " ssh_key
    ssh_key="${ssh_key:-$HOME/.ssh/id_rsa}"
    # Expand ~ in ssh_key for the inventory file.
    ssh_key="${ssh_key/#\~/$HOME}"
  fi
else
  read -rp "Server IP or hostname: " server_ip
  read -rp "SSH user [root]: " ssh_user
  ssh_user="${ssh_user:-root}"
  read -erp "SSH private key path [~/.ssh/id_rsa]: " ssh_key
  ssh_key="${ssh_key:-$HOME/.ssh/id_rsa}"
  # Expand ~ in ssh_key for the inventory file.
  ssh_key="${ssh_key/#\~/$HOME}"
fi

read -rp "Remote app directory [/opt/open-car-fleet]: " app_dir
app_dir="${app_dir:-/opt/open-car-fleet}"
read -erp "Local env file [./src/.env.production]: " env_file
env_file="${env_file:-./src/.env.production}"

# Ask for the sudo password interactively. Stored only in the local, gitignored
# inventory file so ansible-playbook can use it via ansible_become_password.
read -rsp "Sudo/become password for remote user (press Enter to skip): " become_password
become_password="${become_password:-}"
echo ""

cp "$TEMPLATE" "$OUTPUT"

# Use Python to rewrite YAML values while preserving structure.
python3 - "$OUTPUT" <<PY
from pathlib import Path

path = Path(r"$OUTPUT")
text = path.read_text()

text = text.replace('xps-server.kanyu-bluegill.ts.net:', r"$server_ip:")
text = text.replace('ansible_user: root', 'ansible_user: ' + r"$ssh_user")
if r"$use_tailscale"[0].lower() == 'y':
    # Add StrictHostKeyChecking=no for Tailscale connections; Tailscale
    # already authenticates the tunnel, so SSH host-key prompting is not needed.
    text = text.replace(
        '          ansible_user: ' + r"$ssh_user",
        '          ansible_user: ' + r"$ssh_user" + '\n          ansible_ssh_extra_args: -o StrictHostKeyChecking=no'
    )
if r"$ssh_key":
    text = text.replace('ansible_ssh_private_key_file: ~/.ssh/id_rsa', 'ansible_ssh_private_key_file: ' + r"$ssh_key")
else:
    # Remove the SSH key line when using Tailscale SSH.
    text = text.replace('          ansible_ssh_private_key_file: ~/.ssh/id_rsa\n', '')
text = text.replace('app_dir: /opt/open-car-fleet', 'app_dir: ' + r"$app_dir")
text = text.replace('env_file: ./src/.env.production', 'env_file: ' + r"$env_file")
if r"$become_password":
    text = text.replace(
        '          ansible_user: ' + r"$ssh_user",
        '          ansible_user: ' + r"$ssh_user" + '\n          ansible_become_password: ' + r"$become_password"
    )

path.write_text(text)
PY

echo ""
echo "Wrote $OUTPUT"
echo "Next steps:"
echo "  1) Verify Tailscale login: make check-tailscale"
echo "  2) Verify SSH: make ansible-ping"
echo "  3) Prepare env: scripts/prepare-env.sh --hanko-api-url ..."
echo "  4) Deploy: make ansible-deploy"
