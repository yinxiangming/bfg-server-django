#!/usr/bin/env bash
# Interactive bootstrap for a single BFG instance in the current repo.
set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]:-$0}"
if [[ -f "$SCRIPT_PATH" ]]; then
  BOOTSTRAP_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
else
  BOOTSTRAP_DIR="${BOOTSTRAP_DIR:-}"
fi

if [[ -z "${BOOTSTRAP_DIR}" || ! -d "${BOOTSTRAP_DIR}/docker" ]]; then
  echo "BOOTSTRAP_DIR is not set or bootstrap assets are missing." >&2
  exit 1
fi

# shellcheck source=scripts/lib-env.sh
source "${BOOTSTRAP_DIR}/scripts/lib-env.sh"

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
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
  read -r -s -p "$prompt" s || true
  printf '\n' >&2
  printf '%s\n' "$s"
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
  [[ -n "$runner" ]] || { echo "Docker Compose not found." >&2; exit 1; }
  if [[ "$runner" == "docker compose" ]]; then
    docker compose -f "$compose_file" "$@"
  else
    docker-compose -f "$compose_file" "$@"
  fi
}

ROOT_DIR="$(cd "${BOOTSTRAP_DIR}/.." && pwd)"
SERVER_ENV="${ROOT_DIR}/.env"
ENV_EXAMPLE="${ROOT_DIR}/.env.example"

require_cmd bash
require_cmd python3
require_cmd curl
require_cmd openssl

if [[ ! -f "${ROOT_DIR}/manage.py" ]]; then
  echo "This installer must run from a BFG server checkout (manage.py not found near bootstrap/)." >&2
  exit 1
fi

cat <<'EOF'
=== BFG single-instance bootstrap ===
This installer configures the current server repo as a runnable BFG instance.
EOF

echo ""
echo "Choose setup mode:"
echo "  1) Single workspace"
echo "  2) Embedded platform"
MODE_CHOICE="$(read_line "Choose [1-2]" "2")"
MODE_LABEL="single"
if [[ "$MODE_CHOICE" == "2" ]]; then
  MODE_LABEL="embedded"
fi

SITE_NAME="$(read_line "Site / instance name" "BFG")"
SERVER_PORT="$(read_line "Django runserver port" "8000")"
FRONTEND_URL="$(read_line "Frontend URL" "http://127.0.0.1:3000")"

DB_CHOICE=""
echo ""
echo "Database: 1) SQLite  2) MySQL  3) PostgreSQL"
DB_CHOICE="$(read_line "Choose [1-3]" "1")"

DATABASE_URL=""
MYSQL_HOST="127.0.0.1"
MYSQL_PORT="3306"
MYSQL_USER="root"
MYSQL_PASSWORD=""
MYSQL_DB="bfg"
POSTGRES_HOST="127.0.0.1"
POSTGRES_PORT="5432"
POSTGRES_USER="postgres"
POSTGRES_PASSWORD=""
POSTGRES_DB="bfg"

case "$DB_CHOICE" in
  1|"")
    DATABASE_URL="sqlite:///./db.sqlite3"
    ;;
  2)
    MYSQL_HOST="$(read_line "MySQL host" "127.0.0.1")"
    MYSQL_PORT="$(read_line "MySQL port" "3306")"
    MYSQL_USER="$(read_line "MySQL username" "root")"
    MYSQL_PASSWORD="$(read_secret "MySQL password (input hidden): ")"
    MYSQL_DB="$(read_line "MySQL database" "bfg")"
    DATABASE_URL="mysql://${MYSQL_USER}:${MYSQL_PASSWORD}@${MYSQL_HOST}:${MYSQL_PORT}/${MYSQL_DB}"
    ;;
  3)
    POSTGRES_HOST="$(read_line "PostgreSQL host" "127.0.0.1")"
    POSTGRES_PORT="$(read_line "PostgreSQL port" "5432")"
    POSTGRES_USER="$(read_line "PostgreSQL username" "postgres")"
    POSTGRES_PASSWORD="$(read_secret "PostgreSQL password (input hidden): ")"
    POSTGRES_DB="$(read_line "PostgreSQL database" "bfg")"
    DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}"
    ;;
  *)
    echo "Invalid database choice." >&2
    exit 1
    ;;
