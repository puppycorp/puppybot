#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$project_dir"

# Export model geometry/shared libraries once. Compile current simulation
# sources on every launch; normal launches do not re-export the large model.
if [[ ! -s build/flex/sim/puppybot.bin || ! -s build/flex/sim/dependencies.flex || ! -s build/flex/sim/dependencies.json ]]; then
    ./flex/scripts/build-sim.sh >&2
else
    compiler="${FLEXSCRIPT_COMPILER:-$project_dir/build/flex/pup-compiler}"
    if [[ -n "${FLEXSCRIPT_COMPILER:-}" && ! -x "$compiler" ]]; then
        echo 'FLEXSCRIPT_COMPILER must name an executable compiler.' >&2
        exit 1
    fi
    if [[ ! -x "$compiler" ]]; then
        compiler="$(command -v flexscript || true)"
    fi
    if [[ -z "$compiler" ]]; then
        compiler="$project_dir/../flexscript/build/flex"
    fi
    if [[ ! -x "$compiler" ]]; then
        echo 'Set FLEXSCRIPT_COMPILER to a verified Flexscript compiler.' >&2
        exit 1
    fi
    export FLEXSCRIPT_ROOT="${FLEXSCRIPT_ROOT:-$project_dir/../flexscript}"
    temporary="$(mktemp -d "$project_dir/build/flex/sim/run.XXXXXXXX")"
    trap 'rm -f "$temporary/puppybot-sim"; rmdir "$temporary"' EXIT
    "$compiler" "$project_dir/flex/sim/main.flex" -o "$temporary/puppybot-sim"
    mv -f "$temporary/puppybot-sim" "$project_dir/build/flex/puppybot-sim"
    rmdir "$temporary"
    trap - EXIT
fi

exec "$project_dir/build/flex/puppybot-sim" "$@"
