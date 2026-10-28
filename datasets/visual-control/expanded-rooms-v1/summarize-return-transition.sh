#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
output="${1:?New output file is required}"
[[ ! -e "$output" ]]
/usr/bin/jq -e --slurpfile coverage "$base/return-admission-v1/coverage.json" '.dataSHA256==$coverage[0].dataSHA256 and .actorInputsUnchanged and .eventHintInputAlwaysZero and .visibilityHeuristicNotSegmentation and (.rows|length)==14' "$base/return-event-survey-v1/result.json" > /dev/null
/usr/bin/jq -e --slurpfile coverage "$base/return-admission-v1/coverage.json" '.dataSHA256==$coverage[0].dataSHA256 and .allStudentCommandsReplayedExactly and .actorInputsUnchanged and .phaseReadoutNotDirectActorInput and (.rows|length)==14' "$base/return-phase-probe-v1/result.json" > /dev/null
/usr/bin/jq -e --slurpfile phase "$base/return-phase-probe-v1/result.json" '.weightsSHA256==$phase[0].weightsSHA256 and .actualCommandsReplayedExactly and .phaseHeadReadOnly and (.rows|length)==300' "$base/return-phase-autonomous-v1/result.json" > /dev/null
/usr/bin/jq -n --slurpfile event "$base/return-event-survey-v1/result.json" --slurpfile phase "$base/return-phase-probe-v1/result.json" --slurpfile autonomous "$base/return-phase-autonomous-v1/result.json" '
  $event[0].rows as $e | $phase[0].rows as $p | $autonomous[0].rows as $a |
  {scope:"Training-only uncalibrated phase readout and raw image changes; not causal evidence, promotion evidence or a task-event input",weightsSHA256:$phase[0].weightsSHA256,dataSHA256:$event[0].dataSHA256,
   imageTransition:{histories:($e|length),lastSearchFrameHeuristicMatches:([$e[]|select(.targetHeuristicMatchedLastSearchFrame)]|length),meanEventRGBDifference:(([$e[].eventAbsoluteRGBDifference]|add)/($e|length)),meanPriorRGBDifference:(([$e[].priorMeanAbsoluteRGBDifference]|add)/($e|length)),eventBelowMedianPriorChange:([$e[]|select(.fractionOfPriorChangesAtMostEventChange<0.5)]|length),visibilityHeuristicNotSegmentation:true},
   teacherApproachStudentReturn:{histories:($p|length),studentCommandsReplayed:([$p[].studentCommandsReplayed]|add),searchFrames:([$p[].searchFrames]|add),searchAboveHalf:([$p[].searchAboveHalf]|add),returnFrames:([$p[].returnFrames]|add),returnAboveHalf:([$p[].returnAboveHalf]|add),lastFiveSearchMean:(([$p[].lastFiveSearchMean]|add)/($p|length)),firstFiveReturnMean:(([$p[].firstFiveReturnMean]|add)/($p|length))},
   autonomousApproach:{episodes:1,searchFrames:([$a[]|select(.actualReturning|not)]|length),searchAboveHalf:([$a[]|select((.actualReturning|not) and .predictedReturnProbability>0.5)]|length),returnFrames:([$a[]|select(.actualReturning)]|length),returnAboveHalf:([$a[]|select(.actualReturning and .predictedReturnProbability>0.5)]|length),returned:false,replayExact:$autonomous[0].actualCommandsReplayedExactly},actorInputsUnchanged:true}' > "$output"
/usr/bin/jq -e '.imageTransition.histories==14 and .teacherApproachStudentReturn.studentCommandsReplayed==1230 and .autonomousApproach.searchFrames==59 and .autonomousApproach.returnFrames==241 and .actorInputsUnchanged' "$output" > /dev/null
echo 'Return-transition diagnostic summary written from audited replays.'
