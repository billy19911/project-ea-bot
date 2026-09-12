#!/bin/bash
# Database restore script
# Usage: ./restore.sh [backup_file] [database_name]

set -e

BACKUP_FILE=$1
DB_NAME=${2:-eabot}

if [ ! -f "$BACKUP_FILE" ]; then
    echo "Error: Backup file not found: $BACKUP_FILE"
    exit 1
fi

echo "Restoring database: $DB_NAME from $BACKUP_FILE"

pg_restore -U postgres -h localhost -d "$DB_NAME" -c "$BACKUP_FILE"

echo "Restore completed successfully"
