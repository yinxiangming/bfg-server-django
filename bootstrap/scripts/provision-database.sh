#!/usr/bin/env bash
# Create MySQL or PostgreSQL database if missing (requires admin credentials).
set -euo pipefail

DB_TYPE="${1:?db type: mysql|postgres}"
DB_NAME="${2:?database name}"
shift 2

if [[ "$DB_TYPE" == "mysql" ]]; then
  HOST="${MYSQL_HOST:-127.0.0.1}"
  PORT="${MYSQL_PORT:-3306}"
  ADMIN_USER="${MYSQL_ADMIN_USER:?}"
  ADMIN_PASS="${MYSQL_ADMIN_PASSWORD:?}"
  export MYSQL_PWD="$ADMIN_PASS"
  mysql -h"$HOST" -P"$PORT" -u"$ADMIN_USER" -e \
    "CREATE DATABASE IF NOT EXISTS \`${DB_NAME}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
  echo "MySQL database ready: ${DB_NAME}"
elif [[ "$DB_TYPE" == "postgres" ]]; then
  HOST="${POSTGRES_HOST:-127.0.0.1}"
  PORT="${POSTGRES_PORT:-5432}"
  ADMIN_USER="${POSTGRES_ADMIN_USER:?}"
  ADMIN_PASS="${POSTGRES_ADMIN_PASSWORD:?}"
  export PGPASSWORD="$ADMIN_PASS"
  psql -h"$HOST" -p"$PORT" -U"$ADMIN_USER" -d postgres -tc \
    "SELECT 1 FROM pg_database WHERE datname = '${DB_NAME}'" | grep -q 1 \
    || psql -h"$HOST" -p"$PORT" -U"$ADMIN_USER" -d postgres -c \
      "CREATE DATABASE \"${DB_NAME}\" ENCODING 'UTF8';"
  echo "PostgreSQL database ready: ${DB_NAME}"
else
  echo "Unsupported DB_TYPE: $DB_TYPE" >&2
  exit 1
fi
