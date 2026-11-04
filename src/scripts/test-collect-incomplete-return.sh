#!/usr/bin/env bash
# Live collection must retain incomplete return windows only with opt-in.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
runtime="$(realpath "${1:?Isolated control runtime required}")"
policy="$(realpath "${2:?Frozen policy required}")"
catalog="$(realpath "${3:?Two-scene catalog required}")"
out="$(realpath -m "${4:?New output directory required}")";[[ ! -e "$out" ]];mkdir "$out"
sha256sum "$runtime/build/flex/control/control" "$runtime/build/flex/control/simulator" "$policy/weights.bin" "$policy/receipt.json" "$catalog"/{0,1}/{case.json,environment.bin,layout.json} > "$out/inputs.sha256"
cd "$runtime";control=./build/flex/control/control
"$control" correct --policy "$policy" --scene-catalog "$catalog" --output "$out/runs" --episodes 2 --validation 1 --rollin 60 --rollin-min 60 --horizon 354 --label-rollin --return-rollin --allow-incomplete --coverage-teacher --seed 1998000 --large-model > "$out/collect.log" 2>&1
jq -e '.complete and .episodes==2 and .teacherCompleted==1 and .incompleteEpisodes==1 and .incompletePrefixesRetained and (.studentSuccessClaimed|not)' "$out/runs/report.json" > /dev/null
jq -e '.allowIncomplete and .recordedHorizon==354 and .terminationReason=="horizon" and .studentBeginsAfterConsumption and .studentStartAction>=1 and .studentActions>=1 and .studentActions<.scheduledRollinActions and (.studentCompletedBeforeHandoff|not)' "$out/runs/expert-0/supervision.json" > /dev/null
jq -e '(.success|not) and .steps==354' "$out/runs/expert-0/result.json" > /dev/null
jq -e '.allowIncomplete and .terminationReason=="success" and .studentBeginsAfterConsumption and .studentActions>=1' "$out/runs/expert-1/supervision.json" > /dev/null
"$control" pack-data --data "$out/runs/data.bin" --output "$out/packed" > "$out/pack.log" 2>&1
if "$control" verify-data --run "$out/runs" --data "$out/packed/data.bin" --output "$out/default-rejected" --large-model > "$out/default-rejected.log" 2>&1;then echo 'Incomplete return data was accepted without opt-in.' >&2;exit 1;fi
[[ ! -e "$out/default-rejected/result.json" ]]
"$control" verify-data --run "$out/runs" --data "$out/packed/data.bin" --output "$out/verified" --allow-incomplete --large-model > "$out/verified.log" 2>&1
actions="$(jq -er '.studentRollinActions' "$out/runs/report.json")"
jq -e --argjson actions "$actions" '.passed and .episodes==2 and .incompleteEpisodes==1 and .successfulEpisodes==1 and .studentRollinCommandsReplayed==$actions and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .denseOracleLabels and .zeroPaddingChecked and .taskEventHintAbsent and (.incompleteEpisodesClaimedSuccessful|not)' "$out/verified/result.json" > /dev/null
for i in 0 1;do bash "$project/datasets/visual-control/expanded-rooms-v1/audit-coverage-teacher-v2.sh" "$out/runs/expert-$i" "$out/goal-audit-$i" > "$out/goal-audit-$i.log" 2>&1;done
sha256sum -c "$out/inputs.sha256" > "$out/integrity.log"
echo 'Live return collection retains and verifies the incomplete episode with explicit opt-in.'
