#!/usr/bin/env bash
# BFG workspace app bootstrap — creates submodule layout, extension symlinks, env, deps, migrate + init.
set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]:-$0}"
if [[ -f "$SCRIPT_PATH" ]]; then
  BOOTSTRAP_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
else
  BOOTSTRAP_DIR="${BOOTSTRAP_DIR:-}"
fi

if [[ -z "${BOOTSTRAP_DIR}" || ! -d "${BOOTSTRAP_DIR}/templates" ]]; then
  echo "BOOTSTRAP_DIR is not set or templates/ is missing." >&2
  echo "Run this script from a repo checkout, e.g. bash src/server/bootstrap/bootstrap-app.sh" >&2
  exit 1
fi

# shellcheck source=scripts/lib-env.sh
source "${BOOTSTRAP_DIR}/scripts/lib-env.sh"

SUBMODULE_SERVER_URL="${SUBMODULE_SERVER_URL:-https://github.com/yinxiangming/bfg-server-django.git}"
SUBMODULE_CLIENT_URL="${SUBMODULE_CLIENT_URL:-https://github.com/yinxiangming/bfg-client-react.git}"

die() {
  echo "Error: $*" >&2
  exit 1
}

slugify() {
  local raw="$1"
  echo "$raw" | tr '[:upper:]' '[:lower:]' | sed -e 's/[^a-z0-9]+/_/g' -e 's/^_//' -e 's/_$//'
}

validate_slug() {
  [[ "$1" =~ ^[a-z][a-z0-9_]*$ ]] || die "Invalid slug: use [a-z0-9_], start with a letter."
}

read_line() {
  local prompt="$1"
  local default="${2:-}"
  local value
  if [[ -n "$default" ]]; then
    read -r -p "${prompt} [${default}]: " value || true
    echo "${value:-$default}"
  else
    read -r -p "${prompt}: " value || true
    echo "$value"
  fi
}

