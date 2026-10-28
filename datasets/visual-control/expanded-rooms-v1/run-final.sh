#!/usr/bin/env bash
set -euo pipefail
reject_known_hash() {
    local status=0
    /usr/bin/rg -Fxq "$1" "$2" || status=$?
    if (( status==0 ));then echo "Duplicate file hash: $1" >&2;exit 1;fi
    if (( status!=1 ));then echo "Could not check prior hashes: $2" >&2;exit "$status";fi
}

project="${PUPPYBOT_PROJECT:?Project root is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
root="$base/final-benchmark-v1"
generalization="$base/generalization-benchmark-v1"
training="$base/matched-training-v3"
trap 'status=$?; printf "%s\n" "$status" > "$root/run.exit"' EXIT
printf '%s\n' "$BASHPID" > "$root/run.pid"
cd "$project"
while [[ ! -f "$generalization/run.exit" ]];do
    [[ -f "$generalization/run.pid" ]] && kill -0 "$(< "$generalization/run.pid")" || { echo 'Generalization benchmark disappeared without a terminal status.';exit 1; }
    /usr/bin/sleep 10
done
[[ "$(< "$generalization/run.exit")" == 0 ]]
/usr/bin/sha256sum -c "$root/inputs.sha256" > "$root/integrity-before.log"
if /usr/bin/jq -e '.skipped' "$generalization/comparison.json" > /dev/null;then
    /usr/bin/jq -n '{skipped:true,reason:"No development candidate qualified",finalLayoutsGenerated:false,retainedPolicyOverwritten:false}' > "$root/comparison.json"
    echo 'Reserved final layouts remain untouched because no model qualified.';exit 0
fi
/usr/bin/jq -e '(.skipped|not) and .allEpisodeAuditsPassed' "$generalization/comparison.json" > /dev/null
/usr/bin/sha256sum -c "$generalization/inputs.sha256" > "$root/generalization-integrity.log"
candidate="$(/usr/bin/jq -r '.candidate' "$generalization/comparison.json")"
model="$training/old";if [[ "$candidate" == continued-202 ]];then model="$training/expanded";else [[ "$candidate" == continued-172 ]];fi
/usr/bin/jq -e --arg candidate "$candidate" '.qualified and .selected.candidate==$candidate and .selected.physicalReturns>=24 and .selected.openReturns>=8 and .selected.hiddenReturns>=8 and .selected.auditedEpisodes==32' "$generalization/selection.json" > /dev/null
sha="$(/usr/bin/sha256sum "$model/weights.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$sha" '.weightsSHA256==$sha and (.taskFeedback|not)' "$model/receipt.json" > /dev/null
"$root/generate" "$root/scenes" 10 12 validation > "$root/generate.log" 2>&1
prior="$base/generalization-audit-v1/prior-shas.txt"
cp "$prior" "$root/prior-shas.txt"
for layout in 20 21 22 23;do for scene in {0..15};do /usr/bin/sha256sum "$generalization/scenes/$layout/$scene/case.json" | /usr/bin/cut -d' ' -f1;done;/usr/bin/sha256sum "$generalization/scenes/$layout/environment.bin" | /usr/bin/cut -d' ' -f1;done >> "$root/prior-shas.txt"
for layout in 10 11;do
    /usr/bin/jq -e --argjson layout "$layout" '.layoutId==$layout and (.fit|not) and (.rooms|length)==(1+($layout%2))' "$root/scenes/$layout/layout.json" > /dev/null
    envhash="$(/usr/bin/sha256sum "$root/scenes/$layout/environment.bin" | /usr/bin/cut -d' ' -f1)"
    reject_known_hash "$envhash" "$root/prior-shas.txt"
    for scene in {0..7};do
        casefile="$root/scenes/$layout/$scene/case.json";casehash="$(/usr/bin/sha256sum "$casefile" | /usr/bin/cut -d' ' -f1)"
        reject_known_hash "$casehash" "$root/prior-shas.txt"
        /usr/bin/jq -ne --slurpfile layout "$root/scenes/$layout/layout.json" --slurpfile case "$casefile" --argjson hidden "$((layout%2))" '$layout[0].rooms[$hidden] as $room | $case[0].objects[0].position as $p | $p[0]>$room[0] and $p[0]<$room[2] and $p[1]>$room[1] and $p[1]<$room[3]' > /dev/null
        index=$(((layout-10)*8+scene));seed=$((9980000+index))
        /usr/bin/jq -n --argjson index "$index" --argjson layout "$layout" --argjson scene "$scene" --argjson seed "$seed" --arg casehash "$casehash" --arg envhash "$envhash" '{index:$index,layout:$layout,scene:$scene,seed:$seed,caseSHA256:$casehash,environmentSHA256:$envhash}'
    done
done > "$root/cases.jsonl"
/usr/bin/jq -s '{passed:(length==16 and ([.[].caseSHA256]|unique|length)==16 and ([.[].environmentSHA256]|unique|length)==2),episodes:length,layouts:[10,11],rows:sort_by(.index)}' "$root/cases.jsonl" > "$root/cases.json"
/usr/bin/jq -e '.passed and .episodes==16' "$root/cases.json" > /dev/null
find "$root/scenes" -type f -print0 | /usr/bin/sort -z | /usr/bin/xargs -0 /usr/bin/sha256sum > "$root/scenes.sha256"
bash "$root/benchmark.sh" "$root/policies/baseline" baseline false
bash "$root/benchmark.sh" "$model" selected false
bash "$root/benchmark.sh" "$model" blackout true
/usr/bin/sha256sum -c "$root/inputs.sha256" > "$root/integrity-after.log"
/usr/bin/sha256sum -c "$root/scenes.sha256" > "$root/scenes-integrity.log"
[[ "$(/usr/bin/sha256sum "$model/weights.bin" | /usr/bin/cut -d' ' -f1)" == "$sha" ]]
/usr/bin/jq -s --arg candidate "$candidate" -f "$root/final-report.jq" "$root/score-baseline.json" "$root/score-selected.json" "$root/score-blackout.json" > "$root/comparison.json"
echo 'Reserved final comparison completed; inspect task and blackout results before any promotion.'
