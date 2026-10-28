#!/usr/bin/env bash
# Verify the same-input join and reject changed pilot labels.
set -euo pipefail
out="$(realpath -m "${1:?New output directory required}")"
[[ ! -e "$out" ]]; mkdir "$out"
project="$(cd "$(dirname "$0")/../.." && pwd)"
bash "$project/flex/scripts/test-initial-conflict-scenes.sh" "$out/scene-fixture" > "$out/fixture.log"
fixture="$out/scene-fixture"
cp "$fixture/corpus/expert-0/actor-7.rgb" "$fixture/corpus/expert-1/actor-7.rgb"
pilot="$out/pilot"; mkdir -p "$pilot/runs" "$pilot/verified" "$pilot/goal-audit-0" "$pilot/goal-audit-1"
cp -a "$fixture/corpus/expert-0" "$pilot/runs/expert-0"
cp -a "$fixture/corpus/expert-1" "$pilot/runs/expert-1"
jq -n '{passed:true,episodes:2,teacherCompleted:2,studentAutonomousSuccessClaimed:false}' > "$pilot/summary.json"
jq -n '{passed:true,taskEventHintAbsent:true}' > "$pilot/verified/result.json"
for index in 0 1; do
    jq -n '{rooms:[[0,0,4,4]],startRoom:0}' > "$fixture/corpus/expert-$index/scene/layout.json"
    cp "$fixture/corpus/expert-$index/scene/case.json" "$fixture/corpus/expert-$index/scene/environment.bin"
    cp "$fixture/corpus/expert-$index/scene/environment.bin" "$pilot/runs/expert-$index/scene/environment.bin"
    jq -n --arg path "$fixture/corpus/expert-$index/scene" '{sourceScene:$path}' > "$fixture/corpus/expert-$index/supervision.json"
    jq -n --arg path "$fixture/corpus/expert-$index/scene" '{sourceScene:$path}' > "$pilot/runs/expert-$index/supervision.json"
    jq -n '{passed:true,reconstructedFromRoomBoundsAndRecordedCamera:true,oracleLabelsMatched:true,brickPositionNotReadBySearchReconstruction:true,teacherGeometryPrivileged:true}' > "$pilot/goal-audit-$index/result.json"
    jq -nc '{step:0,source:"coverage",label:[0,1]}' > "$pilot/runs/expert-$index/teacher-search.jsonl"
done
analysis="$project/datasets/visual-control/expanded-rooms-v1/audit-coverage-conflict-pilot.sh"
"$analysis" "$fixture/good/summary.json" "$pilot" "$out/good" > "$out/good.log"
jq -e '.passed and .episodes==2 and .identicalActorInputs and .differentCaseFiles and .bothCoverageLabelsForwardStraight and .teacherLayoutMatchesCorpus and .teacherUsesPrivilegedGeometry and .teacherAssistedOnly and (.oracleLabelsForSameCases|length)==2' "$out/good/summary.json" > /dev/null
jq -nc '{step:0,source:"coverage",label:[0,-1]}' > "$pilot/runs/expert-1/teacher-search.jsonl"
if "$analysis" "$fixture/good/summary.json" "$pilot" "$out/bad" > "$out/bad.log" 2>&1; then echo 'Changed coverage teacher command accepted.' >&2; exit 1; fi
[[ "$(< "$out/bad/run.exit")" != 0 && ! -e "$out/bad/summary.json" ]]
echo 'Coverage conflict pilot audit joins exact inputs and rejects changed labels.'
