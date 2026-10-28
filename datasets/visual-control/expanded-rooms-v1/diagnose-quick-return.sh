#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
quick="$base/contact-quick-v1"
screen="$base/correction-probe-v1/screen-contact-quick-v1/1"
run="$screen/9960001"
out="${1:?New output directory is required}"
[[ "$(< "$quick/run.exit")" == 0 && ! -e "$out" ]]
/usr/bin/jq -e '.exploratory and .allEpisodeAuditsPassed and (.qualifiesForPromotion|not)' "$quick/comparison.json" > /dev/null
/usr/bin/jq -e '.caseIndex==1 and .auditPassed and .recordingCompleted and .found and (.physicalReturned|not)' "$screen/benchmark-row.json" > /dev/null
/usr/bin/jq -e '.passed and .commandReplayMaxAbsError==0 and .consumptionEventsProjected==1' "$screen/verified/result.json" > /dev/null
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
/usr/bin/jq -s '[to_entries[]|{index:.key,step:.value.step,action:.value.action,contact:.value.proprio[5],consumed:.value.state.findReturn.consumedIndex,pose:.value.state.pose,box:.value.state.case.container.position,vision:.value.state.case.dockVision.valid,stable:.value.state.findReturn.stableReturnObservations}] | ([.[]|select(.consumed>=0)]|first) as $first | [.[]|select(.index>$first.index)|.distance=((.pose[0]-.box[0]) as $x|(.pose[1]-.box[1]) as $y|($x*$x+$y*$y)|sqrt)] | {exploratory:true,postHocSimulatorPositionsOnly:true,actorInputsUnchanged:true,firstConsumedAction:$first.index,postDetectionActions:length,forward:(map(select(.action[1]>0))|length),reverse:(map(select(.action[1]<0))|length),stop:(map(select(.action[1]==0))|length),blocked:(map(select(.contact>0.5))|length),closestRobotCenterToBoxM:(map(.distance)|min),finalRobotCenterToBoxM:.[-1].distance,validBoxVisionFrames:(map(select(.vision))|length),maxStableReturnObservations:(map(.stable)|max)}' "$run/decisions.jsonl" > "$out/result.json"
/usr/bin/jq -e '.exploratory and .postHocSimulatorPositionsOnly and .actorInputsUnchanged and .postDetectionActions>0 and (.forward+.reverse+.stop)==.postDetectionActions' "$out/result.json" > /dev/null
echo 'Audited post-detection trajectory summarized; this is one exploratory episode.'
