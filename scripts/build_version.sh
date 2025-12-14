#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:-version}"

ensure_length() {
  local value="$1"
  if [ ${#value} -gt 50 ]; then
    printf 'Warning: %s is longer than 50 characters and will be truncated.\n' "$2" >&2
    value="${value:0:50}"
  fi
  printf '%s' "$value"
}

case "$MODE" in
version)
  VALUE="${VERSION:-}"
  if [ -z "$VALUE" ]; then
    if git -C "$ROOT_DIR" rev-parse --short=8 HEAD >/dev/null 2>&1; then
      VALUE="$(git -C "$ROOT_DIR" rev-parse --short=8 HEAD)"
    else
      VALUE="unknown"
    fi
  fi
  ensure_length "$VALUE" "VERSION"
  ;;
name)
  VALUE="${NAME:-puppybot}"
  ensure_length "$VALUE" "NAME"
  ;;
*)
  printf 'Unknown argument: %s\n' "$MODE" >&2
  exit 1
  ;;
esac