esac

DEFAULT_REDIS_URL="redis://127.0.0.1:6379/0"
REDIS_URL_EFFECTIVE="$DEFAULT_REDIS_URL"
MAILPIT_SMTP_PORT="1025"
MAILPIT_UI_PORT="8025"
COMPOSE_FILE="${BOOTSTRAP_DIR}/docker/docker-compose.yml"

if [[ "${SKIP_DOCKER:-0}" != "1" ]]; then
  if ! "${BOOTSTRAP_DIR}/scripts/check-services.sh" redis "$DEFAULT_REDIS_URL"; then
    START_REDIS="$(read_line "Redis not detected. Start Redis via Docker? [y/N]" "n")"
    if [[ "$START_REDIS" =~ ^[yY] ]]; then
      export BFG_BOOTSTRAP_REDIS_PORT="${BFG_BOOTSTRAP_REDIS_PORT:-6380}"
      REDIS_URL_EFFECTIVE="redis://127.0.0.1:${BFG_BOOTSTRAP_REDIS_PORT}/0"
      run_compose "$COMPOSE_FILE" --project-name bfg-instance-deps up -d redis
    fi
  fi

  if ! "${BOOTSTRAP_DIR}/scripts/check-services.sh" mailpit "127.0.0.1" "$MAILPIT_UI_PORT"; then
    START_MAILPIT="$(read_line "Mailpit not detected. Start Mailpit via Docker? [y/N]" "n")"
    if [[ "$START_MAILPIT" =~ ^[yY] ]]; then
      export BFG_BOOTSTRAP_MAILPIT_SMTP_PORT="${BFG_BOOTSTRAP_MAILPIT_SMTP_PORT:-1025}"
      export BFG_BOOTSTRAP_MAILPIT_UI_PORT="${BFG_BOOTSTRAP_MAILPIT_UI_PORT:-8025}"
      MAILPIT_SMTP_PORT="${BFG_BOOTSTRAP_MAILPIT_SMTP_PORT}"
      MAILPIT_UI_PORT="${BFG_BOOTSTRAP_MAILPIT_UI_PORT}"
      run_compose "$COMPOSE_FILE" --project-name bfg-instance-deps up -d mailpit
    fi
  fi
fi

INIT_ADMIN_USERNAME="$(read_line "Admin username" "admin")"
INIT_ADMIN_EMAIL="$(read_line "Admin email" "admin@example.com")"
INIT_ADMIN_PASSWORD="$(read_secret "Admin password (input hidden): ")"
[[ -n "$INIT_ADMIN_PASSWORD" ]] || { echo "Admin password is required." >&2; exit 1; }

if [[ -f "$ENV_EXAMPLE" && ! -f "$SERVER_ENV" ]]; then
  cp "$ENV_EXAMPLE" "$SERVER_ENV"
fi

touch "$SERVER_ENV"
SECRET_KEY_VAL="$(openssl rand -hex 32)"
PLATFORM_API_KEY_VAL="$(openssl rand -hex 24)"

env_upsert "$SERVER_ENV" "ENV" "dev"
env_upsert "$SERVER_ENV" "DEBUG" "True"
env_upsert "$SERVER_ENV" "SECRET_KEY" "$SECRET_KEY_VAL"
env_upsert "$SERVER_ENV" "SITE_NAME" "$SITE_NAME"
env_upsert "$SERVER_ENV" "DATABASE_URL" "$DATABASE_URL"
env_upsert "$SERVER_ENV" "FRONTEND_URL" "$FRONTEND_URL"
env_upsert "$SERVER_ENV" "CELERY_BROKER_URL" "$REDIS_URL_EFFECTIVE"
env_upsert "$SERVER_ENV" "CELERY_RESULT_BACKEND" "$REDIS_URL_EFFECTIVE"
env_upsert "$SERVER_ENV" "EMAIL_BACKEND" "django.core.mail.backends.smtp.EmailBackend"
env_upsert "$SERVER_ENV" "EMAIL_HOST" "127.0.0.1"
env_upsert "$SERVER_ENV" "EMAIL_PORT" "$MAILPIT_SMTP_PORT"
env_upsert "$SERVER_ENV" "EMAIL_USE_TLS" "False"
env_upsert "$SERVER_ENV" "DEFAULT_FROM_EMAIL" "noreply@example.com"
env_upsert "$SERVER_ENV" "BFG_INSTANCE_TYPE" "workspace"

