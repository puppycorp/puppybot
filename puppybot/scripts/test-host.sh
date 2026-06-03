#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(cd "$script_dir/.." && pwd)"

cd "$project_dir"

cargo_cmd=(cargo)
if rustup toolchain list | grep -q '^stable-'; then
    cargo_cmd=(cargo +stable)
fi

"${cargo_cmd[@]}" test \
    --config 'build.target="x86_64-unknown-linux-gnu"' \
    --config 'unstable.build-std=[]' \
    --no-default-features \
    --features host \
    --lib \
    "$@"

if [ "$#" -ne 0 ]; then
    exit 0
fi

host_addr="127.0.0.1:18080"
host_log="$(mktemp)"
PUPPYBOT_HOST_ADDR="$host_addr" "${cargo_cmd[@]}" run \
    --config 'build.target="x86_64-unknown-linux-gnu"' \
    --config 'unstable.build-std=[]' \
    --no-default-features \
    --features host \
    >"$host_log" 2>&1 &
host_pid="$!"
cleanup() {
    kill "$host_pid" >/dev/null 2>&1 || true
    wait "$host_pid" >/dev/null 2>&1 || true
    rm -f "$host_log"
}
trap cleanup EXIT

deadline=$((SECONDS + 15))
while true; do
    if ! kill -0 "$host_pid" >/dev/null 2>&1; then
        cat "$host_log" >&2
        echo "host process exited before WebSocket smoke test" >&2
        exit 1
    fi

    if { exec 3<>"/dev/tcp/127.0.0.1/18080"; } 2>/dev/null; then
        break
    fi

    if [ "$SECONDS" -ge "$deadline" ]; then
        cat "$host_log" >&2
        echo "timed out waiting for host process on $host_addr" >&2
        exit 1
    fi
    sleep 0.1
done

printf 'GET /ws HTTP/1.1\r\nHost: 127.0.0.1:18080\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n' >&3
read -r status_line <&3
exec 3>&-
if [[ "$status_line" != *"101 Switching Protocols"* ]]; then
    cat "$host_log" >&2
    echo "host WebSocket smoke test failed: $status_line" >&2
    exit 1
fi
