#!/usr/bin/env bash
# Evaluate a frozen large policy on the eight distinct-start development rooms.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
base="$project/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1"
scene_set="${PUPPYBOT_DIVERSE_SCENE_SET:-standard}"
if [[ "$scene_set" == standard ]];then scenes="$(realpath "$root/diverse-development-v1")";first_layout=180;first_seed=9980000
elif [[ "$scene_set" == wide-heading ]];then scenes="$(realpath "$root/wide-heading-development-v1")";first_layout=218;first_seed=9990000
else echo 'Expected standard or wide-heading scene set.' >&2;exit 2;fi
runtime="$root/phase-large-tests-v1/runtime";measure="$root/runtime/measure-brick-distance"
policy="${PUPPYBOT_DIVERSE_POLICY:?Frozen policy required}"
capacity="${PUPPYBOT_DIVERSE_WAIT_RUN:?Previous benchmark required}"
out="${PUPPYBOT_DIVERSE_BENCHMARK_OUT:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
[[ "$(< "$scenes/run.exit")" == 0 ]]
if [[ "$scene_set" == standard ]];then
    jq -e '.passed and .developmentOnly and .episodes==8 and .openRooms==4 and .twoRoomLayouts==4 and .uniqueStartingPoses==8 and .exactCaseAndEnvironmentFilesDisjointFrom316HistoryCorpusAndExistingDevelopment and .reservedFinalUntouched' "$scenes/summary.json" > /dev/null
else
    smoke="$root/wide-heading-smoke-v1"
    [[ "$(< "$smoke/run.exit")" == 0 ]]
    jq -e '.passed and .developmentOnly and .episodes==8 and .openRooms==4 and .twoRoomLayouts==4 and .uniqueStartingPoses==8 and .wideHeading and .headingsBeyond90Degrees>=2 and .geometryChecked and .exactCaseAndEnvironmentFilesDisjointFromCorporaAndPriorDevelopment and .reservedFinalUntouched' "$scenes/summary.json" > /dev/null
    jq -e '.passed and .episodes==8 and .uniqueStartingPoses==8 and .physicalSpawnsChecked and .initialCameraFramesChecked and .actionsReplayed==8 and .sceneAndInitialPosesMatched and .wholeEpisodePerformanceNotMeasured' "$smoke/summary.json" > /dev/null
    sha256sum -c "$smoke/inputs.sha256" > "$out/smoke-integrity-before.log"
fi
while [[ ! -f "$capacity.exit" ]];do [[ -f "$capacity.pid" ]] && kill -0 "$(< "$capacity.pid")" || { echo 'Previous benchmark ended without a status.' >&2;exit 1; };sleep 20;done
printf '%s\n' "$(< "$capacity.exit")" > "$out/prior-benchmark-status.txt"
sha="$(sha256sum "$policy/weights.bin" | cut -d' ' -f1)";data_sha="$(jq -er '.dataSHA256' "$policy/receipt.json")"
jq -e --arg sha "$sha" '.weightsSHA256==$sha and .memoryWidth==256 and (.taskFeedback|not)' "$policy/receipt.json" > /dev/null
# Only accept corpora included in the exact-scene disjointness audit.
old="$root/student-only-admission-v1/expanded/data.bin";new="$root/coverage-v2-student-admission-v1/expanded/data.bin"
old_sha="$(sha256sum "$old" | cut -d' ' -f1)";new_sha="$(sha256sum "$new" | cut -d' ' -f1)"
corpus_audit=""
if [[ "$data_sha" != "$old_sha" && "$data_sha" != "$new_sha" ]];then
    corpus_audit="$(realpath "${PUPPYBOT_DIVERSE_CORPUS_AUDIT:?An audit for this policy corpus is required}")"
    jq -e --arg sha "$data_sha" --arg scenes "$scenes" '.passed and .developmentOnly and .dataSHA256==$sha and .sceneDirectory==$scenes and .episodes==8 and .exactCaseAndEnvironmentFilesDisjoint and .actorInputsUnchanged and .reservedFinalUntouched' "$corpus_audit/summary.json" > /dev/null
    sha256sum -c "$corpus_audit/inputs.sha256" > "$out/corpus-integrity-before.log"
    sha256sum -c "$corpus_audit/corpus-scenes.sha256" > "$out/corpus-scenes-before.log"
fi
sha256sum -c "$scenes/inputs.sha256" > "$out/scenes-integrity-before.log"
sha256sum -c "$scenes/prior-inputs.sha256" > "$out/prior-integrity-before.log"
sha256sum "$policy/weights.bin" "$policy/policy" "$policy/receipt.json" "$runtime/build/flex/control/control" "$runtime/build/flex/control/simulator" "$measure" "$scenes/summary.json" > "$out/inputs.sha256"
if [[ "$scene_set" == wide-heading ]];then
    sha256sum "$smoke/summary.json" "$smoke/inputs.sha256" >> "$out/inputs.sha256"
    smoke_sha="$(jq -er '.policyWeightsSHA256' "$smoke/summary.json")"
    for ((index=0;index<8;index++));do
        seed=$((9990000+index));scene="$scenes/catalog/$index";prior="$smoke/$index/$seed";verified="$smoke/$index/verified/result.json"
        jq -e --arg sha "$smoke_sha" '.passed and .commandReplayMaxAbsError==0 and .modelCommandsReplayed==1 and .PNGAndActorFramesMatched==2 and .weightsSHA256==$sha and .returnPoseChecked and .taskEventHintAbsent' "$verified" > /dev/null
        for file in case.json environment.bin;do cmp "$scene/$file" "$prior/scene/$file";done
        jq -n --slurpfile scene "$scene/layout.json" --slurpfile initial "$prior/initial.json" 'def abs: if .<0 then -. else . end; all(range(0;3); . as $i | (($scene[0].startPose[$i]-$initial[0].pose[$i])|abs)<0.00001)' | jq -e . > /dev/null
        sha256sum "$verified" "$prior/initial.json" "$prior/scene/case.json" "$prior/scene/environment.bin" >> "$out/inputs.sha256"
    done
