#!/usr/bin/env sh
# Daily PostgreSQL backup (ARCHITECTURE.md §13): compressed custom-format dump with a
# 30-day retention. Restoration must be tested regularly:
#   pg_restore --clean --if-exists -d "$DATABASE_URL" backups/fms-YYYYMMDD-HHMMSS.dump
set -eu

: "${DATABASE_URL:?DATABASE_URL is required}"
BACKUP_DIR="${BACKUP_DIR:-backups}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"

mkdir -p "$BACKUP_DIR"
target="$BACKUP_DIR/fms-$(date -u +%Y%m%d-%H%M%S).dump"
pg_dump --format=custom --no-owner --file "$target" "$DATABASE_URL"
# A dump that cannot be listed is not a backup.
pg_restore --list "$target" > /dev/null
find "$BACKUP_DIR" -name 'fms-*.dump' -mtime +"$RETENTION_DAYS" -delete
echo "Backup written to $target"
