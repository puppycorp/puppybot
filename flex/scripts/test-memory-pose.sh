#!/usr/bin/env bash
set -euo pipefail
project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
output="$(realpath -m "${1:?New output directory required}")"
runtime="${PUPPYBOT_POSE_RUNTIME:-$project}"
fixtures="${PUPPYBOT_POSE_FIXTURE_TOOL:-$project/build/flex/control/pose-fixtures}"
compare="${PUPPYBOT_POSE_COMPARE_TOOL:-$project/build/flex/control/pose-compare}"
core="${PUPPYBOT_POSE_CORE_TOOL:-$project/build/flex/control/pose-core-match}"
trainer="$runtime/build/flex/control/trainer"
control="$runtime/build/flex/control/control"
kernels="$runtime/build/flex/control/kernels"
mkdir "$output"
"$fixtures" "$output/fixtures"
cd "$runtime"
"$control" init --categorical --output "$output/base" --seed 7 > "$output/base.log" 2>&1
weights="$output/base/weights.bin"
sha="$(/usr/bin/sha256sum "$weights" | /usr/bin/cut -d' ' -f1)"
data="$output/fixtures/data.bin"
for variant in 0 1 2; do
    mkdir "$output/run-$variant"
    "$trainer" "$weights" "$sha" "$kernels" "$data" "$output/run-$variant" 1 2 100 7 --categorical --memory-pose "$output/fixtures/pose-$variant" --checkpoint-every 1 > "$output/run-$variant.log" 2>&1
done
cmp "$output/run-0/initial.bin" "$output/run-1/initial.bin"
cmp "$output/run-0/initial.bin" "$output/run-2/initial.bin"
cmp "$output/run-0/first-gradients.bin" "$output/run-2/first-gradients.bin"
cmp "$output/run-0/first-after.bin" "$output/run-2/first-after.bin"
"$compare" "$output/run-0/first-gradients.bin" "$output/run-1/first-gradients.bin" memory.weight_ih_T
"$core" "$weights" "$output/run-0/initial.bin" "$output/core-match.json"
jq -e '.passed and .allOriginalParametersByteIdentical and .extraTrainingParameters==516' "$output/core-match.json" > /dev/null
for variant in 3 4 5 6 7; do
    mkdir "$output/rejected-$variant"
    if "$trainer" "$weights" "$sha" "$kernels" "$data" "$output/rejected-$variant" 0 1 100 7 --categorical --memory-pose "$output/fixtures/pose-$variant" > "$output/rejected-$variant.log" 2>&1; then
        echo "Invalid memory-pose fixture $variant was accepted." >&2;exit 1
    fi
    expected='memory-pose mask differs from valid frame'
    if [[ "$variant" == 4 ]];then expected='memory-pose target hash or dimensions differ';fi
    if [[ "$variant" == 5 ]];then expected='memory-pose receipt does not match demonstration data';fi
    if [[ "$variant" == 6 ]];then expected='memory-pose heading is not a unit vector';fi
    if [[ "$variant" == 7 ]];then expected='memory-pose padding is nonzero';fi
    rg -Fq "$expected" "$output/rejected-$variant.log"
    [[ ! -e "$output/rejected-$variant/initial.bin" && ! -e "$output/rejected-$variant/weights.bin" ]]
done
mkdir "$output/dynamic-mirror" "$output/static-mirror"
"$trainer" "$weights" "$sha" "$kernels" "$data" "$output/dynamic-mirror" 1 2 100 7 --categorical --memory-pose "$output/fixtures/pose-0" --mirror-augment > "$output/dynamic-mirror.log" 2>&1
"$trainer" "$weights" "$sha" "$kernels" "$output/fixtures/mirrored-data.bin" "$output/static-mirror" 1 2 100 7 --categorical --memory-pose "$output/fixtures/pose-mirrored" > "$output/static-mirror.log" 2>&1
[[ "$(/usr/bin/od -An -tu8 "$output/dynamic-mirror/first-mirror-mask.bin" | /usr/bin/tr -d '[:space:]')" == 1 ]]
cmp "$output/dynamic-mirror/first-gradients.bin" "$output/static-mirror/first-gradients.bin"
cmp "$output/dynamic-mirror/first-after.bin" "$output/static-mirror/first-after.bin"
if "$control" init --categorical --memory-pose "$output/fixtures/pose-0" --output "$output/rejected-cli" > "$output/rejected-cli.log" 2>&1;then
    echo 'Memory-pose targets were accepted outside training.' >&2;exit 1
fi
rg -Fq 'memory-pose supervision is training-only' "$output/rejected-cli.log"
[[ ! -e "$output/rejected-cli" ]]
"$control" train --data "$data" --initial-policy "$output/base" --memory-pose "$output/fixtures/pose-0" --event-aux --output "$output/policy" --epochs 1 --batch 2 --seed 7 --checkpoint-every 1 > "$output/policy.log" 2>&1
target_sha="$(/usr/bin/sha256sum "$output/fixtures/pose-0/targets.bin" | /usr/bin/cut -d' ' -f1)"
jq -e --arg sha "$target_sha" '.memoryPoseAuxiliary and .cameraEventAuxiliary and (.taskFeedback|not) and .memoryPoseTargetsSHA256==$sha' "$output/policy/receipt.json" > /dev/null
cmp "$output/policy/memory-pose/targets.bin" "$output/fixtures/pose-0/targets.bin"
"$core" "$weights" "$output/policy/initial.bin" "$output/combined-core-match.json"
jq -e '.passed and .extraTrainingParameters==645' "$output/combined-core-match.json" > /dev/null
"$runtime/build/flex/control/forward-tests" "$output/policy" "$data" "$output/forward" > "$output/forward.log" 2>&1
jq -e '.passed and .logitMaxAbsError==0 and .memoryMaxAbsError==0 and .resetBitIdentical' "$output/forward/result.json" > /dev/null
if [[ -n "${PUPPYBOT_POSE_OLD_TRAINER:-}" ]];then
    for version in old new;do
        binary="$trainer";if [[ "$version" == old ]];then binary="$PUPPYBOT_POSE_OLD_TRAINER";fi
        mkdir "$output/default-$version"
        "$binary" "$weights" "$sha" "$kernels" "$data" "$output/default-$version" 1 2 100 7 --categorical > "$output/default-$version.log" 2>&1
    done
    for file in initial.bin first-gradients.bin first-after.bin last.bin weights.bin;do cmp "$output/default-old/$file" "$output/default-new/$file";done
    for version in old new;do jq -s 'map(del(.elapsedMilliseconds))' "$output/default-$version/curves.jsonl" > "$output/default-$version-curves.json";done
    cmp "$output/default-old-curves.json" "$output/default-new-curves.json"
fi
jq -n '{passed:true,poseTargetsAffectGRUGradients:true,validationTargetsDoNotAffectUpdates:true,originalWeightsByteIdentical:true,badSourceHashTargetHashMaskHeadingAndPaddingRejected:true,mirroredSequenceGradientsMatch:true,trainingOnlyCLIEnforced:true,combinedVisualAuxiliarySupported:true,exportedActorHasNoPoseInputAndMatchesNativeForward:true,pythonRequired:false}' > "$output/result.json"
echo 'Native memory-pose training contracts passed.'
