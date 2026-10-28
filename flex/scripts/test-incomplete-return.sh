#!/usr/bin/env bash
# Recheck a retained failed return pair without modifying the original files.
set -euo pipefail
runtime="$(realpath "${1:?Isolated control runtime required}")"
source="$(realpath "${2:?Retained correction runs required}")"
out="$(realpath -m "${3:?New output directory required}")";[[ ! -e "$out" ]];mkdir "$out"
sha256sum "$source/data.partial.bin" "$source"/expert-{0,1}/{supervision.json,result.json,decisions.jsonl} > "$out/source-inputs.sha256"
jq -e '(.success|not) and .steps==354' "$source/expert-0/result.json" > /dev/null
jq -e '.success and .steps<354' "$source/expert-1/result.json" > /dev/null
cp -a --reflink=auto "$source" "$out/runs"
cp --reflink=auto "$source/data.partial.bin" "$out/runs/data.bin"
for i in 0 1;do
    reason=horizon;if (( i==1 ));then reason=success;fi
    jq --arg reason "$reason" '.allowIncomplete=true | .recordedHorizon=354 | .terminationReason=$reason' "$source/expert-$i/supervision.json" > "$out/runs/expert-$i/supervision.json"
done
cd "$runtime";control=./build/flex/control/control
if "$control" verify-data --run "$out/runs" --data "$out/runs/data.bin" --output "$out/default-rejected" --large-model > "$out/default-rejected.log" 2>&1;then echo 'Incomplete return data was accepted without opt-in.' >&2;exit 1;fi
[[ ! -e "$out/default-rejected/result.json" ]]
"$control" verify-data --run "$out/runs" --data "$out/runs/data.bin" --output "$out/verified" --allow-incomplete --large-model > "$out/verified.log" 2>&1
jq -e '.passed and .episodes==2 and .incompleteEpisodes==1 and .successfulEpisodes==1 and .studentRollinCommandsReplayed==96 and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .denseOracleLabels and .zeroPaddingChecked and .taskEventHintAbsent and (.incompleteEpisodesClaimedSuccessful|not)' "$out/verified/result.json" > /dev/null
cp -a --reflink=auto "$out/runs" "$out/altered-runs"
jq '.studentCompletedBeforeHandoff=true' "$out/altered-runs/expert-0/supervision.json" > "$out/altered.json";mv "$out/altered.json" "$out/altered-runs/expert-0/supervision.json"
if "$control" verify-data --run "$out/altered-runs" --data "$out/runs/data.bin" --output "$out/altered-rejected" --allow-incomplete --large-model > "$out/altered-rejected.log" 2>&1;then echo 'False student success was accepted.' >&2;exit 1;fi
[[ ! -e "$out/altered-rejected/result.json" ]]
jq '.studentStartAction-=1 | .studentActions+=1' "$out/runs/expert-0/supervision.json" > "$out/altered-runs/expert-0/supervision.json"
if "$control" verify-data --run "$out/altered-runs" --data "$out/runs/data.bin" --output "$out/early-window-rejected" --allow-incomplete --large-model > "$out/early-window-rejected.log" 2>&1;then echo 'Return roll-in before brick consumption was accepted.' >&2;exit 1;fi
[[ ! -e "$out/early-window-rejected/result.json" ]]
rg -Fq 'return student window does not begin at the first consumed-brick frame' "$out/early-window-rejected.log"
sha256sum -c "$out/source-inputs.sha256" > "$out/source-integrity.log"
echo 'Incomplete return prefixes require opt-in, replay exactly and reject false success or early handoff.'