read_secret() {
  local prompt="$1"
  local s
  if [[ -t 0 ]]; then
    read -r -s -p "$prompt" s || true
    printf '\n' >&2
  else
    read -r s || true
  fi
  printf '%s\n' "$s"
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

detect_compose() {
  if command_exists docker && docker compose version >/dev/null 2>&1; then
    echo "docker compose"
  elif command_exists docker-compose; then
    echo "docker-compose"
  else
    echo ""
  fi
}

run_compose() {
  local compose_file="$1"
  shift
  local runner
  runner="$(detect_compose)"
  [[ -n "$runner" ]] || die "Docker Compose not found."
  if [[ "$runner" == "docker compose" ]]; then
    docker compose -f "$compose_file" "$@"
  else
    docker-compose -f "$compose_file" "$@"
  fi
}

echo "=== BFG application bootstrap ==="
echo "Bootstrap directory: ${BOOTSTRAP_DIR}"

APP_TITLE="$(read_line "Application title (display name)")"
[[ -n "$APP_TITLE" ]] || die "Title is required."

DEFAULT_SLUG="$(slugify "$APP_TITLE")"
RAW_SLUG="$(read_line "Application slug (Python package, letters/digits/underscore)" "$DEFAULT_SLUG")"
APP_SLUG="$(slugify "$RAW_SLUG")"
[[ -n "$APP_SLUG" ]] || die "Slug is required."
validate_slug "$APP_SLUG"

PARENT_DIR="$(read_line "Parent directory for the new app (empty = current directory)" "${PWD}")"
PARENT_DIR="${PARENT_DIR:-$PWD}"
[[ -d "$PARENT_DIR" ]] || die "Parent directory does not exist: $PARENT_DIR"

APP_ROOT="${PARENT_DIR}/${APP_SLUG}"
[[ ! -e "$APP_ROOT" ]] || die "Target already exists: $APP_ROOT"

SERVER_PORT="$(read_line "Django runserver port" "8000")"
CLIENT_PORT="$(read_line "Next.js dev port (for FRONTEND_URL hints)" "3000")"

DEFAULT_API="http://127.0.0.1:${SERVER_PORT}"
API_PUBLIC_URL="$(read_line "API base URL for browser (NEXT_PUBLIC_API_URL)" "$DEFAULT_API")"
API_PUBLIC_URL="${API_PUBLIC_URL%/}"

echo ""
echo "Database: 1) SQLite (default)  2) MySQL  3) PostgreSQL"
DB_CHOICE="$(read_line "Choose [1-3]" "1")"

DB_NAME_DEFAULT="$APP_SLUG"
DB_NAME="$DB_NAME_DEFAULT"
MYSQL_HOST="127.0.0.1"
MYSQL_PORT="3306"
MYSQL_USER=""
MYSQL_PASSWORD=""
MYSQL_ADMIN_USER=""
MYSQL_ADMIN_PASSWORD=""
POSTGRES_HOST="127.0.0.1"
POSTGRES_PORT="5432"
POSTGRES_USER=""
POSTGRES_PASSWORD=""
POSTGRES_ADMIN_USER=""
POSTGRES_ADMIN_PASSWORD=""
DATABASE_URL=""

case "$DB_CHOICE" in
  1|"")
    DATABASE_URL="sqlite:///./db.sqlite3"
    ;;
  2)
    echo "MySQL connection (app user — used in DATABASE_URL):"
    MYSQL_HOST="$(read_line "MySQL host" "127.0.0.1")"
    MYSQL_PORT="$(read_line "MySQL port" "3306")"
    MYSQL_USER="$(read_line "MySQL username" "bfg")"
    MYSQL_PASSWORD="$(read_secret "MySQL password for app user (input hidden): ")"
    DB_NAME="$(read_line "Database name" "$DB_NAME_DEFAULT")"
    echo "MySQL admin (for CREATE DATABASE if needed):"
    MYSQL_ADMIN_USER="$(read_line "Admin username" "root")"
    MYSQL_ADMIN_PASSWORD="$(read_secret "MySQL admin password (for CREATE DATABASE, input hidden): ")"
    DATABASE_URL="mysql://${MYSQL_USER}:${MYSQL_PASSWORD}@${MYSQL_HOST}:${MYSQL_PORT}/${DB_NAME}"
    ;;
  3)
    echo "PostgreSQL connection (app user):"
    POSTGRES_HOST="$(read_line "PostgreSQL host" "127.0.0.1")"
    POSTGRES_PORT="$(read_line "PostgreSQL port" "5432")"
    POSTGRES_USER="$(read_line "PostgreSQL username" "bfg")"
    POSTGRES_PASSWORD="$(read_secret "PostgreSQL password for app user (input hidden): ")"
    DB_NAME="$(read_line "Database name" "$DB_NAME_DEFAULT")"
    echo "PostgreSQL admin (superuser for CREATE DATABASE):"
    POSTGRES_ADMIN_USER="$(read_line "Admin username" "postgres")"
    POSTGRES_ADMIN_PASSWORD="$(read_secret "PostgreSQL admin password (for CREATE DATABASE, input hidden): ")"
    DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${DB_NAME}"
    ;;
  *)
    die "Invalid database choice."
    ;;
esac

echo ""
echo "Optional: OpenAI (leave empty to skip)."
OPENAI_API_KEY_INPUT="$(read_line "OPENAI_API_KEY (optional)")"
OPENAI_MODEL_INPUT="$(read_line "OPENAI_MODEL" "gpt-4o-mini")"

echo ""
echo "Redis / Mailpit: used for Celery and email testing."
DEFAULT_REDIS_URL="redis://127.0.0.1:6379/0"
REDIS_URL_EFFECTIVE="$DEFAULT_REDIS_URL"
MAILPIT_SMTP_PORT="1025"
MAILPIT_UI_PORT="8025"

if "${BOOTSTRAP_DIR}/scripts/check-services.sh" redis "$DEFAULT_REDIS_URL"; then
  echo "Detected Redis on ${DEFAULT_REDIS_URL}."
