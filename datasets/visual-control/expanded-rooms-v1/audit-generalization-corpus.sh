#!/usr/bin/env bash
set -euo pipefail
reject_known_hash() {
    local status=0
    /usr/bin/rg -Fxq "$1" "$2" || status=$?
    if (( status==0 ));then echo "Duplicate file hash: $1" >&2;exit 1;fi
    if (( status!=1 ));then echo "Could not check prior hashes: $2" >&2;exit "$status";fi
}
project="${PUPPYBOT_PROJECT:?Project root is required}"
out="${1:?A new output directory is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
source="${2:?Audited corpus directory is required}"
coverage="${3:?Corpus coverage report is required}"
general="$base/generalization-benchmark-v1"
scenes="$general/scenes"
[[ ! -e "$out" ]]
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
cd "$project"
/usr/bin/sha256sum -c "$general/inputs.sha256" > "$out/generalization-integrity-before.log"
sha="$(/usr/bin/sha256sum "$source/data.bin" | /usr/bin/cut -d' ' -f1)"
read -r histories fitting length < <(/usr/bin/od -An -v -tu8 -j8 -N24 "$source/data.bin" | /usr/bin/tr '\n' ' '; echo)
magic="$(/usr/bin/head -c 8 "$source/data.bin")"
bytes="$(/usr/bin/stat -c %s "$source/data.bin")"
[[ "$magic" == PVDATA04 && "$histories" -gt 0 && "$histories" -le 1024 && "$fitting" -gt 0 && "$fitting" -lt "$histories" && "$length" -gt 0 && "$length" -le 512 && "$bytes" -le 8589934592 && "$bytes" -eq $((32+histories*length*21224)) ]]
/usr/bin/jq -e --arg sha "$sha" --argjson n "$histories" --argjson fit "$fitting" '.passed and .episodes==$n and .fittingHistories==$fit and .validationHistories==($n-$fit) and .dataSHA256==$sha and .existingDataBytePreserved and .newHistoriesIndependentlyAudited and .teacherLabelsTrainingOnly and .actorInputsUnchanged' "$coverage" > /dev/null
/usr/bin/jq -e '.passed and .episodes==16 and .layouts==[20,21,22,23] and .casesNotInPriorDataOrDevelopment and .environmentFilesNotInPriorDataOrDevelopment' "$general/cases.json" > /dev/null
/usr/bin/cp "$base/generalization-audit-v1/prior-shas.txt" "$out/prior-shas.txt"
for ((i=0;i<histories;i++));do
    for file in case.json environment.bin;do /usr/bin/sha256sum "$source/expert-$i/scene/$file" | /usr/bin/cut -d' ' -f1;done
done >> "$out/prior-shas.txt"
for layout in 18 19;do
    for scene in {0..15};do
        for file in case.json environment.bin;do /usr/bin/sha256sum "$base/unseen-benchmark-v2/scenes/$layout/$scene/$file" | /usr/bin/cut -d' ' -f1;done
    done
done >> "$out/prior-shas.txt"
for ((i=0;i<16;i++));do
    for file in case.json environment.bin;do
        digest="$(/usr/bin/sha256sum "$base/return-quick-v1/merged-16/expert-$i/scene/$file" | /usr/bin/cut -d' ' -f1)"
        /usr/bin/rg -Fxq "$digest" "$out/prior-shas.txt"
    done
done
for layout in 20 21 22 23;do
    /usr/bin/jq -e --argjson layout "$layout" '.layoutId==$layout and (.fit|not) and (.rooms|length)==(1+($layout%2))' "$scenes/$layout/layout.json" > /dev/null
    envhash="$(/usr/bin/sha256sum "$scenes/$layout/environment.bin" | /usr/bin/cut -d' ' -f1)"
    reject_known_hash "$envhash" "$out/prior-shas.txt"
    for scene in 0 5 10 15;do
        /usr/bin/cmp "$scenes/$layout/environment.bin" "$scenes/$layout/$scene/environment.bin"
        /usr/bin/cmp "$scenes/$layout/layout.json" "$scenes/$layout/$scene/layout.json"
        casefile="$scenes/$layout/$scene/case.json";casehash="$(/usr/bin/sha256sum "$casefile" | /usr/bin/cut -d' ' -f1)"
        reject_known_hash "$casehash" "$out/prior-shas.txt"
        index=$(((layout-20)*4+scene/5));seed=$((9970000+index))
        /usr/bin/jq -e --argjson index "$index" --argjson layout "$layout" --argjson scene "$scene" --argjson seed "$seed" --arg casehash "$casehash" --arg envhash "$envhash" '[.rows[]|select(.index==$index and .layout==$layout and .scene==$scene and .seed==$seed and .caseSHA256==$casehash and .environmentSHA256==$envhash)]|length==1' "$general/cases.json" > /dev/null
        /usr/bin/jq -ne --slurpfile layout "$scenes/$layout/layout.json" --slurpfile case "$casefile" --argjson hidden "$((layout%2))" '$layout[0].rooms[$hidden] as $room | $case[0].objects[0].position as $p | $p[0]>$room[0] and $p[0]<$room[2] and $p[1]>$room[1] and $p[1]<$room[3]' > /dev/null
        /usr/bin/jq -n --argjson index "$index" --argjson layout "$layout" --argjson scene "$scene" --argjson seed "$seed" --arg casehash "$casehash" --arg envhash "$envhash" '{index:$index,layout:$layout,scene:$scene,seed:$seed,caseSHA256:$casehash,environmentSHA256:$envhash}'
    done
done > "$out/cases.jsonl"
/usr/bin/jq -s --arg data "$sha" --argjson n "$histories" --argjson fit "$fitting" '{passed:(length==16 and ([.[].caseSHA256]|unique|length)==16 and ([.[].environmentSHA256]|unique|length)==4),trainingHistories:$n,fittingHistories:$fit,validationHistories:($n-$fit),trainingDataSHA256:$data,layouts:([.[].layout]|unique),cases:length,rows:sort_by(.index),exactCaseAndEnvironmentHashesDisjointFromTrainingAndDevelopment:true,geometrySimilarityNotExcluded:true,reservedFinalUntouched:true}' "$out/cases.jsonl" > "$out/result.json"
/usr/bin/jq -e --argjson n "$histories" '.passed and .trainingHistories==$n and .layouts==[20,21,22,23] and .cases==16' "$out/result.json" > /dev/null
/usr/bin/sha256sum -c "$general/inputs.sha256" > "$out/generalization-integrity-after.log"
echo 'Four-layout cases are disjoint from the audited corpus and development scenes by exact file hash.'
