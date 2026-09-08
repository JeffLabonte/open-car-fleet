#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/deploy-ssh.sh --host user@server [options]

Options:
  --host <user@server>          SSH host (required)
  --remote-dir <path>           Remote app directory (default: /opt/open-car-fleet)
  --env-file <path>             Local env file to upload as src/.env (default: src/.env.production)
  --ssh-port <port>             SSH port (default: 22)
  --skip-upload                 Skip source upload and run only remote docker commands
  -h, --help                    Show this help
EOF
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

HOST=""
REMOTE_DIR="/opt/open-car-fleet"
ENV_FILE="${REPO_ROOT}/src/.env.production"
SSH_PORT="22"
SKIP_UPLOAD="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      HOST="${2:-}"
      shift 2
      ;;
    --remote-dir)
      REMOTE_DIR="${2:-}"
      shift 2
      ;;
    --env-file)
      ENV_FILE="${2:-}"
      shift 2
      ;;
    --ssh-port)
      SSH_PORT="${2:-}"
      shift 2
      ;;
    --skip-upload)
      SKIP_UPLOAD="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "${HOST}" ]]; then
  echo "Error: --host is required." >&2
  usage
  exit 1
fi

if [[ "${SKIP_UPLOAD}" != "true" && ! -f "${ENV_FILE}" ]]; then
  echo "Error: env file not found at ${ENV_FILE}" >&2
  exit 1
fi

for cmd in ssh tar docker; do
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "Error: '${cmd}' is required but was not found in PATH." >&2
    exit 1
  fi
done

SSH_OPTS=(-p "${SSH_PORT}" -o BatchMode=yes -o StrictHostKeyChecking=accept-new)

if [[ "${SKIP_UPLOAD}" != "true" ]]; then
  echo "Uploading application source to ${HOST}:${REMOTE_DIR} ..."
  tar -C "${REPO_ROOT}" \
    --exclude=".git" \
    --exclude=".venv" \
    --exclude="__pycache__" \
    --exclude=".pytest_cache" \
    --exclude="*.pyc" \
    -czf - . \
    | ssh "${SSH_OPTS[@]}" "${HOST}" "mkdir -p '${REMOTE_DIR}' && tar -xzf - -C '${REMOTE_DIR}'"

  echo "Uploading env file to ${HOST}:${REMOTE_DIR}/src/.env ..."
  cat "${ENV_FILE}" | ssh "${SSH_OPTS[@]}" "${HOST}" "cat > '${REMOTE_DIR}/src/.env'"
fi

echo "Running Docker deployment commands on remote host ..."
ssh "${SSH_OPTS[@]}" "${HOST}" "bash -s" <<EOF
set -euo pipefail
cd '${REMOTE_DIR}'
docker compose up -d --build
docker compose run --rm web python /app/src/manage.py migrate
docker compose up -d web
docker compose ps
EOF

echo "Deployment completed."
