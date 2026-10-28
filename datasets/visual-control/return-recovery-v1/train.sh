#!/usr/bin/env bash
set -euo pipefail
project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
dataset="$project/datasets/visual-control/return-recovery-v1"
artifacts="$dataset/artifacts"
out="$project/build/flex/sim/approach35-v2/recovery-models"
[[ ! -e "$out" ]]
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/train.exit"' EXIT
cd "$project"
runtime="$out/runtime"
mkdir -p "$runtime/build/flex/control/kernels" "$runtime/flex/control"
cp build/flex/control/{control,trainer,forward-tests,policy,policy-categorical,policy-categorical-phase} "$runtime/build/flex/control/"
cp build/flex/control/kernels/*.ptx "$runtime/build/flex/control/kernels/"
cp build/flex/pixel-control{,-categorical,-categorical-phase}-model.flex "$runtime/build/flex/"
cp flex/control/model{,-categorical,-categorical-phase}.pup "$runtime/flex/control/"
cp -a build/flex/sim/approach35-train-v1/policy-warm5 "$out/initial-policy"
cp "$dataset/"{protocol.json,publish.flex,train.sh} "$out/"
/usr/bin/find "$runtime" -type f -print0 | /usr/bin/sort -z | /usr/bin/xargs -0 /usr/bin/sha256sum > "$out/runtime.sha256"
build/flex/control/compiler "$dataset/publish.flex" -o "$out/publish"
mkdir "$out/native-path"
for command in bash cat cp chmod dirname ffmpeg flock ln mkdir mktemp mv patch sha256sum; do
    executable="$(command -v "$command")"
    ln -s "$executable" "$out/native-path/$command"
done
export PATH="$out/native-path"
while [[ ! -f "$artifacts/dataset.exit" ]]; do
    if [[ -f "$artifacts/collection.exit" ]]; then echo 'Collection stopped before publishing an accepted recovery dataset'; exit 1; fi
    /usr/bin/sleep 5
done
[[ "$(< "$artifacts/dataset.exit")" == 0 ]]
/usr/bin/jq -e '.passed and .selectedHistories==96 and .fittingHistories==72 and .validationHistories==24 and .allOriginalSplitRolesPreserved and .studentInputsUnchanged' "$artifacts/coverage.json" > /dev/null
expected="$(/usr/bin/jq -r '.dataSHA256' "$artifacts/data96/report.json")"
[[ "$(/usr/bin/sha256sum "$artifacts/data96/data.bin" | /usr/bin/cut -d' ' -f1)" == "$expected" ]]
/usr/bin/sha256sum -c "$out/runtime.sha256" > "$out/runtime-before-training.log"
cd "$runtime"
pids=()
for arm in flat phase; do
    (
        trap 'status=$?; printf "%s\n" "$status" > "$out/'"$arm"'.exit"' EXIT
        extra=(); if [[ "$arm" == phase ]]; then extra+=(--phase-gated --event-aux); fi
        ./build/flex/control/control train --data "$artifacts/data96/data.bin" --initial-policy "$out/initial-policy" --output "$out/$arm" \
            --epochs 80 --batch 2 --learning-rate-micros 100 --seed 89 --checkpoint-every 20 "${extra[@]}" > "$out/$arm.log" 2>&1
    ) &
    pids+=("$!")
done
status=0
for pid in "${pids[@]}"; do if ! wait "$pid"; then status=1; fi; done
(( status==0 ))
/usr/bin/cmp "$out/flat/first-order.bin" "$out/phase/first-order.bin"
/usr/bin/cmp "$out/flat/final-order.bin" "$out/phase/final-order.bin"
/usr/bin/sha256sum -c "$out/runtime.sha256" > "$out/runtime-after-training.log"
echo 'Two matched-data recovery models completed80 epochs; fixed snapshot rollout evaluation is separate'
