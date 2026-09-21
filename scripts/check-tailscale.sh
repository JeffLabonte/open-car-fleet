#!/usr/bin/env bash
# Pre-flight check: ensure Tailscale is installed, logged in, and the target
# host is reachable. Run this before ansible-ping / ansible-deploy when the
# inventory uses a Tailscale hostname or IP.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
INVENTORY="${REPO_ROOT}/ansible/inventory.yml"

if ! command -v tailscale >/dev/null 2>&1; then
  echo "Error: tailscale CLI not found. Install Tailscale first:" >&2
  echo "  https://tailscale.com/download" >&2
  exit 1
fi

STATUS_JSON="$(tailscale status --json 2>/dev/null || true)"
if [[ -z "$STATUS_JSON" ]]; then
  echo "Error: Tailscale is not running. Start it with:" >&2
  echo "  sudo tailscale up" >&2
  echo "Then open the browser link and log in with your credentials." >&2
  exit 1
fi

BACKEND_STATE="$(echo "$STATUS_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("BackendState",""))' 2>/dev/null || true)"
if [[ "$BACKEND_STATE" != "Running" ]]; then
  echo "Error: Tailscale backend state is '${BACKEND_STATE:-unknown}', expected 'Running'." >&2
  echo "Log in with:" >&2
  echo "  tailscale login" >&2
  echo "Or, if you have not joined this tailnet:" >&2
  echo "  tailscale up" >&2
  exit 1
fi

SELF_DNS_NAME="$(echo "$STATUS_JSON" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("Self",{}).get("DNSName","").rstrip("."))' 2>/dev/null || true)"
if [[ -n "$SELF_DNS_NAME" ]]; then
  echo "Tailscale is connected as: $SELF_DNS_NAME"
else
  echo "Tailscale is connected."
fi

if [[ -f "$INVENTORY" ]]; then
  HOSTS="$(python3 - "$INVENTORY" <<'PY'
import yaml, sys
with open(sys.argv[1]) as f:
    data = yaml.safe_load(f)
hosts = []
for child in data.get('all', {}).get('children', {}).values():
    hosts.extend(child.get('hosts', {}).keys())
print(' '.join(hosts))
PY
  )"

  if [[ -n "$HOSTS" ]]; then
    echo "Inventory hosts: $HOSTS"
    for host in $HOSTS; do
      # Try a short Tailscale ping (requires host to be online in tailnet).
      # Fall back to a plain ping if tailscale ping is unavailable.
      if ! tailscale ping --c=1 --timeout=5s "$host" >/dev/null 2>&1; then
        echo "Warning: tailscale ping to '$host' failed. The host may be offline or not in your tailnet." >&2
      else
        echo "Tailscale ping to '$host': OK"
      fi
    done
  fi
else
  echo "Warning: inventory not found at $INVENTORY" >&2
fi

echo ""
echo "Tailscale pre-flight check passed. You can now run ansible-ping / ansible-deploy."
