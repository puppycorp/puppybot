#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(cd "$script_dir/.." && pwd)"

cd "$project_dir"

cargo_cmd=(cargo)
if command -v rustup >/dev/null 2>&1 && rustup toolchain list | grep -q '^stable-'; then
    cargo_cmd=(cargo +stable)
fi

if [[ -n "${PUPPYBOT_RUNTIME_TARGET:-}" ]]; then
    exec "${cargo_cmd[@]}" run -p puppybot-runtime --target "$PUPPYBOT_RUNTIME_TARGET" -- "$@"
fi

exec "${cargo_cmd[@]}" run -p puppybot-runtime -- "$@"
