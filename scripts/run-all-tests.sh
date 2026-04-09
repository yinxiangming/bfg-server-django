#!/usr/bin/env bash
set -euo pipefail

SERVER_DIR="/Users/mac/Projects/nexus/src/server"
E2E_DIR="/Users/mac/Projects/bfg2/bfg-server-test-e2e"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/run-all-tests.sh                # run unit + seed_data import + e2e
  ./scripts/run-all-tests.sh --skip-unit
  ./scripts/run-all-tests.sh --skip-seed
  ./scripts/run-all-tests.sh --skip-e2e
  ./scripts/run-all-tests.sh --unit-only
  ./scripts/run-all-tests.sh --seed-only
  ./scripts/run-all-tests.sh --e2e-only
EOF
}

RUN_UNIT=1
RUN_SEED=1
RUN_E2E=1

for arg in "$@"; do
  case "$arg" in
    --skip-unit) RUN_UNIT=0 ;;
    --skip-seed) RUN_SEED=0 ;;
    --skip-e2e) RUN_E2E=0 ;;
    --unit-only) RUN_UNIT=1; RUN_SEED=0; RUN_E2E=0 ;;
    --seed-only) RUN_UNIT=0; RUN_SEED=1; RUN_E2E=0 ;;
    --e2e-only) RUN_UNIT=0; RUN_SEED=0; RUN_E2E=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $arg"; usage; exit 1 ;;
  esac
done

PY="$SERVER_DIR/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY="$(command -v python3)"
fi

echo "==> Server dir: $SERVER_DIR"
echo "==> E2E dir: $E2E_DIR"

action_unit() {
  echo "\n==> Running unit/integration tests (server)"
  cd "$SERVER_DIR"
  "$PY" -m pytest bfg2/tests
}

action_seed() {
  echo "\n==> Running seed/bootstrap smoke checks"
  cd "$SERVER_DIR"
  "$PY" manage.py check
  "$PY" manage.py migrate --noinput
  "$PY" manage.py init --help >/dev/null
}

action_e2e() {
  echo "\n==> Running E2E tests"
  cd "$E2E_DIR"
  E2E_PY="$E2E_DIR/.venv/bin/python"
  if [[ ! -x "$E2E_PY" ]]; then
    E2E_PY="$(command -v python3)"
  fi
  "$E2E_PY" -m pytest e2e
}

[[ "$RUN_UNIT" == "1" ]] && action_unit
[[ "$RUN_SEED" == "1" ]] && action_seed
[[ "$RUN_E2E" == "1" ]] && action_e2e

echo "\n✅ All requested test stages finished."
