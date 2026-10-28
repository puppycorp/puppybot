#!/usr/bin/env bash
# Verify contact is aligned to the previous observation and failures are rejected.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
mkdir -p "$out/probe" "$out/episode" "$out/verified"
printf '{"passed":true,"commandReplayMaxAbsError":0,"weightsSHA256":"test","taskEventHintAbsent":true}\n' > "$out/verified/result.json"
printf '{"proprio":[0,0,0,0,0,1,0]}\n{"proprio":[0,0,0,0,0,0,0]}\n{"proprio":[0,0,0,0,0,1,0]}\n{"proprio":[0,0,0,0,0,1,0]}\n' > "$out/episode/decisions.jsonl"
printf '{"weightsSHA256":"test","actualCommandsReplayedExactly":true,"counterfactualDidNotAlterServerState":true,"neutralFeedbackHypothetical":true,"offlineCounterfactualOnly":true,"simulatorPhaseUsedOnlyForAnalysis":true,"rows":[{"actionIndex":0,"actualReturning":false,"actualClass":0,"neutralFeedbackClass":0,"neutralFeedbackChangesAction":false},{"actionIndex":1,"actualReturning":false,"actualClass":0,"neutralFeedbackClass":3,"neutralFeedbackChangesAction":true},{"actionIndex":2,"actualReturning":false,"actualClass":0,"neutralFeedbackClass":0,"neutralFeedbackChangesAction":false},{"actionIndex":3,"actualReturning":true,"actualClass":0,"neutralFeedbackClass":0,"neutralFeedbackChangesAction":false}]}\n' > "$out/probe/result.json"
driver="$project/datasets/visual-control/expanded-rooms-v1/summarize-blocked-feedback.sh"
bash "$driver" "$out/probe" "$out/episode" "$out/good" > "$out/good.log" 2>&1
jq -e '.passed and .frames==4 and .blockedSearchInputFrames==1 and .actionsChangedWhenPriorDriveFeedbackNeutralized==1 and .actualForward==1 and .hypotheticalReverse==1 and .initialActionExcluded and .contactInputTakenFromPreviousRecordedObservation and .offlineCounterfactualOnly' "$out/good/summary.json" > /dev/null
jq '.rows[1].actionIndex=2' "$out/probe/result.json" > "$out/altered.json";cp "$out/altered.json" "$out/probe/result.json"
if bash "$driver" "$out/probe" "$out/episode" "$out/bad-order" > "$out/bad-order.log" 2>&1;then echo 'Misaligned probe was accepted.' >&2;exit 1;fi
[[ ! -e "$out/bad-order/summary.json" || ! -s "$out/bad-order/summary.json" ]]
printf '{"weightsSHA256":"test","actualCommandsReplayedExactly":true,"counterfactualDidNotAlterServerState":true,"neutralFeedbackHypothetical":true,"offlineCounterfactualOnly":true,"simulatorPhaseUsedOnlyForAnalysis":true,"rows":[{"actionIndex":0,"actualReturning":false,"actualClass":0,"neutralFeedbackClass":0,"neutralFeedbackChangesAction":false},{"actionIndex":1,"actualReturning":false,"actualClass":0,"neutralFeedbackClass":3,"neutralFeedbackChangesAction":false},{"actionIndex":2,"actualReturning":false,"actualClass":0,"neutralFeedbackClass":0,"neutralFeedbackChangesAction":false},{"actionIndex":3,"actualReturning":true,"actualClass":0,"neutralFeedbackClass":0,"neutralFeedbackChangesAction":false}]}\n' > "$out/probe/result.json"
if bash "$driver" "$out/probe" "$out/episode" "$out/bad-flag" > "$out/bad-flag.log" 2>&1;then echo 'Inconsistent intervention flag was accepted.' >&2;exit 1;fi
[[ ! -e "$out/bad-flag/summary.json" || ! -s "$out/bad-flag/summary.json" ]]
echo 'Blocked feedback summary checks pre-action alignment and rejects mismatched probes.'
