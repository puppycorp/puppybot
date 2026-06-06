#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(cd "$script_dir/.." && pwd)"

cd "$project_dir"

if command -v rustup >/dev/null 2>&1 && rustup toolchain list | grep -q '^stable-'; then
    cargo_cmd=(cargo +stable)
else
    cargo_cmd=(cargo)
fi

exec "${cargo_cmd[@]}" run -p puppybot-runtime \
    --config 'build.target="x86_64-unknown-linux-gnu"' \
    --config 'unstable.build-std=[]' \
    -- "$@"