else
  echo "Redis not reachable at ${DEFAULT_REDIS_URL}."
  if [[ "${SKIP_DOCKER:-0}" != "1" ]]; then
    START_REDIS="$(read_line "Start Redis via Docker? [y/N]" "n")"
    if [[ "$START_REDIS" =~ ^[yY] ]]; then
      export BFG_BOOTSTRAP_REDIS_PORT="${BFG_BOOTSTRAP_REDIS_PORT:-6380}"
      REDIS_URL_EFFECTIVE="redis://127.0.0.1:${BFG_BOOTSTRAP_REDIS_PORT}/0"
      COMPOSE_FILE="${BOOTSTRAP_DIR}/docker/docker-compose.yml"
      run_compose "$COMPOSE_FILE" --project-name "bfg-${APP_SLUG}-deps" up -d redis
    fi
  fi
fi

if "${BOOTSTRAP_DIR}/scripts/check-services.sh" mailpit "127.0.0.1" "$MAILPIT_UI_PORT"; then
  echo "Mailpit UI detected on port ${MAILPIT_UI_PORT}."
else
  if [[ "${SKIP_DOCKER:-0}" != "1" ]]; then
    MP="$(read_line "Start Mailpit via Docker? [y/N]" "n")"
    if [[ "$MP" =~ ^[yY] ]]; then
      export BFG_BOOTSTRAP_MAILPIT_SMTP_PORT="${BFG_BOOTSTRAP_MAILPIT_SMTP_PORT:-1025}"
      export BFG_BOOTSTRAP_MAILPIT_UI_PORT="${BFG_BOOTSTRAP_MAILPIT_UI_PORT:-8025}"
      COMPOSE_FILE="${BOOTSTRAP_DIR}/docker/docker-compose.yml"
      run_compose "$COMPOSE_FILE" --project-name "bfg-${APP_SLUG}-deps" up -d mailpit
    fi
  fi
fi

USE_DOCKER_DB="n"
if [[ "$DB_CHOICE" == "2" || "$DB_CHOICE" == "3" ]]; then
  echo ""
  USE_DOCKER_DB="$(read_line "Start database (${DB_CHOICE}) via Docker (see bootstrap/docker)? [y/N]" "n")"
fi

if [[ "$USE_DOCKER_DB" =~ ^[yY] ]]; then
  COMPOSE_FILE="${BOOTSTRAP_DIR}/docker/docker-compose.yml"
  if [[ "$DB_CHOICE" == "2" ]]; then
    export BFG_BOOTSTRAP_MYSQL_PORT="${BFG_BOOTSTRAP_MYSQL_PORT:-3308}"
    export BFG_BOOTSTRAP_MYSQL_DATABASE="$DB_NAME"
    export BFG_BOOTSTRAP_MYSQL_USER="${MYSQL_USER:-bfg}"
    export BFG_BOOTSTRAP_MYSQL_PASSWORD="${MYSQL_PASSWORD:-bfg}"
    export BFG_BOOTSTRAP_MYSQL_ROOT_PASSWORD="${MYSQL_ADMIN_PASSWORD:-root}"
    MYSQL_HOST="127.0.0.1"
    MYSQL_PORT="${BFG_BOOTSTRAP_MYSQL_PORT}"
    DATABASE_URL="mysql://${BFG_BOOTSTRAP_MYSQL_USER}:${BFG_BOOTSTRAP_MYSQL_PASSWORD}@${MYSQL_HOST}:${MYSQL_PORT}/${DB_NAME}"
    run_compose "$COMPOSE_FILE" --project-name "bfg-${APP_SLUG}-db" --profile mysql up -d mysql
    echo "Waiting for MySQL to accept connections..."
    for _ in $(seq 1 40); do
      if command_exists mysql && MYSQL_PWD="${MYSQL_ADMIN_PASSWORD:-root}" mysql -h"$MYSQL_HOST" -P"$MYSQL_PORT" -u"${MYSQL_ADMIN_USER:-root}" -e "SELECT 1" >/dev/null 2>&1; then
        break
      fi
      sleep 2
    done
  elif [[ "$DB_CHOICE" == "3" ]]; then
    export BFG_BOOTSTRAP_POSTGRES_PORT="${BFG_BOOTSTRAP_POSTGRES_PORT:-5433}"
    export BFG_BOOTSTRAP_POSTGRES_DB="$DB_NAME"
    export BFG_BOOTSTRAP_POSTGRES_USER="${POSTGRES_USER:-bfg}"
    export BFG_BOOTSTRAP_POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-bfg}"
    POSTGRES_HOST="127.0.0.1"
    POSTGRES_PORT="${BFG_BOOTSTRAP_POSTGRES_PORT}"
    DATABASE_URL="postgresql://${BFG_BOOTSTRAP_POSTGRES_USER}:${BFG_BOOTSTRAP_POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${DB_NAME}"
    run_compose "$COMPOSE_FILE" --project-name "bfg-${APP_SLUG}-db" --profile postgres up -d postgres
    echo "Waiting for PostgreSQL..."
    for _ in $(seq 1 40); do
      if command_exists psql && PGPASSWORD="${POSTGRES_ADMIN_PASSWORD:-postgres}" psql -h"$POSTGRES_HOST" -p"$POSTGRES_PORT" -U"${POSTGRES_ADMIN_USER:-postgres}" -d postgres -c "SELECT 1" >/dev/null 2>&1; then
        break
      fi
      sleep 2
    done
  fi
