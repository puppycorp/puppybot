#!/usr/bin/env bash
# Check that a new pose head preserves the existing large actor at initialization.
set -euo pipefail
project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
parent="$(realpath "${1:?Initial large gated policy required}")"
out="${2:?New output directory required}"
runtime="$(realpath "${3:-$project}")"
[[ ! -e "$out" ]];mkdir "$out";out="$(cd "$out" && pwd)"
"$project/build/flex/control/pose-fixtures" "$out/data"
"$project/build/flex/control/target-fixtures" "$out/data/data.bin" "$out/data/mirrored-data.bin" "$out/targets"
cd "$runtime"
./build/flex/control/control train --initial-policy "$parent" --data "$out/data/data.bin" --output "$out/policy" --epochs 1 --batch 1 --learning-rate-micros 100 --seed 202 --checkpoint-every 1 --event-aux --target-heatmap "$out/targets/target-0" --heat-actor --heat-stop-gradient --mirror-augment --large-model --phase-gated --memory-pose "$out/data/pose-0" > "$out/training.log" 2>&1
"$project/build/flex/control/compare-pose-initial" "$parent/weights.bin" "$out/policy/initial.bin" "$out/initial-comparison.json"
jq -e '.passed and .allOriginalParametersByteIdentical and .addedPoseHeadOnly and .memoryWidth==256 and .addedPoseParameters==1028' "$out/initial-comparison.json" > /dev/null
pose_sha="$(sha256sum "$out/data/pose-0/targets.bin" | cut -d' ' -f1)"
jq -e --arg sha "$pose_sha" '.memoryPoseAuxiliary and .memoryPoseTargetsSHA256==$sha and .memoryWidth==256 and .phaseGatedNavigation and (.taskFeedback|not)' "$out/policy/receipt.json" > /dev/null
./build/flex/control/large-forward-tests "$out/policy" "$out/data/data.bin" "$out/forward" > "$out/forward.log" 2>&1
jq -e '.passed and .logitMaxAbsError<0.00001 and .memoryMaxAbsError<0.00001 and .resetBitIdentical' "$out/forward/result.json" > /dev/null
cp "$out/policy/initial.bin" "$out/tampered.bin"
base="$(od -An -tu8 -j16 -N8 "$out/tampered.bin")";offset="$(od -An -tu8 -j240 -N8 "$out/tampered.bin")";at=$((base+offset))
byte="$(od -An -tu1 -j "$at" -N1 "$out/tampered.bin")";printf -v replacement '\\%03o' "$((byte^1))";printf '%b' "$replacement" | dd of="$out/tampered.bin" bs=1 seek="$at" conv=notrunc status=none
if "$project/build/flex/control/compare-pose-initial" "$parent/weights.bin" "$out/tampered.bin" "$out/rejected.json" > "$out/rejected.log" 2>&1;then echo 'Changed original weights were accepted.' >&2;exit 1;fi
rg -Fq 'original checkpoint tensor changed' "$out/rejected.log"
echo 'Large pose auxiliary preserves all initial actor weights and inference parity.'
