#!/usr/bin/env bash
set -euo pipefail
reject_known_hash() {
    local status=0
    /usr/bin/rg -Fxq "$1" "$2" || status=$?
    if (( status==0 ));then echo "Duplicate file hash: $1" >&2;exit 1;fi
    if (( status!=1 ));then echo "Could not check prior hashes: $2" >&2;exit "$status";fi
}

project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/expanded-rooms-v1"
base="$project/build/flex/sim/late-search-v1/artifacts-v2/data172"
catalog="$root/cohort-v1/catalog"
scenes="$root/development-scenes-v1"
out="$root/holdout-audit-v1"
[[ ! -e "$out" ]]
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
[[ "$(/usr/bin/sha256sum "$base/data.bin" | /usr/bin/cut -d' ' -f1)" == 05032e0eb2a4a98a7f0146db66195792b2c22fe3bda3138039e9c721bc69b284 ]]
for ((index=0;index<172;index++));do
    role=validation;if (( index<136 ));then role=fitting;fi
    hash="$(/usr/bin/sha256sum "$base/expert-$index/scene/case.json" | /usr/bin/cut -d' ' -f1)"
    printf '%s %s %s\n' "$hash" "$role" "$index"
done > "$out/old-histories.txt"
for worker in {0..5};do for episode in {0..4};do
    /usr/bin/sha256sum "$catalog/$worker/$episode/case.json" | /usr/bin/cut -d' ' -f1
done;done > "$out/new-cases.txt"
for layout in 6 7;do for scene in {0..15};do
    file="$project/datasets/visual-control/approach35-v1/artifacts/scenes/$layout/$scene/case.json"
    hash="$(/usr/bin/sha256sum "$file" | /usr/bin/cut -d' ' -f1)"
    fit="$(/usr/bin/awk -v h="$hash" '$1==h && $2=="fitting" {n++} END {print n+0}' "$out/old-histories.txt")"
    val="$(/usr/bin/awk -v h="$hash" '$1==h && $2=="validation" {n++} END {print n+0}' "$out/old-histories.txt")"
    extra="$(/usr/bin/awk -v h="$hash" '$1==h {n++} END {print n+0}' "$out/new-cases.txt")"
    /usr/bin/jq -n --argjson layout "$layout" --argjson scene "$scene" --arg hash "$hash" --argjson fit "$fit" --argjson val "$val" --argjson extra "$extra" '{layout:$layout,scene:$scene,caseSHA256:$hash,fittingMatches:$fit,validationMatches:$val,additionalCohortMatches:$extra}'
done;done > "$out/old-benchmark.jsonl"
/usr/bin/jq -s '{cases:length,fittingOverlap:(map(select(.fittingMatches>0))|length),validationOverlap:(map(select(.validationMatches>0))|length),screenValidationOverlap:(map(select(.scene<4 and .validationMatches>0))|length),additionalCohortOverlap:(map(select(.additionalCohortMatches>0))|length),rows:.}' "$out/old-benchmark.jsonl" > "$out/old-benchmark.json"
/usr/bin/jq -e '.cases==32 and .fittingOverlap==0 and .validationOverlap==21 and .screenValidationOverlap==8 and .additionalCohortOverlap==6' "$out/old-benchmark.json" > /dev/null

for layout in 18 19;do
    /usr/bin/jq -e --argjson layout "$layout" '.layoutId==$layout and (.fit|not)' "$scenes/$layout/layout.json" > /dev/null
    envhash="$(/usr/bin/sha256sum "$scenes/$layout/environment.bin" | /usr/bin/cut -d' ' -f1)"
    for prior in {0..171};do
        [[ "$(/usr/bin/sha256sum "$base/expert-$prior/scene/environment.bin" | /usr/bin/cut -d' ' -f1)" != "$envhash" ]]
    done
    for worker in {0..5};do for episode in {0..4};do
        [[ "$(/usr/bin/sha256sum "$catalog/$worker/$episode/environment.bin" | /usr/bin/cut -d' ' -f1)" != "$envhash" ]]
    done;done
    for scene in {0..15};do
        hash="$(/usr/bin/sha256sum "$scenes/$layout/$scene/case.json" | /usr/bin/cut -d' ' -f1)"
        status=0
        /usr/bin/awk -v h="$hash" '$1==h {found=1} END {exit !found}' "$out/old-histories.txt" || status=$?
        if (( status==0 ));then echo "Duplicate prior case hash: $hash" >&2;exit 1;fi
        if (( status!=1 ));then echo 'Could not check prior case hashes.' >&2;exit "$status";fi
        reject_known_hash "$hash" "$out/new-cases.txt"
        /usr/bin/jq -n --argjson layout "$layout" --argjson scene "$scene" --arg hash "$hash" --arg env "$envhash" '{layout:$layout,scene:$scene,caseSHA256:$hash,environmentSHA256:$env}'
    done
done > "$out/development-cases.jsonl"
/usr/bin/jq -s '{passed:(length==32 and ([.[].caseSHA256]|unique|length)==32 and ([.[].environmentSHA256]|unique|length)==2),cases:length,openLayout:18,hiddenLayout:19,sourceDatasetSHA256:"05032e0eb2a4a98a7f0146db66195792b2c22fe3bda3138039e9c721bc69b284",noPriorOrCohortCaseOrEnvironmentOverlap:true,reservedFinalLayoutsUntouched:true,rows:.}' "$out/development-cases.jsonl" > "$out/development-cases.json"
/usr/bin/jq -e '.passed and .cases==32' "$out/development-cases.json" > /dev/null
echo 'Original benchmark overlap measured; 32 development cases have distinct cases and environments.'
