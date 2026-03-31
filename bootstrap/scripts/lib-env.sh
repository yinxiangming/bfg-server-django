#!/usr/bin/env bash
# Shared helpers for env file updates (single source for key=value writes).

set -euo pipefail

# Upsert KEY=value in a dotenv-style file. Does not duplicate key reads in callers.
env_upsert() {
  local file="$1"
  local key="$2"
  local value="$3"
  local tmp
  tmp="$(mktemp)"
  if [[ -f "$file" ]]; then
    if grep -q "^${key}=" "$file" 2>/dev/null; then
      awk -v k="$key" -v v="$value" '
        BEGIN { done = 0 }
        $0 ~ "^" k "=" { print k "=" v; done = 1; next }
        { print }
        END { if (!done) print k "=" v }
      ' "$file" >"$tmp"
    else
      cat "$file" >"$tmp"
      printf '%s=%s\n' "$key" "$value" >>"$tmp"
    fi
  else
    printf '%s=%s\n' "$key" "$value" >"$tmp"
  fi
  mv "$tmp" "$file"
}