elif [[ "$DB_CHOICE" == "2" && -n "${MYSQL_ADMIN_USER:-}" ]]; then
  if command_exists mysql; then
    echo "Creating MySQL database if missing..."
    MYSQL_PWD="$MYSQL_ADMIN_PASSWORD" mysql -h"$MYSQL_HOST" -P"$MYSQL_PORT" -u"$MYSQL_ADMIN_USER" -e \
      "CREATE DATABASE IF NOT EXISTS \`${DB_NAME}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;" || true
    echo "Granting privileges (best-effort)..."
    MYSQL_PWD="$MYSQL_ADMIN_PASSWORD" mysql -h"$MYSQL_HOST" -P"$MYSQL_PORT" -u"$MYSQL_ADMIN_USER" -e \
      "CREATE USER IF NOT EXISTS '${MYSQL_USER}'@'%' IDENTIFIED BY '${MYSQL_PASSWORD}'; GRANT ALL ON \`${DB_NAME}\`.* TO '${MYSQL_USER}'@'%'; FLUSH PRIVILEGES;" || true
  else
    echo "mysql client not found; ensure database ${DB_NAME} exists." >&2
  fi
elif [[ "$DB_CHOICE" == "3" && -n "${POSTGRES_ADMIN_USER:-}" ]]; then
  if command_exists psql; then
    echo "Creating PostgreSQL database if missing..."
    PGPASSWORD="$POSTGRES_ADMIN_PASSWORD" psql -h"$POSTGRES_HOST" -p"$POSTGRES_PORT" -U"$POSTGRES_ADMIN_USER" -d postgres -tc \
      "SELECT 1 FROM pg_database WHERE datname = '${DB_NAME}'" | grep -q 1 \
      || PGPASSWORD="$POSTGRES_ADMIN_PASSWORD" psql -h"$POSTGRES_HOST" -p"$POSTGRES_PORT" -U"$POSTGRES_ADMIN_USER" -d postgres -c \
        "CREATE DATABASE \"${DB_NAME}\" ENCODING 'UTF8';"
    PGPASSWORD="$POSTGRES_ADMIN_PASSWORD" psql -h"$POSTGRES_HOST" -p"$POSTGRES_PORT" -U"$POSTGRES_ADMIN_USER" -d postgres -c \
      "DO \$\$ BEGIN CREATE USER \"${POSTGRES_USER}\" WITH PASSWORD '${POSTGRES_PASSWORD}'; EXCEPTION WHEN duplicate_object THEN NULL; END \$\$;" || true
    PGPASSWORD="$POSTGRES_ADMIN_PASSWORD" psql -h"$POSTGRES_HOST" -p"$POSTGRES_PORT" -U"$POSTGRES_ADMIN_USER" -d postgres -c \
      "GRANT ALL PRIVILEGES ON DATABASE \"${DB_NAME}\" TO \"${POSTGRES_USER}\";" || true
  else
    echo "psql not found; ensure database ${DB_NAME} exists." >&2
  fi
fi

echo ""
echo "Creating project at ${APP_ROOT}"
mkdir -p "${APP_ROOT}/src" "${APP_ROOT}/docs" "${APP_ROOT}/extensions"