if [[ "$MODE_LABEL" == "embedded" ]]; then
  env_upsert "$SERVER_ENV" "LOCAL_APPS" ""
  env_upsert "$SERVER_ENV" "BFG_EXTENSION_APPS" "bfg.platform"
  env_upsert "$SERVER_ENV" "PLATFORM_EMBEDDED" "True"
  env_upsert "$SERVER_ENV" "PLATFORM_WORKSPACE_SLUG" "admin"
  env_upsert "$SERVER_ENV" "PLATFORM_API_KEY" "$PLATFORM_API_KEY_VAL"
else
  env_upsert "$SERVER_ENV" "LOCAL_APPS" ""
  env_upsert "$SERVER_ENV" "BFG_EXTENSION_APPS" ""
  env_upsert "$SERVER_ENV" "PLATFORM_EMBEDDED" "False"
  env_upsert "$SERVER_ENV" "PLATFORM_WORKSPACE_SLUG" ""
fi

echo "Installing Python dependencies..."
cd "$ROOT_DIR"
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

PY="$ROOT_DIR/.venv/bin/python"
if [[ "$DB_CHOICE" == "3" ]]; then
  "$PY" -m pip install 'psycopg[binary]>=3.1'
fi

echo "Running migrations..."
"$PY" manage.py migrate --noinput

echo "Ensuring admin user..."
"$PY" manage.py shell -c "from django.contrib.auth import get_user_model; User=get_user_model(); u, created = User.objects.get_or_create(username='${INIT_ADMIN_USERNAME}', defaults={'email':'${INIT_ADMIN_EMAIL}','is_superuser':True,'is_staff':True,'is_active':True}); u.email='${INIT_ADMIN_EMAIL}'; u.is_superuser=True; u.is_staff=True; u.is_active=True; u.set_password('${INIT_ADMIN_PASSWORD}'); u.save(); print({'created': created, 'username': u.username, 'email': u.email})"

if [[ "$MODE_LABEL" == "embedded" ]]; then
  echo "Ensuring embedded platform admin workspace..."
  "${PY}" manage.py shell -c "from django.contrib.auth import get_user_model; from django.apps import apps; User=get_user_model(); Workspace=apps.get_model('common','Workspace'); StaffRole=apps.get_model('common','StaffRole'); StaffMember=apps.get_model('common','StaffMember'); u=User.objects.get(username='${INIT_ADMIN_USERNAME}'); ws, _ = Workspace.objects.get_or_create(slug='admin', defaults={'name':'Admin Workspace','is_active':True,'email':'${INIT_ADMIN_EMAIL}'}); role = StaffRole.objects.filter(workspace=ws, code='admin').first(); StaffMember.objects.get_or_create(workspace=ws, user=u, defaults={'role': role, 'is_active': True}); print({'workspace': ws.slug, 'user': u.username})"
  echo "Syncing workspace domains..."
  "${PY}" manage.py sync_workspace_domains --apply || true
fi

echo ""
echo "=== BFG instance ready ==="
echo "Mode:            ${MODE_LABEL}"
echo "Server repo:     ${ROOT_DIR}"
echo "Env file:        ${SERVER_ENV}"
echo "Django:          http://127.0.0.1:${SERVER_PORT}"
echo "Frontend hint:   ${FRONTEND_URL}"
if [[ "$MODE_LABEL" == "embedded" ]]; then
  echo "Platform slug:   admin"
fi

echo ""
echo "Next steps:"
echo "  cd ${ROOT_DIR}"
echo "  source .venv/bin/activate"
echo "  python manage.py runserver 0.0.0.0:${SERVER_PORT}"

echo ""
START_NOW="$(read_line "Start Django now (foreground)? [y/N]" "n")"
if [[ "$START_NOW" =~ ^[yY] ]]; then
  cd "$ROOT_DIR"
  exec "$PY" manage.py runserver "0.0.0.0:${SERVER_PORT}"
fi
