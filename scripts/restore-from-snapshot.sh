#!/usr/bin/env bash
# Restore Open Car Fleet database and media from backups.
#
# This script is intended to run on the Docker host (e.g. xps-server) as root or
# a user with Docker privileges and access to /opt/backups. It:
#
#   1. Stops the web container to prevent writes.
#   2. Takes a safety snapshot of the current DB/media (if any).
#   3. Wipes and recreates the Postgres volume.
#   4. Restores the provided SQL snapshot.
#   5. Reconciles migration-history edge cases for snapshots taken between the
#      attachment size_bytes work and the garage->fleet rename.
#   6. Runs Django migrations (this applies 0019_rename_garage_to_fleet).
#   7. Restores media files from the provided tarball.
#   8. Brings the web service back up.
#
# Usage:
#   sudo scripts/restore-from-snapshot.sh \
#       --db-snapshot snapshot-20261009-010001.sql.gz \
#       --media-snapshot /opt/backups/media/snapshot-20261009-010000.tar.gz
#
# Environment overrides:
#   APP_DIR         defaults to /opt/open-car-fleet
#   COMPOSE_FILE    defaults to $APP_DIR/docker-compose.prod.yml
#   DB_BACKUP_DIR   defaults to /opt/backups/database
#   MEDIA_BACKUP_DIR defaults to /opt/backups/media

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/open-car-fleet}"
COMPOSE_FILE="${COMPOSE_FILE:-$APP_DIR/docker-compose.prod.yml}"
DB_BACKUP_DIR="${DB_BACKUP_DIR:-/opt/backups/database}"
MEDIA_BACKUP_DIR="${MEDIA_BACKUP_DIR:-/opt/backups/media}"

usage() {
    cat <<'EOF'
Usage: restore-from-snapshot.sh [options]

Required options:
  --db-snapshot <path>      Path to the gzipped SQL dump to restore.
  --media-snapshot <path>   Path to the media tarball to restore.

Optional environment overrides:
  APP_DIR             Application directory (default: /opt/open-car-fleet)
  COMPOSE_FILE        Docker Compose file (default: $APP_DIR/docker-compose.prod.yml)
  DB_BACKUP_DIR       Directory for pre-restore DB safety backups
  MEDIA_BACKUP_DIR    Directory for pre-restore media safety backups

Example:
  sudo scripts/restore-from-snapshot.sh \
    --db-snapshot /opt/backups/database/snapshot-20261009-010001.sql.gz \
    --media-snapshot /opt/backups/media/snapshot-20261009-010000.tar.gz
EOF
}

DB_SNAPSHOT=""
MEDIA_SNAPSHOT=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --db-snapshot)
            DB_SNAPSHOT="${2:-}"
            shift 2
            ;;
        --media-snapshot)
            MEDIA_SNAPSHOT="${2:-}"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

if [[ -z "$DB_SNAPSHOT" ]]; then
    echo "Error: --db-snapshot is required." >&2
    usage >&2
    exit 1
fi

if [[ -z "$MEDIA_SNAPSHOT" ]]; then
    echo "Error: --media-snapshot is required." >&2
    usage >&2
    exit 1
fi

if [[ ! -f "$DB_SNAPSHOT" ]]; then
    echo "Error: DB snapshot not found: $DB_SNAPSHOT" >&2
    exit 1
fi

if [[ ! -f "$MEDIA_SNAPSHOT" ]]; then
    echo "Error: media snapshot not found: $MEDIA_SNAPSHOT" >&2
    exit 1
fi

if [[ ! -f "$COMPOSE_FILE" ]]; then
    echo "Error: Docker Compose file not found: $COMPOSE_FILE" >&2
    exit 1
fi

# Load credentials from the deployed env file.
ENV_FILE="$APP_DIR/src/.env"
if [[ -f "$ENV_FILE" ]]; then
    # shellcheck source=/dev/null
    set -a
    # shellcheck source=/dev/null
    source "$ENV_FILE"
    set +a
