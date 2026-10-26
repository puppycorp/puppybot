#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"
if [[ "${1:-}" == build ]]; then exec bash flex/scripts/build-control.sh; fi
if [[ "${1:-}" == test ]]; then shift; exec bash flex/scripts/test-control.sh "$@"; fi
if [[ ! -x build/flex/control/control ]]; then bash flex/scripts/build-control.sh; fi
if [[ "${1:-}" == collect || "${1:-}" == run ]]; then
    if [[ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}${SDL_VIDEODRIVER:-}" ]]; then
        display_runtime="${XDG_RUNTIME_DIR:-/run/user/$UID}"
        display_sockets=()
        if [[ -d "$display_runtime" && -O "$display_runtime" ]]; then
            for candidate in "$display_runtime"/wayland-*; do
                if [[ -S "$candidate" && -O "$candidate" ]]; then display_sockets+=("$candidate"); fi
            done
        fi
        if (( ${#display_sockets[@]} != 1 )); then
            echo 'Visual control needs a local renderer. Set WAYLAND_DISPLAY or DISPLAY from your desktop session.' >&2
            exit 2
        fi
        export XDG_RUNTIME_DIR="$display_runtime"
        export WAYLAND_DISPLAY="${display_sockets[0]##*/}"
    fi
fi
exec "$project_dir/build/flex/control/control" "$@"
