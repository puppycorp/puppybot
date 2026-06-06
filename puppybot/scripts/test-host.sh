#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "scripts/test-host.sh is deprecated; use scripts/test-runtime.sh" >&2
exec "$script_dir/test-runtime.sh" "$@"