fi
if [[ -n "$corpus_audit" ]];then sha256sum "$corpus_audit/summary.json" "$corpus_audit/inputs.sha256" "$corpus_audit/corpus-scenes.sha256" >> "$out/inputs.sha256";fi
export PATH="$base/unseen-benchmark-v2/native-path:$PATH" XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$runtime"
attempt() {
    local index="$1"
    local layout=$((first_layout+index)) seed=$((first_seed+index)) scene="$scenes/catalog/$index" destination="$out/$index"
    local extra=(--large-model);if (( layout%2 ));then extra+=(--hidden-target);fi
    ./build/flex/control/control run --policy "$policy" --scene "$scene" --output "$destination" --episodes 1 --seed "$seed" --horizon 300 "${extra[@]}" > "$destination.log" 2>&1
    jq -e --arg sha "$sha" '.complete and .episodes==1 and (.rows|length)==1 and .rows[0].policyWeightsSHA256==$sha and .rows[0].maximumBrickDistanceM==0.35 and (.rows[0].suppliedMap|not) and (.rows[0].taskEventHint|not)' "$destination/summary.json" > /dev/null
    for file in case.json environment.bin;do cmp "$scene/$file" "$destination/$seed/scene/$file";done
    # The initial pose is reference data used only to verify the test setup.
    jq -n --slurpfile scene "$scene/layout.json" --slurpfile initial "$destination/$seed/initial.json" 'def abs: if .<0 then -. else . end; all(range(0;3); . as $i | (($scene[0].startPose[$i]-$initial[0].pose[$i])|abs)<0.00001)' | jq -e . > /dev/null
    ./build/flex/control/control verify --run "$destination/$seed" --policy "$destination/policy" --output "$destination/verified" --large-model > "$destination/verified.log" 2>&1
    jq -e --arg sha "$sha" '.passed and .commandReplayMaxAbsError==0 and .weightsSHA256==$sha and .returnPoseChecked and .taskEventHintAbsent' "$destination/verified/result.json" > /dev/null
    "$measure" "$destination/$seed" "$destination/distance" > "$destination/distance.log" 2>&1
    decision_sha="$(sha256sum "$destination/$seed/decisions.jsonl" | cut -d' ' -f1)"
    jq -e --arg sha "$decision_sha" --slurpfile summary "$destination/summary.json" '.decisionsSHA256==$sha and .evaluationOnly and (.referencePositionsEnteredActor|not) and .consumed==$summary[0].rows[0].found' "$destination/distance/result.json" > /dev/null
    returned="$(tail -n 1 "$destination/$seed/decisions.jsonl" | jq -r '.state.case.passed')"
    jq --slurpfile distance "$destination/distance/result.json" --slurpfile metadata "$scene/layout.json" --argjson index "$index" --argjson layout "$layout" --argjson returned "$returned" '.rows[0]+{caseIndex:$index,layoutId:$layout,startPose:$metadata[0].startPose,recordingCompleted:true,auditPassed:true,physicalReturned:$returned,closestBrickDistanceM:$distance[0].closestPlanarBaseToBrickM}' "$destination/summary.json" > "$destination/benchmark-row.json"
}
for ((wave=0;wave<8;wave+=2));do
    attempt "$wave" & a=$!;attempt "$((wave+1))" & b=$!;status=0
    wait "$a" || status=1;wait "$b" || status=1
    (( status==0 )) || { echo 'A development episode failed; recordings were retained.' >&2;exit 1; }
done
jq -s --arg sha "$sha" --arg scene_set "$scene_set" '{passed:true,developmentOnly:true,sceneSet:$scene_set,policyWeightsSHA256:$sha,episodes:length,auditedEpisodes:(map(select(.auditPassed))|length),approaches:(map(select(.found))|length),returns:(map(select(.physicalReturned))|length),openApproaches:(map(select((.layoutId%2)==0 and .found))|length),twoRoomApproaches:(map(select((.layoutId%2)==1 and .found))|length),twoRoomExits:(map(select((.layoutId%2)==1 and .leftStartRoom))|length),meanSuccessfulSimulationSeconds:(map(select(.physicalReturned)|.simulationSeconds)|if length>0 then add/length else null end),uniqueStartingPoses:(map(.startPose)|unique|length),reservedFinalStillRequired:true,automaticPromotion:false,rows:sort_by(.caseIndex)}' "$out/"*/benchmark-row.json > "$out/score.json"
jq -e '.passed and .episodes==8 and .auditedEpisodes==8 and .uniqueStartingPoses==8 and ([.rows[].caseIndex]|sort)==[range(0;8)] and .reservedFinalStillRequired and (.automaticPromotion|not)' "$out/score.json" > /dev/null
sha256sum -c "$scenes/inputs.sha256" > "$out/scenes-integrity-after.log"
sha256sum -c "$scenes/prior-inputs.sha256" > "$out/prior-integrity-after.log"
if [[ "$scene_set" == wide-heading ]];then sha256sum -c "$smoke/inputs.sha256" > "$out/smoke-integrity-after.log";fi
if [[ -n "$corpus_audit" ]];then sha256sum -c "$corpus_audit/inputs.sha256" > "$out/corpus-integrity-after.log";sha256sum -c "$corpus_audit/corpus-scenes.sha256" > "$out/corpus-scenes-after.log";fi
sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
echo 'Distinct-start development benchmark completed with replay and physical audits.'
