#!/usr/bin/env bash
set -euo pipefail
reject_known_hash() {
    local status=0
    /usr/bin/rg -Fxq "$1" "$2" || status=$?
    if (( status==0 ));then echo "Duplicate file hash: $1" >&2;exit 1;fi
    if (( status!=1 ));then echo "Could not check prior hashes: $2" >&2;exit "$status";fi
}
project="${PUPPYBOT_PROJECT:?Project root is required}"
out="${1:?New output directory required}"
resources="${2:?Frozen resources required}"
first="${3:?First candidate gate required}"
second="${4:?Second candidate gate required}"
[[ ! -e "$out" ]]
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
cd "$project"
args=()
declare -A seen=()
for source in "$first" "$second";do
    [[ -f "$source/run.exit" && "$(< "$source/run.exit")" == 0 ]] || { echo "Candidate comparison is incomplete or failed: $source" >&2;exit 1; }
    file="$source/selection/selection.json"
    /usr/bin/jq -e '.reservedFinalStillRequired and (.retainedPolicyOverwritten|not) and (.qualified|type=="boolean")' "$file" > /dev/null
    if /usr/bin/jq -e '.qualified' "$file" > /dev/null;then
        name="$(/usr/bin/jq -r '.selected.candidate' "$file")"
        [[ "$name" =~ ^[a-zA-Z0-9_-]+$ ]]
        if [[ -z "${seen[$name]:-}" ]];then
            score="$(/usr/bin/jq -r '.selected.scoreFile' "$file")";policy="$(/usr/bin/jq -r '.selected.policyDirectory' "$file")"
            [[ -f "$score" && -f "$policy/receipt.json" ]]
            args+=("$score" "$policy");seen[$name]=1
        fi
    fi