cat > "${APP_ROOT}/.gitignore" <<'EOF'
.DS_Store
.env
.env.*
!.env.example

# Python
__pycache__/
*.py[cod]
.venv/
venv/

# Node
node_modules/
.next/

# Build / tooling
dist/
coverage/
.pytest_cache/
EOF

if [[ "${SKIP_GIT_INIT:-0}" != "1" ]]; then
  git -C "$APP_ROOT" init
fi

echo "Adding git submodules..."
git -C "$APP_ROOT" submodule add "$SUBMODULE_SERVER_URL" src/server
git -C "$APP_ROOT" submodule add "$SUBMODULE_CLIENT_URL" src/client

if [[ "$DB_CHOICE" == "1" || -z "$DB_CHOICE" ]]; then
  echo "Applying SQLite compatibility patch for Django settings..."
  APP_ROOT_SQLITE="$APP_ROOT" python3 <<'PY'
from pathlib import Path
import os

path = Path(os.environ["APP_ROOT_SQLITE"]) / "src/server/config/settings.py"
text = path.read_text(encoding="utf-8")
needle = "db_from_env = dj_database_url.config(conn_max_age=500)\nif db_from_env:\n    DATABASES['default'].update(db_from_env)\n"
if needle in text and "DATABASES['default'].pop('OPTIONS', None)" not in text:
    text = text.replace(
        needle,
        needle + "if DATABASES['default'].get('ENGINE') == 'django.db.backends.sqlite3':\n    DATABASES['default'].pop('OPTIONS', None)\n",
    )
    path.write_text(text, encoding="utf-8")
PY
fi

echo "Rendering extension templates..."
python3 "${BOOTSTRAP_DIR}/scripts/render_templates.py" \
  "${BOOTSTRAP_DIR}/templates/server" \
  "${APP_ROOT}/extensions/${APP_SLUG}-server" \
  --slug "$APP_SLUG" \
  --title "$APP_TITLE"

python3 "${BOOTSTRAP_DIR}/scripts/render_templates.py" \
  "${BOOTSTRAP_DIR}/templates/client" \
  "${APP_ROOT}/extensions/${APP_SLUG}-client" \
  --slug "$APP_SLUG" \
  --title "$APP_TITLE"

echo "Installing reference extension templates under server/client..."
mkdir -p "${APP_ROOT}/src/server/_extension_template"
mkdir -p "${APP_ROOT}/src/client/src/_extension_template"
python3 "${BOOTSTRAP_DIR}/scripts/render_templates.py" \
  "${BOOTSTRAP_DIR}/templates/server" \
  "${APP_ROOT}/src/server/_extension_template/server" \
  --slug "myapp" \
  --title "Extension template (copy and rename)"

python3 "${BOOTSTRAP_DIR}/scripts/render_templates.py" \
  "${BOOTSTRAP_DIR}/templates/client" \
  "${APP_ROOT}/src/client/src/_extension_template/client" \
  --slug "myapp" \
  --title "Extension template (copy and rename)"

echo "Linking extensions into submodule apps/plugins..."
mkdir -p "${APP_ROOT}/src/server/apps"
mkdir -p "${APP_ROOT}/src/client/src/plugins"
ln -snf "${APP_ROOT}/extensions/${APP_SLUG}-server" "${APP_ROOT}/src/server/apps/${APP_SLUG}"
ln -snf "${APP_ROOT}/extensions/${APP_SLUG}-client" "${APP_ROOT}/src/client/src/plugins/${APP_SLUG}"

MAILPIT_SMTP_PORT_EFFECTIVE="${BFG_BOOTSTRAP_MAILPIT_SMTP_PORT:-1025}"
MAILPIT_UI_PORT_EFFECTIVE="${BFG_BOOTSTRAP_MAILPIT_UI_PORT:-8025}"

SERVER_ENV="${APP_ROOT}/src/server/.env"
CLIENT_ENV="${APP_ROOT}/src/client/.env.local"
SECRET_KEY_VAL="$(openssl rand -hex 32)"

