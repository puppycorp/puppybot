#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$project_dir"
bash flex/scripts/build-control.sh
if [[ -n "${1:-}" ]]; then
    test_output="$1"
    mkdir "$test_output"
else
    test_output="$(mktemp -d "$project_dir/build/flex/sim/control-tests.XXXXXXXX")"
fi
build/flex/control/tests "$test_output/contracts"
build/flex/control/gradient-tests build/flex/control/kernels "$test_output/gradients"
build/flex/control/guard-tests build/flex/control/trainer build/flex/control/kernels "$test_output/guards"
./flex/control.sh init --output "$test_output/baseline" --seed 7
build/flex/control/policy-tests "$test_output/baseline" "$test_output/policy-contracts"
./flex/control.sh collect --output "$test_output/data" --episodes 2 --validation 1 --seed 101000
./flex/control.sh train --data "$test_output/data/data.bin" --output "$test_output/policy" \
    --epochs 2 --batch 1 --seed 7 --from-scratch
./flex/control.sh run --policy "$test_output/policy" --output "$test_output/run" \
    --episodes 1 --seed 110000 --horizon 12
./flex/control.sh verify --run "$test_output/run/110000" --policy "$test_output/run/policy" \
    --output "$test_output/verified"
if build/flex/control/simulator --headless --case ball-into-bin --steps 1 --bind 127.0.0.1:0 \
    > "$test_output/autonomous-incomplete.log" 2>&1; then
    echo 'An incomplete autonomous case incorrectly returned success.' >&2
    exit 1
fi
if [[ "$(< "$test_output/autonomous-incomplete.log")" != *'Case incomplete:'* ]]; then
    echo 'The autonomous case failed before exercising its normal incomplete status.' >&2
    exit 1
fi
echo "Native visual-control tests passed: $test_output"
