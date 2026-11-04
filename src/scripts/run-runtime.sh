#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if ! bash "$project_dir/src/scripts/build-runtime.sh" >&2; then
    echo 'Puppybot: native compilation failed; program was not started.' >&2
    exit 1
fi
exec "$project_dir/build/flex/puppybot-runtime" "$@"
