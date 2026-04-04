#!/usr/bin/env bash
# Probe Redis (TCP) and Mailpit UI (HTTP). Exits 0 if reachable.
set -euo pipefail

redis_ok() {
  local url="${1:-redis://127.0.0.1:6379/0}"
  python3 - "$url" <<'PY' 2>/dev/null || return 1
import os, socket, sys
from urllib.parse import urlparse
u = urlparse(sys.argv[1])
host = u.hostname or "127.0.0.1"
port = u.port or 6379
s = socket.socket()
s.settimeout(1.0)
try:
    s.connect((host, port))
except OSError:
    sys.exit(1)
finally:
    s.close()
PY
}

mailpit_ok() {
  local host="${1:-127.0.0.1}"
  local port="${2:-8025}"
  python3 - "$host" "$port" <<'PY' 2>/dev/null || return 1
import socket, sys
s = socket.socket()
s.settimeout(1.0)
try:
    s.connect((sys.argv[1], int(sys.argv[2])))
except OSError:
    sys.exit(1)
finally:
    s.close()
PY
}

case "${1:-}" in
  redis)
    redis_ok "${2:-redis://127.0.0.1:6379/0}"
    ;;
  mailpit)
    mailpit_ok "${2:-127.0.0.1}" "${3:-8025}"
    ;;
  *)
    echo "Usage: $0 redis [REDIS_URL] | mailpit [HOST] [PORT]" >&2
    exit 2
    ;;
esac
