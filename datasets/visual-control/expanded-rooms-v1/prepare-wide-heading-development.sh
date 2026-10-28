#!/usr/bin/env bash
# Reserve eight further development rooms with full-range starting headings.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
base="$project/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1"
generator="${PUPPYBOT_WIDE_GENERATOR:?Frozen wide-heading generator required}"
validator="${PUPPYBOT_WIDE_VALIDATOR:?Frozen wide-heading validator required}"
out="${PUPPYBOT_WIDE_DEVELOPMENT_OUT:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
sha256sum "$generator" "$validator" "$root/workspace/flex/sim/cases/find-return-house.json" "$root/diverse-development-v1/summary.json" "$root/coverage-scale-catalog-v1/summary.json" > "$out/inputs.sha256"
for spec in coverage-v2-student-admission-v1:316 coverage-return-admission-v1:310;do
    corpus="$root/${spec%:*}";count="${spec#*:}";[[ "$(< "$corpus/run.exit")" == 0 ]]
    sha="$(sha256sum "$corpus/expanded/data.bin" | cut -d' ' -f1)"
    jq -e --arg sha "$sha" --argjson count "$count" '.passed and .episodes==$count and .dataSHA256==$sha and .newHistoriesIndependentlyAudited and .actorInputsUnchanged' "$corpus/coverage.json" > /dev/null
    sha256sum "$corpus/expanded/data.bin" "$corpus/coverage.json" >> "$out/inputs.sha256"
    for ((index=0;index<count;index++));do for file in case.json environment.bin;do sha256sum "$corpus/expanded/expert-$index/scene/$file" >> "$out/prior-inputs.sha256";done;done
done
for layout in 18 19 20 21 22 23;do
    parent=generalization-benchmark-v1;if (( layout<20 ));then parent=unseen-benchmark-v2;fi
    for scene in {0..15};do for file in case.json environment.bin;do sha256sum "$base/$parent/scenes/$layout/$scene/$file" >> "$out/prior-inputs.sha256";done;done
done
for spec in diverse-development-v1:8 coverage-scale-catalog-v1:32;do parent="$root/${spec%:*}";count="${spec#*:}";[[ "$(< "$parent/run.exit")" == 0 ]];for ((index=0;index<count;index++));do for file in case.json environment.bin;do sha256sum "$parent/catalog/$index/$file" >> "$out/prior-inputs.sha256";done;done;done
cut -d' ' -f1 "$out/prior-inputs.sha256" > "$out/prior-hashes.txt"
cd "$root/workspace"
"$generator" "$out/generated" 218 226 wide-development --wide-heading > "$out/generate.log" 2>&1
"$validator" "$out/generated" 218 226 validation --wide-heading > "$out/geometry.log" 2>&1
mkdir "$out/catalog"
for ((index=0;index<8;index++));do
    layout=$((218+index));scene="$out/generated/$layout/4";rooms=1;if (( layout%2 ));then rooms=2;fi
    jq -e --argjson layout "$layout" --argjson rooms "$rooms" '.generator=="diverse-v1" and .layoutId==$layout and (.fit|not) and .wideHeading==true and (.rooms|length)==$rooms and (.startPose|length)==3' "$scene/layout.json" > /dev/null
    mkdir "$out/catalog/$index";for file in case.json environment.bin layout.json;do cp -L "$scene/$file" "$out/catalog/$index/$file";done
    for file in case.json environment.bin;do
        digest="$(sha256sum "$out/catalog/$index/$file" | cut -d' ' -f1)";status=0;rg -Fxq "$digest" "$out/prior-hashes.txt" || status=$?
        if (( status==0 ));then echo "Wide-heading scene $layout/$file duplicates existing data." >&2;exit 1;fi
        if (( status!=1 ));then echo 'Could not check prior hashes.' >&2;exit "$status";fi
        printf '%s\n' "$digest" >> "$out/prior-hashes.txt"
    done
    sha256sum "$out/catalog/$index/"{case.json,environment.bin,layout.json} >> "$out/inputs.sha256"
    jq -nc --argjson index "$index" --argjson layout "$layout" --argjson rooms "$rooms" --slurpfile meta "$out/catalog/$index/layout.json" '{caseIndex:$index,layoutId:$layout,rooms:$rooms,startPose:$meta[0].startPose}' >> "$out/rows.jsonl"
done
sha256sum -c "$out/inputs.sha256" > "$out/integrity.log"
sha256sum -c "$out/prior-inputs.sha256" > "$out/prior-integrity.log"
jq -s '{passed:true,developmentOnly:true,episodes:length,openRooms:map(select(.rooms==1))|length,twoRoomLayouts:map(select(.rooms==2))|length,uniqueStartingPoses:(map(.startPose)|unique|length),wideHeading:true,headingsBeyond90Degrees:(map(select((.startPose[2]>1.57079632679) or (.startPose[2]< -1.57079632679)))|length),geometryChecked:true,exactCaseAndEnvironmentFilesDisjointFromCorporaAndPriorDevelopment:true,similarGeometryStillPossible:true,reservedFinalUntouched:true,physicalSpawnNotYetChecked:true,rows:.}' "$out/rows.jsonl" > "$out/summary.json"
jq -e '.passed and .episodes==8 and .openRooms==4 and .twoRoomLayouts==4 and .uniqueStartingPoses==8 and .headingsBeyond90Degrees>=2 and .physicalSpawnNotYetChecked and .reservedFinalUntouched' "$out/summary.json" > /dev/null
echo 'Wide-heading development rooms prepared; physical spawn checks remain required.'
