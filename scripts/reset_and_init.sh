#!/usr/bin/env bash
# 1) reset_db — drops all tables (DB is empty; django_migrations gone too).
# 2) init — runs migrate, then creates workspace/admin and optional seed (use --seed-data).
#
# Non-interactive password: export INIT_ADMIN_PASSWORD=... before running.
# ENV=prod blocks reset_db.

set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.."

if command -v uv >/dev/null 2>&1; then
  PY=(uv run python)
else
  PY=(python)
fi

"${PY[@]}" manage.py reset_db --no-input
"${PY[@]}" manage.py init --seed-data
