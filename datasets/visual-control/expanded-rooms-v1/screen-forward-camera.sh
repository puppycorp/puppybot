#!/usr/bin/env bash
# Exploratory comparison only: existing weights were trained on the old pose.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
pilot="$base/camera-forward-pilot-v3"
probe="$base/correction-probe-v1"
out="$pilot/actor-screen-v1"
policy="$base/return-quick-v1/model"
[[ ! -e "$out/run.exit" && ! -e "$out/cases" ]]
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
cd "$project"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
sha="$(/usr/bin/sha256sum "$policy/weights.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$sha" '.episodes==8 and .completedRecordings==8 and .auditedEpisodes==8 and .auditFailures==0 and all(.rows[];.policyWeightsSHA256==$sha)' "$probe/score-screen-return-quick-v1.json" > /dev/null
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
export PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
mkdir "$out/cases"
cd "$pilot/runtime"
for index in 0 1 2 3 16 17 18 19;do
    layout=$((18+index/16));scene=$((index%16));seed=$((9960000+index))
    source="$probe/scenes/$layout/$scene";destination="$out/cases/$index"
    extra=();if ((layout%2));then extra+=(--hidden-target);fi
    ./build/flex/control/control run --policy "$policy" --scene "$source" --output "$destination" --episodes 1 --seed "$seed" --horizon 300 "${extra[@]}" > "$out/cases/$index.log" 2>&1
    /usr/bin/jq -e --arg sha "$sha" '.complete and .episodes==1 and (.rows|length)==1 and .rows[0].policyWeightsSHA256==$sha and .rows[0].maximumBrickDistanceM==0.35 and (.rows[0].suppliedMap|not) and (.rows[0].taskEventHint|not)' "$destination/summary.json" > /dev/null
    /usr/bin/cmp "$destination/$seed/scene/case.json" "$source/case.json"
    /usr/bin/cmp "$destination/$seed/scene/environment.bin" "$source/environment.bin"
    ./build/flex/control/control verify --run "$destination/$seed" --policy "$destination/policy" --output "$destination/verified" > "$out/cases/$index-verified.log" 2>&1
    /usr/bin/jq -e --arg sha "$sha" '.passed and .commandReplayMaxAbsError==0 and .weightsSHA256==$sha and .taskEventHintAbsent and (.blackout|not)' "$destination/verified/result.json" > /dev/null
    returned="$(/usr/bin/tail -n 1 "$destination/$seed/decisions.jsonl" | /usr/bin/jq -r '.state.case.passed')"
    /usr/bin/jq --argjson index "$index" --argjson layout "$layout" --argjson scene "$scene" --argjson returned "$returned" '.rows[0]+{caseIndex:$index,layoutId:$layout,sceneId:$scene,recordingCompleted:true,auditPassed:true,recordedPhysicalReturn:$returned,physicalReturned:$returned}' "$destination/summary.json" > "$destination/benchmark-row.json"
done
/usr/bin/jq -s '{candidate:"balanced-camera-existing-policy",episodes:length,completedRecordings:(map(select(.recordingCompleted))|length),auditedEpisodes:(map(select(.auditPassed))|length),auditFailures:(map(select(.auditPassed|not))|length),physicalReturns:(map(select(.physicalReturned))|length),auditedApproaches:(map(select(.auditPassed and .found))|length),openReturns:(map(select(.layoutId==18 and .physicalReturned))|length),hiddenReturns:(map(select(.layoutId==19 and .physicalReturned))|length),meanSuccessfulSimulationSeconds:(map(select(.physicalReturned)|.simulationSeconds)|if length>0 then add/length else null end),rows:sort_by(.caseIndex)}' "$out/cases/"*/benchmark-row.json > "$out/score.json"
/usr/bin/jq -e '.episodes==8 and .auditedEpisodes==8 and .auditFailures==0 and ([.rows[].caseIndex]|unique)==[0,1,2,3,16,17,18,19]' "$out/score.json" > /dev/null
cd "$project"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
/usr/bin/jq -n --slurpfile baseline "$probe/score-screen-return-quick-v1.json" --slurpfile candidate "$out/score.json" '{exploratory:true,trainedForNewCameraPose:false,matchedCases:true,baselineCamera:"compact-legacy",candidateCamera:"compact-balanced",baseline:$baseline[0],candidate:$candidate[0],heldOutGeneralizationNotEstablished:true,retainedPolicyOverwritten:false}' > "$out/comparison.json"
echo 'Matched camera-pose screen completed; no model promotion.'
