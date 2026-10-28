#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
root="$base/generalization-benchmark-v1"
training="$base/matched-training-v3"
unseen="$base/unseen-benchmark-v2"
trap 'status=$?; printf "%s\n" "$status" > "$root/run.exit"' EXIT
printf '%s\n' "$BASHPID" > "$root/run.pid"
cd "$project"
while [[ ! -f "$training/run.exit" ]];do
    [[ -f "$training/run.pid" ]] && kill -0 "$(< "$training/run.pid")" || { echo 'Matched training disappeared without a terminal status.';exit 1; }
    /usr/bin/sleep 10
done
[[ "$(< "$training/run.exit")" == 0 ]]
/usr/bin/sha256sum -c "$root/inputs.sha256" > "$root/integrity-before.log"
/usr/bin/jq -e '.passed and .episodes==16 and .layouts==[20,21,22,23] and .casesNotInPriorDataOrDevelopment and .environmentFilesNotInPriorDataOrDevelopment' "$root/cases.json" > /dev/null
/usr/bin/jq -e '.allEpisodeAuditsPassed' "$training/comparison.json" > /dev/null
/usr/bin/jq -s 'map(select(.episodes==32 and .auditedEpisodes==32 and .auditFailures==0 and .physicalReturns>=24 and .openReturns>=8 and .hiddenReturns>=8))|sort_by([(-.physicalReturns),.meanSuccessfulSimulationSeconds,.candidate])|{qualified:(length>0),selected:.[0]}' "$unseen/score-continued-172.json" "$unseen/score-continued-202.json" > "$root/selection.json"
if ! /usr/bin/jq -e '.qualified' "$root/selection.json" > /dev/null;then
    /usr/bin/jq -n '{skipped:true,reason:"Neither matched candidate met the 32-case qualification",reservedFinalStillRequired:true,retainedPolicyOverwritten:false}' > "$root/comparison.json"
    echo 'Four-layout check skipped because neither model qualified.';exit 0
fi
candidate="$(/usr/bin/jq -r '.selected.candidate' "$root/selection.json")"
model="$training/old";if [[ "$candidate" == continued-202 ]];then model="$training/expanded";else [[ "$candidate" == continued-172 ]];fi
sha="$(/usr/bin/sha256sum "$model/weights.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$sha" '.weightsSHA256==$sha and (.taskFeedback|not)' "$model/receipt.json" > /dev/null
for layout in 20 21 22 23;do for scene in 0 5 10 15;do
    casehash="$(/usr/bin/sha256sum "$root/scenes/$layout/$scene/case.json" | /usr/bin/cut -d' ' -f1)"
    envhash="$(/usr/bin/sha256sum "$root/scenes/$layout/$scene/environment.bin" | /usr/bin/cut -d' ' -f1)"
    index=$(((layout-20)*4+scene/5));seed=$((9970000+index))
    /usr/bin/jq -e --argjson index "$index" --argjson seed "$seed" --argjson layout "$layout" --argjson scene "$scene" --arg casehash "$casehash" --arg envhash "$envhash" '[.rows[]|select(.index==$index and .seed==$seed and .layout==$layout and .scene==$scene and .caseSHA256==$casehash and .environmentSHA256==$envhash)]|length==1' "$root/cases.json" > /dev/null
done;done
bash "$root/benchmark.sh" "$root/policies/baseline" baseline
bash "$root/benchmark.sh" "$model" selected
/usr/bin/sha256sum -c "$root/inputs.sha256" > "$root/integrity-after.log"
[[ "$(/usr/bin/sha256sum "$model/weights.bin" | /usr/bin/cut -d' ' -f1)" == "$sha" ]]
/usr/bin/jq -s --arg candidate "$candidate" '{skipped:false,candidate:$candidate,baseline:.[0],selected:.[1],allEpisodeAuditsPassed:all(.[]; .completedRecordings==16 and .auditedEpisodes==16 and .auditFailures==0),reservedFinalStillRequired:true,retainedPolicyOverwritten:false}' "$root/score-baseline.json" "$root/score-selected.json" > "$root/comparison.json"
echo 'Paired four-layout generalization check completed; reserved final layouts remain separate.'
