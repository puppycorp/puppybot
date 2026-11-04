#!/usr/bin/env bash
# Ablated inference must equal the parent with neutral drive feedback.
set -euo pipefail
ablate="$(realpath "${1:?Ablation binary required}")";probe="$(realpath "${2:?Forward probe required}")"
source="$(realpath "${3:?Large policy required}")";episode="$(realpath "${4:?Recorded episode required}")"
out="$(realpath -m "${5:?New output directory required}")";[[ ! -e "$out" ]];mkdir "$out";mkdir "$out/policy"
cp "$source/policy" "$out/policy/policy";cp -a "$source/kernels" "$out/policy/kernels"
"$ablate" "$source/weights.bin" "$out/policy/weights.bin" "$out/ablation.json" > "$out/ablation.log" 2>&1
sha="$(sha256sum "$out/policy/weights.bin" | cut -d' ' -f1)"
jq --arg sha "$sha" '.weightsSHA256=$sha | .checkpointSHA256=$sha' "$source/receipt.json" > "$out/policy/receipt.json"
step="$(jq -er '.step|select(type=="number" and floor==.)' "$episode/initial.json")"
"$probe" "$source" "$out/policy" "$episode/actor-$step.rgb" "$episode/actor-$step.feedback" "$out/forward" > "$out/forward.log" 2>&1
jq -e '.passed and .cameraInputUnchanged and .contactInputUnchanged and .initialMemoryIdentical and .outputCount==263 and .originalNeutralVsAblatedError<0.00001 and .ablatedDriveVariationError<0.00001 and .singleFrameOnly and .closedLoopPerformanceNotMeasured' "$out/forward/result.json" > /dev/null
echo 'Ablated inference matches neutral parent and ignores changed drive feedback.'