done
if (( ${#args[@]}==0 ));then
    /usr/bin/jq -n '{skipped:true,reason:"No 32-case candidate met the predefined qualification",reservedFinalGenerated:false,retainedPolicyOverwritten:false}' > "$out/comparison.json"
    echo 'No candidate qualified; held-out layouts remain unused.';exit 0
fi
/usr/bin/sha256sum -c "$resources/inputs.sha256" > "$out/resources-before.log"
/usr/bin/bash "$resources/gate.sh" "$out/selection" "${args[@]}" > "$out/selection.log" 2>&1
/usr/bin/jq -e '.qualified and .selected.physicalReturns>=24 and .selected.openReturns>=8 and .selected.hiddenReturns>=8 and .selected.auditedEpisodes==32 and .reservedFinalStillRequired' "$out/selection/selection.json" > /dev/null
model="$(/usr/bin/jq -r '.selected.policyDirectory' "$out/selection/selection.json")"
candidate="$(/usr/bin/jq -r '.selected.candidate' "$out/selection/selection.json")"
sha="$(/usr/bin/sha256sum "$model/weights.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$sha" '.weightsSHA256==$sha and (.taskFeedback|not) and ((.imageSide // 84)==84)' "$model/receipt.json" > /dev/null
if [[ -n "${PUPPYBOT_QUALIFIED_CORPUS_DIR:-}" || -n "${PUPPYBOT_QUALIFIED_COVERAGE:-}" ]];then
    corpus="${PUPPYBOT_QUALIFIED_CORPUS_DIR:?Both corpus and coverage are required}"
    coverage="${PUPPYBOT_QUALIFIED_COVERAGE:?Both corpus and coverage are required}"
    # The audit must be part of the frozen, verified resources, not live code.
    /usr/bin/sha256sum "$resources/corpus-audit.sh" | /usr/bin/rg -Fxq -f - "$resources/inputs.sha256"
    if /usr/bin/rg -q '(^|;)[[:space:]]*![[:space:]]+/usr/bin/rg -Fxq' "$resources/corpus-audit.sh";then echo 'Frozen corpus audit contains an unsafe overlap check; create a corrected snapshot.' >&2;exit 1;fi
    /usr/bin/bash "$resources/corpus-audit.sh" "$out/overlap-audit" "$corpus" "$coverage" > "$out/overlap-audit.log" 2>&1
    data="$(/usr/bin/jq -r '.dataSHA256' "$model/receipt.json")"
    /usr/bin/jq -e --arg data "$data" '.passed and .trainingDataSHA256==$data and .cases==16 and .reservedFinalUntouched' "$out/overlap-audit/result.json" > /dev/null
else
    if /usr/bin/rg -q '(^|;)[[:space:]]*![[:space:]]+/usr/bin/rg -Fxq' "$resources/audit.sh";then echo 'Frozen corpus audit contains an unsafe overlap check; create a corrected snapshot.' >&2;exit 1;fi
    /usr/bin/bash "$resources/audit.sh" "$out/overlap-audit" > "$out/overlap-audit.log" 2>&1
    /usr/bin/jq -e '.passed and .trainingHistories==236 and .cases==16 and .reservedFinalUntouched' "$out/overlap-audit/result.json" > /dev/null
fi
memory="$(/usr/bin/jq -r '.memoryWidth // 128' "$model/receipt.json")"
[[ "$memory" == 128 || "$memory" == 256 ]]
if [[ "$memory" == 256 ]];then
    for benchmark in benchmark-generalization.sh benchmark-final.sh;do /usr/bin/rg -Fq -- '--large-model' "$resources/$benchmark";done
    for benchmark in generalization final;do "$resources/$benchmark/runtime/build/flex/control/control" help | /usr/bin/rg -Fq -- '--large-model';done
fi
original="$project/build/flex/sim/expanded-rooms-v1/generalization-benchmark-v1/scenes"
for layout in 20 21 22 23;do
    /usr/bin/cmp "$original/$layout/layout.json" "$resources/generalization/scenes/$layout/layout.json"
    /usr/bin/cmp "$original/$layout/environment.bin" "$resources/generalization/scenes/$layout/environment.bin"
    for scene in 0 5 10 15;do
        for file in case.json environment.bin layout.json;do /usr/bin/cmp "$original/$layout/$scene/$file" "$resources/generalization/scenes/$layout/$scene/$file";done
    done
done
for file in weights.bin policy receipt.json;do /usr/bin/cmp "$resources/generalization/policies/baseline/$file" "$resources/final/policies/baseline/$file";done
/usr/bin/cp -a "$resources/generalization" "$out/generalization"
export PUPPYBOT_GENERALIZATION_OUTPUT="$out/generalization"
/usr/bin/bash "$resources/benchmark-generalization.sh" "$out/generalization/policies/baseline" baseline
/usr/bin/bash "$resources/benchmark-generalization.sh" "$model" selected
/usr/bin/jq -s -e 'all(.[]; .episodes==16 and .completedRecordings==16 and .auditedEpisodes==16 and .auditFailures==0)' "$out/generalization/score-baseline.json" "$out/generalization/score-selected.json" > /dev/null
/usr/bin/jq -n --arg candidate "$candidate" --slurpfile baseline "$out/generalization/score-baseline.json" --slurpfile selected "$out/generalization/score-selected.json" '{candidate:$candidate,baseline:$baseline[0],selected:$selected[0],allEpisodeAuditsPassed:true,reservedFinalStillRequired:true}' > "$out/generalization/comparison.json"

# The reserved layouts are generated only after a qualified development
# candidate and a fully audited four-layout comparison.
/usr/bin/cp -a "$resources/final" "$out/final"
final="$out/final"
"$final/generate" "$final/scenes" 10 12 validation > "$final/generate.log" 2>&1
/usr/bin/cp "$out/overlap-audit/prior-shas.txt" "$final/prior-shas.txt"
for layout in 20 21 22 23;do
    /usr/bin/sha256sum "$out/generalization/scenes/$layout/environment.bin" | /usr/bin/cut -d' ' -f1
    for scene in {0..15};do /usr/bin/sha256sum "$out/generalization/scenes/$layout/$scene/case.json" | /usr/bin/cut -d' ' -f1;done
done >> "$final/prior-shas.txt"
for layout in 10 11;do
    /usr/bin/jq -e --argjson layout "$layout" '.layoutId==$layout and (.fit|not) and (.rooms|length)==(1+($layout%2))' "$final/scenes/$layout/layout.json" > /dev/null
    envhash="$(/usr/bin/sha256sum "$final/scenes/$layout/environment.bin" | /usr/bin/cut -d' ' -f1)"
    reject_known_hash "$envhash" "$final/prior-shas.txt"
    for scene in {0..7};do
        /usr/bin/cmp "$final/scenes/$layout/environment.bin" "$final/scenes/$layout/$scene/environment.bin"
        /usr/bin/cmp "$final/scenes/$layout/layout.json" "$final/scenes/$layout/$scene/layout.json"
        casefile="$final/scenes/$layout/$scene/case.json";casehash="$(/usr/bin/sha256sum "$casefile" | /usr/bin/cut -d' ' -f1)"
        reject_known_hash "$casehash" "$final/prior-shas.txt"
        /usr/bin/jq -ne --slurpfile layout "$final/scenes/$layout/layout.json" --slurpfile case "$casefile" --argjson hidden "$((layout%2))" '$layout[0].rooms[$hidden] as $room | $case[0].objects[0].position as $p | $p[0]>$room[0] and $p[0]<$room[2] and $p[1]>$room[1] and $p[1]<$room[3]' > /dev/null
        index=$(((layout-10)*8+scene));seed=$((9980000+index))
        /usr/bin/jq -n --argjson index "$index" --argjson layout "$layout" --argjson scene "$scene" --argjson seed "$seed" --arg casehash "$casehash" --arg envhash "$envhash" '{index:$index,layout:$layout,scene:$scene,seed:$seed,caseSHA256:$casehash,environmentSHA256:$envhash}'
    done
done > "$final/cases.jsonl"
/usr/bin/jq -s '{passed:(length==16 and ([.[].caseSHA256]|unique|length)==16 and ([.[].environmentSHA256]|unique|length)==2),episodes:length,layouts:[10,11],rows:sort_by(.index)}' "$final/cases.jsonl" > "$final/cases.json"
/usr/bin/jq -e '.passed and .episodes==16' "$final/cases.json" > /dev/null
find "$final/scenes" -type f -print0 | /usr/bin/sort -z | /usr/bin/xargs -0 /usr/bin/sha256sum > "$final/scenes.sha256"
export PUPPYBOT_FINAL_OUTPUT="$final"
/usr/bin/bash "$resources/benchmark-final.sh" "$final/policies/baseline" baseline false
/usr/bin/bash "$resources/benchmark-final.sh" "$model" selected false
/usr/bin/bash "$resources/benchmark-final.sh" "$model" blackout true
/usr/bin/sha256sum -c "$resources/inputs.sha256" > "$out/resources-after.log"
/usr/bin/sha256sum -c "$final/scenes.sha256" > "$final/scenes-integrity.log"
[[ "$(/usr/bin/sha256sum "$model/weights.bin" | /usr/bin/cut -d' ' -f1)" == "$sha" ]]
/usr/bin/jq -s --arg candidate "$candidate" -f "$resources/final-report.jq" "$final/score-baseline.json" "$final/score-selected.json" "$final/score-blackout.json" > "$final/raw-comparison.json"
/usr/bin/jq '. + {improvesBaseline:(.selected.physicalReturns>.baseline.physicalReturns or (.selected.physicalReturns==.baseline.physicalReturns and .selected.physicalReturns>0 and .selected.meanSuccessfulSimulationSeconds<.baseline.meanSuccessfulSimulationSeconds)),blackoutHasFewerReturns:(.blackout.physicalReturns<.selected.physicalReturns),automaticPromotion:false}' "$final/raw-comparison.json" > "$out/comparison.json"
echo 'Held-out and blackout comparisons completed; inspect the results before promotion.'