fi

POSTGRES_USER="${POSTGRES_USER:-open_garage_user}"
POSTGRES_DB="${POSTGRES_DB:-open_garage}"

TIMESTAMP="$(date +%Y%m%d-%H%M%S)"

cleanup() {
    echo "Restore aborted. Check the safety backups in $DB_BACKUP_DIR and $MEDIA_BACKUP_DIR." >&2
}
trap cleanup ERR

mkdir -p "$DB_BACKUP_DIR" "$MEDIA_BACKUP_DIR"

# ---------------------------------------------------------------------------
# 1. Stop web to prevent any writes during restore.
# ---------------------------------------------------------------------------
echo "[1/8] Stopping web container..."
docker compose -f "$COMPOSE_FILE" stop web || true

# ---------------------------------------------------------------------------
# 2. Safety backups of current state (best-effort).
# ---------------------------------------------------------------------------
echo "[2/8] Creating safety backups of current DB and media..."
if docker compose -f "$COMPOSE_FILE" ps -q db >/dev/null 2>&1; then
    docker compose -f "$COMPOSE_FILE" exec -T db \
        pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        | gzip -n > "$DB_BACKUP_DIR/snapshot-pre-restore-$TIMESTAMP.sql.gz" \
        || echo "Warning: current DB backup failed (DB may be empty)."
fi

if docker compose -f "$COMPOSE_FILE" ps -q web >/dev/null 2>&1; then
    docker compose -f "$COMPOSE_FILE" cp "web:/app/src/media/." "$MEDIA_BACKUP_DIR/media-pre-restore-$TIMESTAMP/" \
        || echo "Warning: current media backup failed (media may be empty)."
    if [[ -d "$MEDIA_BACKUP_DIR/media-pre-restore-$TIMESTAMP" ]]; then
        tar czf "$MEDIA_BACKUP_DIR/snapshot-pre-restore-$TIMESTAMP.tar.gz" -C "$MEDIA_BACKUP_DIR/media-pre-restore-$TIMESTAMP" . \
            || echo "Warning: could not tarball pre-restore media."
        rm -rf "$MEDIA_BACKUP_DIR/media-pre-restore-$TIMESTAMP"
    fi
fi

# ---------------------------------------------------------------------------
# 3. Reset the Postgres volume.
# ---------------------------------------------------------------------------
echo "[3/8] Resetting Postgres volume..."
docker compose -f "$COMPOSE_FILE" down -v --remove-orphans
docker compose -f "$COMPOSE_FILE" up -d db

# Wait for the DB to be ready.
echo "Waiting for Postgres to be ready..."
for attempt in $(seq 1 60); do
    if docker compose -f "$COMPOSE_FILE" exec -T db pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
        echo "Postgres is ready."
        break
    fi
    if [[ "$attempt" -eq 60 ]]; then
        echo "Error: Postgres did not become ready in time." >&2
        docker compose -f "$COMPOSE_FILE" ps >&2
        exit 1
    fi
    sleep 2
done

# ---------------------------------------------------------------------------
# 4. Restore the SQL snapshot.
# ---------------------------------------------------------------------------
echo "[4/8] Restoring DB snapshot: $DB_SNAPSHOT..."
case "$DB_SNAPSHOT" in
    *.gz|*.gzip)
        zcat "$DB_SNAPSHOT"
        ;;
    *.sql)
        cat "$DB_SNAPSHOT"
        ;;
    *)
        echo "Error: DB snapshot must be .sql.gz, .gz, or .sql" >&2
        exit 1
        ;;
esac | docker compose -f "$COMPOSE_FILE" exec -T db \
    psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1

