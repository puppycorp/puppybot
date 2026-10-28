#!/usr/bin/env bash
# Reserve eight new development rooms with distinct robot starting poses.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
base="$project/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1"
corpus="$root/coverage-v2-student-admission-v1";generator="${PUPPYBOT_DIVERSE_GENERATOR:-$project/build/flex/control/diverse-generator}";workspace="$root/workspace"
out="${PUPPYBOT_DIVERSE_DEVELOPMENT_OUT:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
[[ "$(< "$corpus/run.exit")" == 0 ]]
jq -e '.passed and .episodes==316 and .newHistoriesIndependentlyAudited and .actorInputsUnchanged' "$corpus/coverage.json" > /dev/null
sha256sum "$generator" "$workspace/flex/sim/cases/find-return-house.json" "$corpus/coverage.json" > "$out/inputs.sha256"
cd "$workspace"
"$generator" "$out/generated" 180 188 development > "$out/generate.log" 2>&1
mkdir "$out/catalog"
for ((index=0;index<316;index++));do
    for file in case.json environment.bin;do sha256sum "$corpus/expanded/expert-$index/scene/$file" >> "$out/prior-inputs.sha256";done
done
for layout in 18 19 20 21 22 23;do
    parent=generalization-benchmark-v1;if (( layout<20 ));then parent=unseen-benchmark-v2;fi
    for scene in {0..15};do for file in case.json environment.bin;do sha256sum "$base/$parent/scenes/$layout/$scene/$file" >> "$out/prior-inputs.sha256";done;done
done
cut -d' ' -f1 "$out/prior-inputs.sha256" > "$out/prior-hashes.txt"
for ((index=0;index<8;index++));do
    layout=$((180+index));scene="$out/generated/$layout/4";rooms=1;if (( layout%2 ));then rooms=2;fi
    jq -e --argjson layout "$layout" --argjson rooms "$rooms" '.generator=="diverse-v1" and .layoutId==$layout and (.fit|not) and (.rooms|length)==$rooms and (.startPose|length)==3 and all(.startPose[];type=="number")' "$scene/layout.json" > /dev/null
    mkdir "$out/catalog/$index"
    for file in case.json environment.bin layout.json;do cp -L "$scene/$file" "$out/catalog/$index/$file";done
    for file in case.json environment.bin;do
        digest="$(sha256sum "$out/catalog/$index/$file" | cut -d' ' -f1)";status=0;rg -Fxq "$digest" "$out/prior-hashes.txt" || status=$?
        if (( status==0 ));then echo "Development scene duplicates an existing file: $layout/$file" >&2;exit 1;fi
        if (( status!=1 ));then echo 'Could not check prior hashes.' >&2;exit "$status";fi
        printf '%s\n' "$digest" >> "$out/prior-hashes.txt"
    done
    sha256sum "$out/catalog/$index/"{case.json,environment.bin,layout.json} >> "$out/inputs.sha256"
    jq -nc --argjson index "$index" --argjson layout "$layout" --argjson rooms "$rooms" --slurpfile metadata "$out/catalog/$index/layout.json" '{caseIndex:$index,layoutId:$layout,rooms:$rooms,startPose:$metadata[0].startPose}' >> "$out/rows.jsonl"
done
sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
sha256sum -c "$out/prior-inputs.sha256" > "$out/prior-integrity-after.log"
jq -s '{passed:true,developmentOnly:true,episodes:8,openRooms:map(select(.rooms==1))|length,twoRoomLayouts:map(select(.rooms==2))|length,uniqueStartingPoses:(map(.startPose)|unique|length),exactCaseAndEnvironmentFilesDisjointFrom316HistoryCorpusAndExistingDevelopment:true,similarGeometryStillPossible:true,reservedFinalUntouched:true,rows:.}' "$out/rows.jsonl" > "$out/summary.json"
jq -e '.passed and .episodes==8 and .openRooms==4 and .twoRoomLayouts==4 and .uniqueStartingPoses==8 and .reservedFinalUntouched' "$out/summary.json" > /dev/null
echo 'Eight new development rooms and distinct starting poses prepared.'
