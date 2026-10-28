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
scenes="$root/generalization-scenes-v1"
out="$root/generalization-audit-v1"
base="$project/build/flex/sim/late-search-v1/artifacts-v2/data172"
cohort="$root/cohort-v1/catalog"
development="$root/development-scenes-v1"
[[ ! -e "$out" ]]
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
[[ "$(/usr/bin/sha256sum "$base/data.bin" | /usr/bin/cut -d' ' -f1)" == 05032e0eb2a4a98a7f0146db66195792b2c22fe3bda3138039e9c721bc69b284 ]]
for ((i=0;i<172;i++));do for file in case.json environment.bin;do /usr/bin/sha256sum "$base/expert-$i/scene/$file" | /usr/bin/cut -d' ' -f1;done;done > "$out/prior-shas.txt"
for worker in {0..5};do for episode in {0..4};do for file in case.json environment.bin;do /usr/bin/sha256sum "$cohort/$worker/$episode/$file" | /usr/bin/cut -d' ' -f1;done;done;done >> "$out/prior-shas.txt"
for layout in 18 19;do for scene in {0..15};do /usr/bin/sha256sum "$development/$layout/$scene/case.json" | /usr/bin/cut -d' ' -f1;done;/usr/bin/sha256sum "$development/$layout/environment.bin" | /usr/bin/cut -d' ' -f1;done >> "$out/prior-shas.txt"
for layout in 20 21 22 23;do
    /usr/bin/jq -e --argjson layout "$layout" '.layoutId==$layout and (.fit|not) and (.rooms|length)==(1+($layout%2))' "$scenes/$layout/layout.json" > /dev/null
    env="$(/usr/bin/sha256sum "$scenes/$layout/environment.bin" | /usr/bin/cut -d' ' -f1)"
    reject_known_hash "$env" "$out/prior-shas.txt"
    for scene in 0 5 10 15;do
        casefile="$scenes/$layout/$scene/case.json"
        sha="$(/usr/bin/sha256sum "$casefile" | /usr/bin/cut -d' ' -f1)"
        reject_known_hash "$sha" "$out/prior-shas.txt"
        /usr/bin/jq -ne --slurpfile layout "$scenes/$layout/layout.json" --slurpfile case "$casefile" --argjson hidden "$((layout%2))" '$layout[0].rooms[$hidden] as $room | $case[0].objects[0].position as $p | $p[0]>$room[0] and $p[0]<$room[2] and $p[1]>$room[1] and $p[1]<$room[3]' > /dev/null
        index=$(((layout-20)*4+scene/5));seed=$((9970000+index))
        /usr/bin/jq -n --argjson index "$index" --argjson layout "$layout" --argjson scene "$scene" --argjson seed "$seed" --arg sha "$sha" --arg env "$env" '{index:$index,layout:$layout,scene:$scene,seed:$seed,caseSHA256:$sha,environmentSHA256:$env}'
    done
done > "$out/cases.jsonl"
/usr/bin/jq -s '{passed:(length==16 and ([.[].caseSHA256]|unique|length)==16 and ([.[].environmentSHA256]|unique|length)==4),episodes:length,layouts:([.[].layout]|unique),openLayouts:[20,22],hiddenLayouts:[21,23],casesNotInPriorDataOrDevelopment:true,environmentFilesNotInPriorDataOrDevelopment:true,reservedFinalLayoutsUntouched:true,rows:sort_by(.index)}' "$out/cases.jsonl" > "$out/cases.json"
/usr/bin/jq -e '.passed and .episodes==16 and .layouts==[20,21,22,23]' "$out/cases.json" > /dev/null
for layout in 20 21 22 23;do /usr/bin/jq -c '.rooms' "$scenes/$layout/layout.json";done | /usr/bin/sort -u > "$out/room-bounds.txt"
[[ "$(/usr/bin/wc -l < "$out/room-bounds.txt")" == 4 ]]
echo 'Four distinct non-fitting room layouts and sixteen cases passed the overlap audit.'
