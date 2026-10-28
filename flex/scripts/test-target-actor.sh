#!/usr/bin/env bash
set -euo pipefail
project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
output="$(realpath -m "${1:?New output directory required}")"
runtime="${PUPPYBOT_TARGET_RUNTIME:-$project}"
fixtures="${PUPPYBOT_TARGET_FIXTURE_TOOL:-$project/build/flex/control/target-fixtures}"
zero="${PUPPYBOT_TARGET_ZERO_TOOL:-$project/build/flex/control/target-zero}"
pose_fixtures="${PUPPYBOT_POSE_FIXTURE_TOOL:-$project/build/flex/control/pose-fixtures}"
compare="${PUPPYBOT_POSE_COMPARE_TOOL:-$project/build/flex/control/pose-compare}"
core="${PUPPYBOT_POSE_CORE_TOOL:-$project/build/flex/control/pose-core-match}"
publish="${PUPPYBOT_ACTOR_PUBLISH_TOOL:-$project/build/flex/control/heat-actor-publish}"
parity="${PUPPYBOT_ACTOR_PARITY_TOOL:-$project/build/flex/control/initial-parity}"
trainer="$runtime/build/flex/control/trainer"
control="$runtime/build/flex/control/control"
kernels="$runtime/build/flex/control/kernels"
mkdir "$output"
"$pose_fixtures" "$output/data-fixtures"
"$fixtures" "$output/data-fixtures/data.bin" "$output/data-fixtures/mirrored-data.bin" "$output/target-fixtures"
cd "$runtime"
"$control" init --categorical --output "$output/base" --seed 7 > "$output/base.log" 2>&1
weights="$output/base/weights.bin"
sha="$(/usr/bin/sha256sum "$weights" | /usr/bin/cut -d' ' -f1)"
data="$output/data-fixtures/data.bin"
for variant in 0 1 2; do
    mkdir "$output/run-$variant"
    "$trainer" "$weights" "$sha" "$kernels" "$data" "$output/run-$variant" 1 2 100 7 --categorical --heat-actor --target-heatmap "$output/target-fixtures/target-$variant" --checkpoint-every 1 > "$output/run-$variant.log" 2>&1
done
cmp "$output/run-0/initial.bin" "$output/run-1/initial.bin"
cmp "$output/run-0/initial.bin" "$output/run-2/initial.bin"
cmp "$output/run-0/first-gradients.bin" "$output/run-2/first-gradients.bin"
cmp "$output/run-0/first-after.bin" "$output/run-2/first-after.bin"
"$compare" "$output/run-0/first-gradients.bin" "$output/run-1/first-gradients.bin" encoder.0.weight
"$core" "$weights" "$output/run-0/initial.bin" "$output/core-match.json"
jq -e '.passed and .allOriginalParametersByteIdentical and .extraTrainingParameters==51345' "$output/core-match.json" > /dev/null
"$zero" "$output/run-0/initial.bin" --merge
"$compare" "$output/run-0/initial.bin" "$output/run-0/first-after.bin" visual.merge.weight_T
"$publish" "$output/run-0/initial.bin" "$data" "$weights" "$output/initial-actor" 0 "$output/target-fixtures/target-0" > "$output/initial-publish.log" 2>&1
"$parity" "$output/base" "$output/initial-actor" "$data" "$output/initial-parity" > "$output/initial-parity.log" 2>&1
jq -e '.passed and .rawActorAndMemoryBitIdentical and .framesCompared==8' "$output/initial-parity/result.json" > /dev/null
for variant in 3 4 5 6 7; do
    mkdir "$output/rejected-$variant"
    if "$trainer" "$weights" "$sha" "$kernels" "$data" "$output/rejected-$variant" 0 1 100 7 --categorical --heat-actor --target-heatmap "$output/target-fixtures/target-$variant" > "$output/rejected-$variant.log" 2>&1; then
        echo "Invalid target-position fixture $variant was accepted." >&2;exit 1
    fi
    expected='target-position mask includes padding or post-consumption frame'
    if [[ "$variant" == 4 ]];then expected='target-position hash or dimensions differ';fi
    if [[ "$variant" == 5 ]];then expected='target-position receipt does not match demonstration data';fi
    if [[ "$variant" == 6 ]];then expected='masked target-position value is nonzero';fi
    if [[ "$variant" == 7 ]];then expected='invalid normalized target-position value';fi
    rg -Fq "$expected" "$output/rejected-$variant.log"
    [[ ! -e "$output/rejected-$variant/initial.bin" && ! -e "$output/rejected-$variant/weights.bin" ]]
