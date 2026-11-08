#!/usr/bin/env sh
# Daily backup (ARCHITECTURE.md §13, docs/operations/DEPLOYMENT.md):
# - PostgreSQL: compressed custom-format dump, checked by listing its contents;
# - stored files (FILES_DIR, optional): technical sheets, receipts, photos;
# - retention of RETENTION_DAYS days (30 by default).
# Restore with scripts/restore_db.sh; the restoration must be tested regularly.
set -eu

: "${DATABASE_URL:?DATABASE_URL is required}"
BACKUP_DIR="${BACKUP_DIR:-backups}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
stamp="$(date -u +%Y%m%d-%H%M%S)"

mkdir -p "$BACKUP_DIR"
target="$BACKUP_DIR/fms-$stamp.dump"
pg_dump --format=custom --no-owner --file "$target" "$DATABASE_URL"
# A dump that cannot be listed is not a backup.
pg_restore --list "$target" > /dev/null
echo "Database backup written to $target"

if [ -n "${FILES_DIR:-}" ] && [ -d "$FILES_DIR" ]; then
  files_target="$BACKUP_DIR/fms-files-$stamp.tar.gz"
  tar -czf "$files_target" -C "$FILES_DIR" .
  tar -tzf "$files_target" > /dev/null
  echo "Files backup written to $files_target"
fi

find "$BACKUP_DIR" -name 'fms-*' -mtime +"$RETENTION_DAYS" -delete
