#!/usr/bin/env bash
set -euo pipefail
project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$project"
root="$project/build/flex/sim/sequence-mirror-v1"
out="$root/models"
dataset="$project/datasets/visual-control/sequence-mirror-v1"
data="$project/datasets/visual-control/return-recovery-v1/artifacts-primitive/data96/data.bin"
[[ ! -e "$out" ]]
for check in contracts optimizer-contracts gradient-contracts forward-contracts old-default; do /usr/bin/jq -e '.passed' "$root/$check/result.json" > /dev/null; done
[[ "$(/usr/bin/sha256sum "$data" | /usr/bin/cut -d' ' -f1)" == a4dd1b61727f82e7ed044ebaf89268509cf47631a1392f7caa8249d826f3d6f8 ]]
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/train.exit"' EXIT
runtime="$out/runtime"
mkdir -p "$runtime/build/flex/control/kernels" "$runtime/flex/control"
cp build/flex/control/{control,trainer,forward-tests,policy,policy-categorical,policy-categorical-phase} "$runtime/build/flex/control/"
cp build/flex/control/kernels/*.ptx "$runtime/build/flex/control/kernels/"
cp build/flex/pixel-control{,-categorical,-categorical-phase}-model.flex "$runtime/build/flex/"
cp flex/control/model{,-categorical,-categorical-phase}.pup "$runtime/flex/control/"
cp -a build/flex/sim/approach35-v2/policy-primitive-flat80 "$out/initial-policy"
[[ "$(/usr/bin/sha256sum "$out/initial-policy/weights.bin" | /usr/bin/cut -d' ' -f1)" == a90445e2f138c326776e22deecceb0d5b04c18c3daaa1f1be76bef2fa107bc11 ]]
cp -a flex/control "$out/source-control"
cp "$dataset/"{train.sh,protocol.json,publish.flex} "$out/"
cp -a build/flex/sim/approach35-v2/recovery-primitive-models/native-path "$out/native-path"
build/flex/control/compiler "$dataset/publish.flex" -o "$out/publish"
/usr/bin/find "$runtime" -type f -print0 | /usr/bin/sort -z | /usr/bin/xargs -0 /usr/bin/sha256sum > "$out/runtime.sha256"
export PATH="$out/native-path"
cd "$runtime"
pids=()
for arm in plain mirror; do
    (
        trap 'status=$?; printf "%s\n" "$status" > "$out/'"$arm"'.exit"' EXIT
        printf '%s\n' "$BASHPID" > "$out/$arm-parent.pid"
        extra=(); if [[ "$arm" == mirror ]]; then extra+=(--mirror-augment); fi
        ./build/flex/control/control train --initial-policy "$out/initial-policy" --data "$data" --output "$out/$arm" \
            --epochs 20 --batch 2 --learning-rate-micros 100 --seed 107 --checkpoint-every 10 "${extra[@]}" > "$out/$arm.log" 2>&1
    ) &
    pids+=("$!")
done
status=0
for pid in "${pids[@]}"; do if ! wait "$pid"; then status=1; fi; done
(( status==0 ))
/usr/bin/cmp "$out/plain/first-order.bin" "$out/mirror/first-order.bin"
/usr/bin/cmp "$out/plain/final-order.bin" "$out/mirror/final-order.bin"
/usr/bin/cmp "$out/plain/initial.bin" "$out/mirror/initial.bin"
/usr/bin/sha256sum -c "$out/runtime.sha256" > "$out/runtime-after-training.log"
echo 'Matched ordinary and mirror training completed; autonomous evaluation is separate.'
