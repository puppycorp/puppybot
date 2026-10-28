#!/usr/bin/env bash
# Check simulator spawn, camera and replay for each wide-heading room.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
base="$project/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1"
scenes="$root/wide-heading-development-v1";runtime="$root/phase-large-tests-v1/runtime";policy="$root/student-only-training-v1/policy"
capacity="${PUPPYBOT_WIDE_SMOKE_WAIT_RUN:?Previous benchmark required}"
out="${PUPPYBOT_WIDE_SMOKE_OUT:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
[[ "$(< "$scenes/run.exit")" == 0 ]]
jq -e '.passed and .developmentOnly and .episodes==8 and .openRooms==4 and .twoRoomLayouts==4 and .uniqueStartingPoses==8 and .wideHeading and .headingsBeyond90Degrees>=2 and .geometryChecked and .exactCaseAndEnvironmentFilesDisjointFromCorporaAndPriorDevelopment and .physicalSpawnNotYetChecked' "$scenes/summary.json" > /dev/null
while [[ ! -f "$capacity.exit" ]];do [[ -f "$capacity.pid" ]] && kill -0 "$(< "$capacity.pid")" || { echo 'Previous benchmark ended without a status.' >&2;exit 1; };sleep 20;done
printf '%s\n' "$(< "$capacity.exit")" > "$out/prior-benchmark-status.txt"
sha="$(sha256sum "$policy/weights.bin" | cut -d' ' -f1)"
jq -e --arg sha "$sha" '.weightsSHA256==$sha and .memoryWidth==256 and (.taskFeedback|not)' "$policy/receipt.json" > /dev/null
cmp "$runtime/build/flex/control/simulator" "$root/workspace/build/flex/control/simulator"
sha256sum -c "$scenes/inputs.sha256" > "$out/scenes-integrity-before.log"
sha256sum -c "$scenes/prior-inputs.sha256" > "$out/prior-integrity-before.log"
sha256sum "$policy/weights.bin" "$policy/policy" "$policy/receipt.json" "$runtime/build/flex/control/control" "$runtime/build/flex/control/simulator" "$scenes/summary.json" > "$out/inputs.sha256"
export PATH="$base/unseen-benchmark-v2/native-path:$PATH" XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$runtime"
for ((index=0;index<8;index++));do
    layout=$((218+index));seed=$((9990000+index));scene="$scenes/catalog/$index";destination="$out/$index"
    extra=(--large-model);if (( layout%2 ));then extra+=(--hidden-target);fi
    ./build/flex/control/control run --policy "$policy" --scene "$scene" --output "$destination" --episodes 1 --seed "$seed" --horizon 1 "${extra[@]}" > "$out/$index.log" 2>&1
    jq -e --arg sha "$sha" '.complete and .episodes==1 and .rows[0].steps==1 and .rows[0].policyWeightsSHA256==$sha and (.rows[0].suppliedMap|not) and (.rows[0].taskEventHint|not)' "$destination/summary.json" > /dev/null
    for file in case.json environment.bin;do cmp "$scene/$file" "$destination/$seed/scene/$file";done
    jq -n --slurpfile scene "$scene/layout.json" --slurpfile initial "$destination/$seed/initial.json" 'def abs: if .<0 then -. else . end; all(range(0;3); . as $i | (($scene[0].startPose[$i]-$initial[0].pose[$i])|abs)<0.00001)' | jq -e . > /dev/null
    ./build/flex/control/control verify --run "$destination/$seed" --policy "$destination/policy" --output "$destination/verified" --large-model > "$out/$index-verified.log" 2>&1
    jq -e --arg sha "$sha" '.passed and .commandReplayMaxAbsError==0 and .modelCommandsReplayed==1 and .PNGAndActorFramesMatched==2 and .weightsSHA256==$sha and .returnPoseChecked and .taskEventHintAbsent' "$destination/verified/result.json" > /dev/null
    jq -nc --argjson index "$index" --argjson layout "$layout" --slurpfile meta "$scene/layout.json" '{caseIndex:$index,layoutId:$layout,startPose:$meta[0].startPose,sceneAndInitialPoseMatched:true,oneActionReplayed:true}' >> "$out/rows.jsonl"
done
sha256sum -c "$scenes/inputs.sha256" > "$out/scenes-integrity-after.log"
sha256sum -c "$scenes/prior-inputs.sha256" > "$out/prior-integrity-after.log"
sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
jq -s --arg sha "$sha" '{passed:true,developmentOnly:true,episodes:length,policyWeightsSHA256:$sha,uniqueStartingPoses:(map(.startPose)|unique|length),physicalSpawnsChecked:true,initialCameraFramesChecked:true,actionsReplayed:8,sceneAndInitialPosesMatched:all(.[];.sceneAndInitialPoseMatched and .oneActionReplayed),wholeEpisodePerformanceNotMeasured:true,rows:.}' "$out/rows.jsonl" > "$out/summary.json"
jq -e '.passed and .episodes==8 and .uniqueStartingPoses==8 and .physicalSpawnsChecked and .actionsReplayed==8 and .sceneAndInitialPosesMatched and .wholeEpisodePerformanceNotMeasured' "$out/summary.json" > /dev/null
echo 'All eight wide-heading spawns and one-step actor replays passed.'