rm -f "$SERVER_ENV" "$CLIENT_ENV"
touch "$SERVER_ENV" "$CLIENT_ENV"

env_upsert "$SERVER_ENV" "ENV" "dev"
env_upsert "$SERVER_ENV" "DEBUG" "True"
env_upsert "$SERVER_ENV" "SECRET_KEY" "$SECRET_KEY_VAL"
env_upsert "$SERVER_ENV" "DATABASE_URL" "$DATABASE_URL"
env_upsert "$SERVER_ENV" "FRONTEND_URL" "http://127.0.0.1:${CLIENT_PORT}"
env_upsert "$SERVER_ENV" "SITE_NAME" "$APP_TITLE"
env_upsert "$SERVER_ENV" "BFG_INSTANCE_TYPE" "workspace"
env_upsert "$SERVER_ENV" "LOCAL_APPS" "$APP_SLUG"
env_upsert "$SERVER_ENV" "CELERY_BROKER_URL" "$REDIS_URL_EFFECTIVE"
env_upsert "$SERVER_ENV" "CELERY_RESULT_BACKEND" "$REDIS_URL_EFFECTIVE"
env_upsert "$SERVER_ENV" "EMAIL_BACKEND" "django.core.mail.backends.smtp.EmailBackend"
env_upsert "$SERVER_ENV" "EMAIL_HOST" "127.0.0.1"
env_upsert "$SERVER_ENV" "EMAIL_PORT" "${MAILPIT_SMTP_PORT_EFFECTIVE}"
env_upsert "$SERVER_ENV" "EMAIL_USE_TLS" "False"
env_upsert "$SERVER_ENV" "DEFAULT_FROM_EMAIL" "noreply@example.com"

if [[ -n "$OPENAI_API_KEY_INPUT" ]]; then
  env_upsert "$SERVER_ENV" "OPENAI_API_KEY" "$OPENAI_API_KEY_INPUT"
fi
env_upsert "$SERVER_ENV" "OPENAI_MODEL" "$OPENAI_MODEL_INPUT"

env_upsert "$CLIENT_ENV" "NEXT_PUBLIC_API_URL" "$API_PUBLIC_URL"
env_upsert "$CLIENT_ENV" "ENABLED_PLUGINS" "$APP_SLUG"
env_upsert "$CLIENT_ENV" "NEXT_PUBLIC_ENABLED_PLUGINS" "$APP_SLUG"

if [[ -f "${APP_ROOT}/src/client/.env.example" ]]; then
  cp "${APP_ROOT}/src/client/.env.example" "${APP_ROOT}/src/client/.env.example.bak.bootstrap" 2>/dev/null || true
fi

echo "Installing Python dependencies..."
cd "${APP_ROOT}/src/server"
if command_exists uv; then
  uv venv .venv
  # shellcheck disable=SC1091
  source .venv/bin/activate
  uv pip install -r requirements.txt
else
  python3 -m venv .venv
  # shellcheck disable=SC1091
  source .venv/bin/activate
  pip install -r requirements.txt
fi

PY="${APP_ROOT}/src/server/.venv/bin/python"
if [[ "$DB_CHOICE" == "3" ]]; then
  echo "Installing PostgreSQL driver (psycopg)..."
  "$PY" -m pip install 'psycopg[binary]>=3.1'
fi

echo "Installing Node dependencies..."
cd "${APP_ROOT}/src/client"
npm install

echo "Regenerating plugin loaders..."
node scripts/prepare.js

echo "Running migrations..."
cd "${APP_ROOT}/src/server"
"$PY" manage.py migrate --noinput

echo ""
echo "Preparing admin passwords for init/seed..."
if [[ -z "${INIT_ADMIN_PASSWORD:-}" && -t 0 ]]; then
  echo "Password step 1/2: admin password for manage.py init (default admin user)."
  INIT_ADMIN_PASSWORD="$(read_secret "Enter INIT admin password (input hidden): ")"
fi

