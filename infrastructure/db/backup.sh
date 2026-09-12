#!/bin/bash
# Database backup script
# Usage: ./backup.sh [database_name] [backup_directory]

set -e

DB_NAME=${1:-eabot}
BACKUP_DIR=${2:-./backups}
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

echo "Starting backup of database: $DB_NAME"

pg_dump -U postgres -h localhost -F c -f "$BACKUP_DIR/${DB_NAME}_${TIMESTAMP}.dump" "$DB_NAME"

echo "Backup completed: $BACKUP_DIR/${DB_NAME}_${TIMESTAMP}.dump"