done
mkdir "$output/dynamic-mirror" "$output/static-mirror"
"$trainer" "$weights" "$sha" "$kernels" "$data" "$output/dynamic-mirror" 1 2 100 7 --categorical --heat-actor --target-heatmap "$output/target-fixtures/target-0" --mirror-augment > "$output/dynamic-mirror.log" 2>&1
"$trainer" "$weights" "$sha" "$kernels" "$output/data-fixtures/mirrored-data.bin" "$output/static-mirror" 1 2 100 7 --categorical --heat-actor --target-heatmap "$output/target-fixtures/target-mirrored" > "$output/static-mirror.log" 2>&1
[[ "$(/usr/bin/od -An -tu8 "$output/dynamic-mirror/first-mirror-mask.bin" | /usr/bin/tr -d '[:space:]')" == 1 ]]
cmp "$output/dynamic-mirror/first-gradients.bin" "$output/static-mirror/first-gradients.bin"
cmp "$output/dynamic-mirror/first-after.bin" "$output/static-mirror/first-after.bin"
mkdir "$output/empty-batch"
"$trainer" "$weights" "$sha" "$kernels" "$output/target-fixtures/target-empty-batch/data.bin" "$output/empty-batch" 1 1 100 7 --categorical --heat-actor --target-heatmap "$output/target-fixtures/target-empty-batch" > "$output/empty-batch.log" 2>&1
[[ "$(/usr/bin/od -An -tu8 "$output/empty-batch/first-order.bin" | /usr/bin/awk '{print $1;exit}')" == 1 ]]
"$zero" "$output/empty-batch/first-gradients.bin" --heat
if "$control" init --categorical --heat-actor --target-heatmap "$output/target-fixtures/target-0" --output "$output/rejected-cli" > "$output/rejected-cli.log" 2>&1;then
    echo 'Target-position labels were accepted outside training.' >&2;exit 1
fi
rg -Fq 'target-position supervision is training-only' "$output/rejected-cli.log"
[[ ! -e "$output/rejected-cli" ]]
"$control" train --data "$data" --initial-policy "$output/base" --heat-actor --target-heatmap "$output/target-fixtures/target-0" --event-aux --output "$output/policy" --epochs 1 --batch 2 --seed 7 --checkpoint-every 1 > "$output/policy.log" 2>&1
target_sha="$(/usr/bin/sha256sum "$output/target-fixtures/target-0/targets.bin" | /usr/bin/cut -d' ' -f1)"
jq -e --arg sha "$target_sha" '.heatmapActorFeatures and .targetHeatmapAuxiliary and .cameraEventAuxiliary and (.taskFeedback|not) and .targetPositionTargetsSHA256==$sha' "$output/policy/receipt.json" > /dev/null
cmp "$output/policy/target-position/targets.bin" "$output/target-fixtures/target-0/targets.bin"
"$core" "$weights" "$output/policy/initial.bin" "$output/combined-core-match.json"
jq -e '.passed and .extraTrainingParameters==51474' "$output/combined-core-match.json" > /dev/null
"$runtime/build/flex/control/forward-tests" "$output/policy" "$data" "$output/forward" > "$output/forward.log" 2>&1
jq -e '.passed and .logitMaxAbsError==0 and .memoryMaxAbsError==0 and .resetBitIdentical' "$output/forward/result.json" > /dev/null
mkdir "$output/rejected-continuation"
if "$trainer" "$output/policy/weights.bin" "$(/usr/bin/sha256sum "$output/policy/weights.bin" | /usr/bin/cut -d' ' -f1)" "$kernels" "$data" "$output/rejected-continuation" 0 1 100 7 --categorical > "$output/rejected-continuation.log" 2>&1;then
    echo 'Heat actor was continued without its visual connection.' >&2;exit 1
fi
rg -Fq 'continuing a heat actor requires --heat-actor' "$output/rejected-continuation.log"
[[ ! -e "$output/rejected-continuation/initial.bin" && ! -e "$output/rejected-continuation/weights.bin" ]]
if [[ -n "${PUPPYBOT_TARGET_OLD_TRAINER:-}" ]];then
    for version in old new;do
        binary="$trainer";if [[ "$version" == old ]];then binary="$PUPPYBOT_TARGET_OLD_TRAINER";fi
        mkdir "$output/default-$version"
        "$binary" "$weights" "$sha" "$kernels" "$data" "$output/default-$version" 1 2 100 7 --categorical > "$output/default-$version.log" 2>&1
    done
    for file in initial.bin first-gradients.bin first-after.bin last.bin weights.bin;do cmp "$output/default-old/$file" "$output/default-new/$file";done
    for version in old new;do jq -s 'map(del(.elapsedMilliseconds))' "$output/default-$version/curves.jsonl" > "$output/default-$version-curves.json";done
    cmp "$output/default-old-curves.json" "$output/default-new-curves.json"
fi
jq -n '{passed:true,targetCoordinatesAffectEncoderGradients:true,validationTargetsDoNotAffectUpdates:true,originalWeightsByteIdentical:true,zeroMergeAndInitialRawParity:true,badSourceHashTargetHashMaskAndValuesRejected:true,mirroredSequenceGradientsMatch:true,emptyCandidateBatchHasZeroTargetGradients:true,continuationRequiresActorConnection:true,combinedEventAuxiliarySupported:true,exportedActorInputsUnchangedAndNativeForwardExact:true,pythonRequired:false}' > "$output/result.json"
echo 'Native learned heatmap actor contracts passed.'