if [[ -z "${ADMIN_PASSWORD:-}" ]]; then
  if [[ -n "${INIT_ADMIN_PASSWORD:-}" ]]; then
    echo "Password step 2/2: seed_data admin password reused from INIT admin password."
    ADMIN_PASSWORD="${INIT_ADMIN_PASSWORD}"
  elif [[ -t 0 ]]; then
    echo "Password step 2/2: password used by seed_data to create/update admin."
    ADMIN_PASSWORD="$(read_secret "Enter ADMIN_PASSWORD for seed_data (input hidden): ")"
  fi
fi
export ADMIN_PASSWORD

echo "Running manage.py init (workspace + admin + optional seed)."
set +e
if [[ -n "${INIT_ADMIN_PASSWORD:-}" ]]; then
  INIT_ADMIN_USERNAME_EFFECTIVE="${INIT_ADMIN_USERNAME:-admin}"
  printf '%s\n%s\n' "${INIT_ADMIN_PASSWORD}" "${INIT_ADMIN_PASSWORD}" | \
    "$PY" manage.py init --no-migrate --seed-data --admin "${INIT_ADMIN_USERNAME_EFFECTIVE}"
else
  "$PY" manage.py init --no-migrate --seed-data
fi
INIT_RC=$?
set -e
if [[ "$INIT_RC" -ne 0 ]]; then
  echo "init exited with ${INIT_RC}. Fix errors above or run: cd ${APP_ROOT}/src/server && python manage.py init --no-migrate --seed-data" >&2
fi

mkdir -p "${APP_ROOT}/.vscode"
TASKS_FILE="${APP_ROOT}/.vscode/tasks.json"
export TASKS_FILE
export APP_SLUG
export SERVER_PORT
export CLIENT_PORT
python3 <<'PY'
import json, os
from pathlib import Path
path = Path(os.environ["TASKS_FILE"])
slug = os.environ["APP_SLUG"]
sp = os.environ["SERVER_PORT"]
cp = os.environ["CLIENT_PORT"]
tasks = {
  "version": "2.0.0",
  "tasks": [
    {
      "label": f"{slug}: backend ({sp})",
      "type": "shell",
      "command": ".venv/bin/python manage.py runserver 0.0.0.0:" + sp,
      "options": {
        "cwd": "${workspaceFolder}/src/server",
        "env": {"LOCAL_APPS": slug},
      },
      "isBackground": True,
      "problemMatcher": [],
    },
    {
      "label": f"{slug}: celery worker",
      "type": "shell",
      "command": ".venv/bin/celery -A config worker -l info",
      "options": {
        "cwd": "${workspaceFolder}/src/server",
        "env": {"LOCAL_APPS": slug},
      },
      "isBackground": True,
      "problemMatcher": [],
    },
    {
      "label": f"{slug}: client ({cp})",
      "type": "shell",
      "command": "npm run dev -- -p " + cp,
      "options": {"cwd": "${workspaceFolder}/src/client"},
      "isBackground": True,
      "problemMatcher": [],
    },
    {
      "label": f"{slug}: start all",
      "dependsOn": [
        f"{slug}: backend ({sp})",
        f"{slug}: celery worker",
        f"{slug}: client ({cp})",
      ],
      "dependsOrder": "parallel",
      "problemMatcher": [],
    },
  ],
}
path.write_text(json.dumps(tasks, indent=2) + "\n", encoding="utf-8")
PY

echo "Cleaning Python caches in extension directories..."
find "${APP_ROOT}/extensions" -type d -name "__pycache__" -prune -exec rm -rf {} +
find "${APP_ROOT}/extensions" -type f -name "*.pyc" -delete

echo ""
echo "=== Done ==="
echo "App root:        ${APP_ROOT}"
echo "Server env:      ${SERVER_ENV}"
echo "Client env:      ${CLIENT_ENV}"
echo "API analyze:     ${API_PUBLIC_URL}/api/v1/${APP_SLUG}/ai/analyze/"
echo "VS Code tasks:   ${TASKS_FILE}"

START_NOW="$(read_line "Start Django now (foreground)? [y/N]" "n")"
if [[ "$START_NOW" =~ ^[yY] ]]; then
  cd "${APP_ROOT}/src/server"
  exec "${APP_ROOT}/src/server/.venv/bin/python" manage.py runserver "0.0.0.0:${SERVER_PORT}"
fi
