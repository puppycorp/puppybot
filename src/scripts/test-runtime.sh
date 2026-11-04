#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$project_dir/src/scripts/native-toolchain.sh"
bash "$project_dir/src/scripts/build-runtime.sh"
"$project_dir/build/flex/controller-demo"
for suite in runtime simulator dashboard cli; do
    python3 "$project_dir/src/tests/$suite.py"
done
echo 'Native controller, HTTP/WebSocket, serial simulator, dashboard and CLI checks passed.'
