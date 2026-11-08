#!/usr/bin/env sh
# Restore a backup made by scripts/backup_db.sh (docs/operations/DEPLOYMENT.md).
#   restore_db.sh backups/fms-YYYYMMDD-HHMMSS.dump [backups/fms-files-YYYYMMDD-HHMMSS.tar.gz]
# DATABASE_URL must point to the database to overwrite (stop the API first). FILES_DIR,
# when set with a files archive, is emptied then restored.
set -eu

: "${DATABASE_URL:?DATABASE_URL is required}"
dump="${1:?usage: restore_db.sh <dump> [files archive]}"
files_archive="${2:-}"

pg_restore --list "$dump" > /dev/null
# --clean --if-exists: drop then recreate every object of the dump; one transaction, so a
# failed restoration leaves the database as it was.
pg_restore --clean --if-exists --no-owner --single-transaction --exit-on-error \
  --dbname "$DATABASE_URL" "$dump"
echo "Database restored from $dump"

if [ -n "$files_archive" ]; then
  : "${FILES_DIR:?FILES_DIR is required to restore files}"
  find "$FILES_DIR" -mindepth 1 -delete
  tar -xzf "$files_archive" -C "$FILES_DIR"
  echo "Files restored from $files_archive into $FILES_DIR"
fi
