#!/usr/bin/env bash
# The independent goal audit must reject changed inputs, goals and labels.
set -euo pipefail
project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
out="$(realpath -m "${1:?New output directory required}")"
mkdir "$out"
scene="$out/source-scene";episode="$out/episode"
mkdir -p "$scene" "$episode/scene"
printf 'case\n' > "$scene/case.json";printf 'environment\n' > "$scene/environment.bin"
cp "$scene/case.json" "$episode/scene/case.json";cp "$scene/environment.bin" "$episode/scene/environment.bin"
printf '{"rooms":[[0,0,8,8]],"startRoom":0}\n' > "$scene/layout.json"
jq -n --arg scene "$scene" '{searchTeacher:"coverage-camera-v1",teacherUsesRoomBounds:true,searchGoalsUseUnseenBrickPosition:false,teacherPlannerUsesPrivilegedGeometry:true,sourceScene:$scene}' > "$episode/supervision.json"
printf '%s\n' '{"totalSteps":1,"pose":[4,4,0],"findReturn":{"consumedIndex":-1},"localization":{"pose":[0,0,0]},"case":{"perception":{"frameId":1,"detections":[{"targetM":[1,0,0]}]},"objects":[{"position":[100,100,0]}]}}' > "$episode/initial.json"
printf '%s\n' '{"step":0,"source":"camera","coverageIndex":3,"goal":[4.76,4,0],"label":[0.6,1]}' > "$episode/teacher-search.jsonl"
printf '%s\n' '{"state":{"totalSteps":11,"trainingOracle":{"label":[0.6,1]}}}' > "$episode/decisions.jsonl"
driver="$project/datasets/visual-control/expanded-rooms-v1/audit-coverage-teacher.sh"
bash "$driver" "$episode" "$out/good"
jq -e '.passed and .steps==1 and .cameraGoals==1 and .coverageGoals==0 and (.independentTeacherExecutionReplay|not)' "$out/good/result.json" > /dev/null
jq '.case.objects[0].position=[-50,23,0]' "$episode/initial.json" > "$out/other-prop.json"
mv "$out/other-prop.json" "$episode/initial.json"
bash "$driver" "$episode" "$out/other-prop"
cp "$episode/teacher-search.jsonl" "$out/original-trace.jsonl"
jq '.goal[0]+=0.1' "$out/original-trace.jsonl" > "$episode/teacher-search.jsonl"
if bash "$driver" "$episode" "$out/bad-goal" > "$out/bad-goal.log" 2>&1;then echo 'Altered camera goal was accepted.' >&2;exit 1;fi
cp "$out/original-trace.jsonl" "$episode/teacher-search.jsonl"
jq '.label[1] = -1' "$out/original-trace.jsonl" > "$episode/teacher-search.jsonl"
if bash "$driver" "$episode" "$out/bad-label" > "$out/bad-label.log" 2>&1;then echo 'Altered oracle label was accepted.' >&2;exit 1;fi
cp "$out/original-trace.jsonl" "$episode/teacher-search.jsonl"
jq '.case.perception.detections[0].targetM[0]=1.5' "$episode/initial.json" > "$out/changed-initial.json"
mv "$out/changed-initial.json" "$episode/initial.json"
if bash "$driver" "$episode" "$out/bad-camera" > "$out/bad-camera.log" 2>&1;then echo 'Altered camera detection was accepted.' >&2;exit 1;fi
jq '.case.perception.detections[0].targetM[0]=1 | .case.perception.frameId=0' "$episode/initial.json" > "$out/stale-initial.json"
mv "$out/stale-initial.json" "$episode/initial.json"
if bash "$driver" "$episode" "$out/stale" > "$out/stale.log" 2>&1;then echo 'Stale camera detection was accepted.' >&2;exit 1;fi
echo 'Coverage teacher audit reconstructs camera goals and rejects altered or stale inputs.'
