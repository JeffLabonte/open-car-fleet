#!/bin/bash
# Backup the PostgreSQL database from the running Docker Compose stack to
# /opt/backups/database. A new compressed dump is created only when the dump
# content has changed compared with the previous dump.
set -euo pipefail

umask 077

BACKUP_DIR="/opt/backups/database"
COMPOSE_FILE="/opt/open-car-fleet/docker-compose.prod.yml"
TEMP_DIR="$(mktemp -d)"

cleanup() {
    rm -rf "$TEMP_DIR"
}
trap cleanup EXIT

mkdir -p "$BACKUP_DIR"

TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
RAW_SQL="$TEMP_DIR/snapshot-$TIMESTAMP.sql"
NORMALIZED_SQL="$TEMP_DIR/snapshot-normalized.sql"
DUMP="$BACKUP_DIR/snapshot-$TIMESTAMP.sql.gz"

# Load credentials from the production env file on the host.
ENV_FILE="/opt/open-car-fleet/src/.env"
if [[ -f "$ENV_FILE" ]]; then
    # shellcheck source=/dev/null
    set -a
    # shellcheck source=/dev/null
    source "$ENV_FILE"
    set +a
fi

POSTGRES_USER="${POSTGRES_USER:-open_garage_user}"
POSTGRES_DB="${POSTGRES_DB:-open_garage}"

# Dump the raw SQL to a temp file.
docker compose -f "$COMPOSE_FILE" exec -T db \
    pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" > "$RAW_SQL"

# Normalize non-deterministic pg_dump restrict/unrestrict tokens before
# comparing hashes. The random token values change on every dump even when
# the data has not changed.
sed -E 's/^(\\restrict|\\unrestrict) .*/\1 DETERMINISTIC_TOKEN/' "$RAW_SQL" > "$NORMALIZED_SQL"

# Compute the hash of the normalized dump.
HASH="$(sha512sum "$NORMALIZED_SQL" | awk '{print $1}')"

# Compare with the most recent kept dump.
LATEST_DUMP="$(ls -1 "$BACKUP_DIR"/snapshot-*.sql.gz 2>/dev/null | sort | tail -n1 || true)"
if [[ -n "$LATEST_DUMP" ]]; then
    LATEST_NORMALIZED="$TEMP_DIR/latest-normalized.sql"
    zcat "$LATEST_DUMP" | sed -E 's/^(\\restrict|\\unrestrict) .*/\1 DETERMINISTIC_TOKEN/' > "$LATEST_NORMALIZED"
    LATEST_HASH="$(sha512sum "$LATEST_NORMALIZED" | awk '{print $1}')"
    if [[ "$LATEST_HASH" == "$HASH" ]]; then
        echo "$(date -Iseconds) database: no changes since $(basename "$LATEST_DUMP"). Skipping."
        exit 0
    fi
fi

# Keep the new dump (compressed deterministically).
gzip -n -c "$RAW_SQL" > "$DUMP"
chmod 600 "$DUMP"
echo "$(date -Iseconds) database: created $DUMP"

# Retain only the 10 most recent dumps.
cd "$BACKUP_DIR"
ls -1 snapshot-*.sql.gz 2>/dev/null | sort | head -n -10 | xargs -r rm -f