# ---------------------------------------------------------------------------
# 5. Reconcile migration/schema edge cases for pre-fleet snapshots.
#
# Snapshots taken between the attachment size_bytes work and the
# garage->fleet rename record migration 0018 as "attachment_size_bytes" and
# have a NOT NULL size_bytes column. The current codebase replaced that
# migration with "attachment_kind_default_blank" and removed the field.
# We drop the dead column and the obsolete migration record so Django can
# apply the current migrations cleanly.
# ---------------------------------------------------------------------------
echo "[5/8] Reconciling migration history..."
SIZE_BYTES_EXISTS="$(docker compose -f "$COMPOSE_FILE" exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "
    SELECT 1
    FROM information_schema.columns
    WHERE table_name = 'shop_attachment' AND column_name = 'size_bytes'
")" || SIZE_BYTES_EXISTS=""

if [[ "$SIZE_BYTES_EXISTS" == "1" ]]; then
    echo "  Found legacy size_bytes column; cleaning up..."
    docker compose -f "$COMPOSE_FILE" exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 <<'SQL'
BEGIN;
DELETE FROM django_migrations WHERE app = 'shop' AND name = '0018_attachment_size_bytes';
ALTER TABLE shop_attachment DROP COLUMN IF EXISTS size_bytes;
COMMIT;
SQL
else
    echo "  No legacy size_bytes column found; nothing to reconcile."
fi

# ---------------------------------------------------------------------------
# 6. Run Django migrations. This is what renames garage* tables to fleet*.
# ---------------------------------------------------------------------------
echo "[6/8] Running Django migrations (garage -> fleet rename will apply here)..."
docker compose -f "$COMPOSE_FILE" run --rm web python /app/src/manage.py migrate --noinput

# ---------------------------------------------------------------------------
# 7. Start web so we can copy media into its volume.
# ---------------------------------------------------------------------------
echo "[7/8] Starting web container..."
docker compose -f "$COMPOSE_FILE" up -d web

# Wait briefly for the container to exist.
for attempt in $(seq 1 30); do
    if docker compose -f "$COMPOSE_FILE" ps -q web >/dev/null 2>&1; then
        break
    fi
    if [[ "$attempt" -eq 30 ]]; then
        echo "Error: web container did not start." >&2
        exit 1
    fi
    sleep 1
done

# ---------------------------------------------------------------------------
# 8. Restore media files.
# ---------------------------------------------------------------------------
echo "[8/8] Restoring media snapshot: $MEDIA_SNAPSHOT..."
docker compose -f "$COMPOSE_FILE" cp "$MEDIA_SNAPSHOT" "web:/tmp/media-snapshot.tar.gz"
docker compose -f "$COMPOSE_FILE" exec -T --user root web tar xzf /tmp/media-snapshot.tar.gz -C /app/src/media
docker compose -f "$COMPOSE_FILE" exec -T --user root web chown -R django:django /app/src/media
docker compose -f "$COMPOSE_FILE" exec -T --user root web rm -f /tmp/media-snapshot.tar.gz

# Rebuild/restart web so it picks up any code changes and runs with restored media.
docker compose -f "$COMPOSE_FILE" up -d --build web

# ---------------------------------------------------------------------------
# Verification.
# ---------------------------------------------------------------------------
echo ""
echo "Restore complete. Running quick verification..."
echo ""
echo "Container status:"
docker compose -f "$COMPOSE_FILE" ps

echo ""
echo "Migration status:"
docker compose -f "$COMPOSE_FILE" run --rm web python /app/src/manage.py showmigrations --list shop car_docs || true

echo ""
echo "Fleet / Car / User counts:"
docker compose -f "$COMPOSE_FILE" exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
SELECT 'fleets' AS entity, COUNT(*) AS n FROM fleet
UNION ALL
SELECT 'cars', COUNT(*) FROM shop_car
UNION ALL
SELECT 'users', COUNT(*) FROM shop_user
UNION ALL
SELECT 'attachments', COUNT(*) FROM shop_attachment;
" || true

echo ""
echo "Done. Safety backups (if any) are in:"
echo "  $DB_BACKUP_DIR/snapshot-pre-restore-$TIMESTAMP.sql.gz"
echo "  $MEDIA_BACKUP_DIR/snapshot-pre-restore-$TIMESTAMP.tar.gz"
