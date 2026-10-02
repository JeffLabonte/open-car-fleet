#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/prepare-env.sh [options]

Options:
  --output <path>                 Output file (default: src/.env.production)
  --template <path>               Template file (default: src/.env.template)
  --hanko-api-url <url>           Hanko API URL
  --allowed-hosts "<hosts>"       Space-separated DJANGO_ALLOWED_HOSTS
  --csrf-trusted-origins "<list>" Space/comma-separated CSRF trusted origins
  --mailersend-api-token <token>  MailerSend API token ("custom access": full Email access, no other features)
  --from-email "<addr>"           DEFAULT_FROM_EMAIL (address on the verified MailerSend domain)
  --server-email "<addr>"         SERVER_EMAIL for Django-internal mail (default: DEFAULT_FROM_EMAIL)
  --postgres-db <name>            Postgres DB name (default: open_garage)
  --postgres-user <user>          Postgres user (default: open_garage_user)
  --postgres-password <password>  Postgres password (default: generated)
  --postgres-host <host>          Postgres host (default: db)
  --postgres-port <port>          Postgres port (default: 5432)
  --force                         Overwrite output file if it exists
  -h, --help                      Show this help
EOF
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

OUTPUT_FILE="${REPO_ROOT}/src/.env.production"
TEMPLATE_FILE="${REPO_ROOT}/src/.env.template"
HANKO_API_URL=""
DJANGO_ALLOWED_HOSTS="localhost 127.0.0.1"
CSRF_TRUSTED_ORIGINS=""
MAILERSEND_API_TOKEN=""
DEFAULT_FROM_EMAIL=""
SERVER_EMAIL=""
POSTGRES_DB="open_garage"
POSTGRES_USER="open_garage_user"
POSTGRES_PASSWORD=""
POSTGRES_HOST="db"
POSTGRES_PORT="5432"
FORCE_OVERWRITE="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output)
      OUTPUT_FILE="${2:-}"
      shift 2
      ;;
    --template)
      TEMPLATE_FILE="${2:-}"
      shift 2
      ;;
    --hanko-api-url)
      HANKO_API_URL="${2:-}"
      shift 2
      ;;
    --allowed-hosts)
      DJANGO_ALLOWED_HOSTS="${2:-}"
      shift 2
      ;;
    --csrf-trusted-origins)
      CSRF_TRUSTED_ORIGINS="${2:-}"
      shift 2
      ;;
    --mailersend-api-token)
      MAILERSEND_API_TOKEN="${2:-}"
      shift 2
      ;;
    --from-email)
      DEFAULT_FROM_EMAIL="${2:-}"
      shift 2
      ;;
    --server-email)
      SERVER_EMAIL="${2:-}"
      shift 2
      ;;
    --postgres-db)
      POSTGRES_DB="${2:-}"
      shift 2
      ;;
    --postgres-user)
      POSTGRES_USER="${2:-}"
      shift 2
      ;;
    --postgres-password)
      POSTGRES_PASSWORD="${2:-}"
      shift 2
      ;;
    --postgres-host)
      POSTGRES_HOST="${2:-}"
      shift 2
      ;;
    --postgres-port)
      POSTGRES_PORT="${2:-}"
      shift 2
      ;;
    --force)
      FORCE_OVERWRITE="true"
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

if [[ ! -f "${TEMPLATE_FILE}" ]]; then
  echo "Error: template file not found at ${TEMPLATE_FILE}" >&2
  exit 1
fi

if [[ -f "${OUTPUT_FILE}" && "${FORCE_OVERWRITE}" != "true" ]]; then
  echo "Error: ${OUTPUT_FILE} already exists. Use --force to overwrite." >&2
  exit 1
fi

if [[ -z "${POSTGRES_PASSWORD}" ]]; then
  POSTGRES_PASSWORD="$(python -c 'import secrets; print(secrets.token_urlsafe(24))')"
fi

DJANGO_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(50))')"

cp "${TEMPLATE_FILE}" "${OUTPUT_FILE}"

export OUTPUT_FILE HANKO_API_URL DJANGO_SECRET_KEY DJANGO_ALLOWED_HOSTS \
    CSRF_TRUSTED_ORIGINS MAILERSEND_API_TOKEN DEFAULT_FROM_EMAIL SERVER_EMAIL \
    POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD POSTGRES_HOST POSTGRES_PORT

python3 - <<'PY'
import os
from pathlib import Path

env_file = Path(os.environ["OUTPUT_FILE"])
updates = {
    "HANKO_API_URL": os.environ["HANKO_API_URL"],
    "DJANGO_SECRET_KEY": os.environ["DJANGO_SECRET_KEY"],
    "DEBUG": "False",
    "DJANGO_ALLOWED_HOSTS": os.environ["DJANGO_ALLOWED_HOSTS"],
    "CSRF_TRUSTED_ORIGINS": os.environ["CSRF_TRUSTED_ORIGINS"],
    "SECURE_SSL_REDIRECT": "True",
    "SECURE_HSTS_SECONDS": "31536000",
    "SESSION_COOKIE_SECURE": "True",
    "CSRF_COOKIE_SECURE": "True",
    "MAILERSEND_API_TOKEN": os.environ["MAILERSEND_API_TOKEN"],
    "DEFAULT_FROM_EMAIL": os.environ["DEFAULT_FROM_EMAIL"],
    "SERVER_EMAIL": os.environ["SERVER_EMAIL"],
    "POSTGRES_DB": os.environ["POSTGRES_DB"],
    "POSTGRES_USER": os.environ["POSTGRES_USER"],
    "POSTGRES_PASSWORD": os.environ["POSTGRES_PASSWORD"],
    "POSTGRES_HOST": os.environ["POSTGRES_HOST"],
    "POSTGRES_PORT": os.environ["POSTGRES_PORT"],
}

lines = env_file.read_text().splitlines()
for key, value in updates.items():
    if value == "":
        continue
    replaced = False
    for idx, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[idx] = f"{key}={value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{key}={value}")

env_file.write_text("\n".join(lines) + "\n")
PY

if [[ -z "${HANKO_API_URL}" ]]; then
  echo "Warning: HANKO_API_URL is empty. Set it before deploying."
fi

if [[ -z "${MAILERSEND_API_TOKEN}" ]]; then
  echo "Warning: MAILERSEND_API_TOKEN is empty. Invitation emails will fail until it is set."
fi

if [[ -z "${DEFAULT_FROM_EMAIL}" ]]; then
  echo "Warning: DEFAULT_FROM_EMAIL is empty. It must be an address on your verified MailerSend domain."
fi

echo "Wrote ${OUTPUT_FILE}"
echo "Next steps:"
echo "  1) Review DJANGO_ALLOWED_HOSTS and CSRF_TRUSTED_ORIGINS"
echo "  2) Set HANKO_API_URL if missing"
echo "  3) Set MAILERSEND_API_TOKEN and DEFAULT_FROM_EMAIL (verified MailerSend domain) if missing"
echo "  4) Verify HTTPS is terminated in front of the app (SECURE_SSL_REDIRECT and HSTS are enabled)"
echo "  5) Deploy with scripts/deploy-ssh.sh --host <user@server> --env-file ${OUTPUT_FILE}"
