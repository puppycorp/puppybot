#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "scripts/run-host.sh is deprecated; use scripts/run-runtime.sh" >&2
exec "$script_dir/run-runtime.sh" "$@"
