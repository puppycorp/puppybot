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

# SSH/TTY shells may lack the compositor's environment even while the user's
# desktop is running. Select only an unambiguous socket owned by this user;
# explicit display/backend choices and non-rendering commands stay untouched.
needs_display=1
for arg in "$@"; do
    case "$arg" in
        --headless|--help|--list-cases) needs_display=0 ;;
    esac
done
if (( needs_display )) && [[ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}${SDL_VIDEODRIVER:-}" ]]; then
    display_runtime="${XDG_RUNTIME_DIR:-/run/user/$UID}"
    display_sockets=()
    if [[ -d "$display_runtime" && -O "$display_runtime" ]]; then
        for candidate in "$display_runtime"/wayland-*; do
            if [[ -S "$candidate" && -O "$candidate" ]]; then
                display_sockets+=("$candidate")
            fi
        done
    fi
    if (( ${#display_sockets[@]} == 1 )); then
        export XDG_RUNTIME_DIR="$display_runtime"
        export WAYLAND_DISPLAY="${display_sockets[0]##*/}"
        echo "PuppyBot: using local Wayland display $WAYLAND_DISPLAY." >&2
    else
        echo 'PuppyBot: no display selected. Set WAYLAND_DISPLAY or DISPLAY from your desktop session.' >&2
        echo 'Run from a desktop terminal, or select the display explicitly. --hidden also needs a display.' >&2
        exit 2
    fi
fi

exec "$project_dir/build/flex/puppybot-sim" "$@"
