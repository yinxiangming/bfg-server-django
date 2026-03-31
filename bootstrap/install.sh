#!/usr/bin/env bash
# Curl-friendly installer for BFG bootstrap bundle.
# Usage:
#   curl -fsSL "<raw-install-sh-url>" | BUNDLE_URL="<tar.gz-url>" bash
set -euo pipefail

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

require_cmd curl
require_cmd tar
require_cmd mktemp
require_cmd bash

BUNDLE_URL="${BUNDLE_URL:-https://github.com/yinxiangming/bfg-server-django/archive/refs/heads/main.tar.gz}"

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

ARCHIVE="$WORKDIR/bootstrap.tar.gz"
echo "Downloading bootstrap bundle..."
curl -fsSL "$BUNDLE_URL" -o "$ARCHIVE"

echo "Extracting bundle..."
tar -xzf "$ARCHIVE" -C "$WORKDIR"

BOOTSTRAP_ENTRY="$(python3 - "$WORKDIR" <<'PY'
import sys
from pathlib import Path

root = Path(sys.argv[1])
patterns = [
    "bootstrap/bootstrap-app.sh",
    "src/server/bootstrap/bootstrap-app.sh",
]
matches = []
for pattern in patterns:
    matches.extend(root.rglob(pattern))
if not matches:
    raise SystemExit(1)
print(matches[0].resolve())
PY
)" || {
  echo "Could not find bootstrap-app.sh in bundle." >&2
  exit 1
}

BOOTSTRAP_DIR="$(cd "$(dirname "$BOOTSTRAP_ENTRY")" && pwd)"
echo "Running bootstrap from: $BOOTSTRAP_DIR"

export BOOTSTRAP_DIR
exec bash "$BOOTSTRAP_ENTRY"
