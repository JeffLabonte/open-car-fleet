#!/bin/bash
# Backup the Django media files from the running Docker volume to
# /opt/backups/media. A new tarball snapshot is created only when the content
# has changed compared with the previous snapshot.
set -euo pipefail

umask 077

BACKUP_DIR="/opt/backups/media"
COMPOSE_FILE="/opt/open-car-fleet/docker-compose.prod.yml"
TEMP_DIR="$(mktemp -d)"
MEDIA_DIR="$TEMP_DIR/media"
MANIFEST="$TEMP_DIR/manifest.sha512"

cleanup() {
    rm -rf "$TEMP_DIR"
}
trap cleanup EXIT

mkdir -p "$BACKUP_DIR" "$MEDIA_DIR"

# Export media from the running web container (named volume mount).
docker compose -f "$COMPOSE_FILE" cp web:/app/src/media/. "$MEDIA_DIR/"

# Build a sorted sha512 manifest of every file, using paths relative to the
# media directory so temporary directory names do not affect comparison.
cd "$MEDIA_DIR"
find . -type f -exec sha512sum {} + | sort > "$MANIFEST"

# Compare with the most recent snapshot manifest.
LATEST_MANIFEST="$(ls -1 "$BACKUP_DIR"/manifest-*.sha512 2>/dev/null | sort | tail -n1 || true)"
if [[ -n "$LATEST_MANIFEST" ]] && diff -q "$LATEST_MANIFEST" "$MANIFEST" >/dev/null 2>&1; then
    echo "$(date -Iseconds) media: no changes since $(basename "$LATEST_MANIFEST"). Skipping."
    exit 0
fi

# Create a new snapshot.
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
SNAPSHOT="$BACKUP_DIR/snapshot-$TIMESTAMP.tar.gz"
tar czf "$SNAPSHOT" -C "$MEDIA_DIR" .
chmod 600 "$SNAPSHOT"
cp "$MANIFEST" "$BACKUP_DIR/manifest-$TIMESTAMP.sha512"
chmod 600 "$BACKUP_DIR/manifest-$TIMESTAMP.sha512"
echo "$(date -Iseconds) media: created $SNAPSHOT"

# Retain only the 10 most recent snapshots + manifests.
cd "$BACKUP_DIR"
ls -1 snapshot-*.tar.gz 2>/dev/null | sort | head -n -10 | xargs -r rm -f
ls -1 manifest-*.sha512 2>/dev/null | sort | head -n -10 | xargs -r rm -f
