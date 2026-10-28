#!/usr/bin/env bash
# Reserve wide-heading rooms for teacher-search and student-return trips.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
base="$project/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1"
generator="${PUPPYBOT_WIDE_RETURN_GENERATOR:?Frozen generator required}"
validator="${PUPPYBOT_WIDE_RETURN_VALIDATOR:?Frozen geometry validator required}"
out="${PUPPYBOT_WIDE_RETURN_CATALOG_OUT:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
corpus="$root/return-reuse-admission-v1";[[ "$(< "$corpus/run.exit")" == 0 ]]
sha="$(sha256sum "$corpus/expanded/data.bin" | cut -d' ' -f1)"
jq -e --arg sha "$sha" '.passed and .episodes==350 and .dataSHA256==$sha and .newHistoriesIndependentlyAudited and .actorInputsUnchanged' "$corpus/coverage.json" > /dev/null
sha256sum "$generator" "$validator" "$root/workspace/flex/sim/cases/find-return-house.json" "$corpus/expanded/data.bin" "$corpus/coverage.json" > "$out/inputs.sha256"
for ((index=0;index<350;index++));do for file in case.json environment.bin;do sha256sum "$corpus/expanded/expert-$index/scene/$file" >> "$out/prior-inputs.sha256";done;done
for spec in diverse-development-v1:8 wide-heading-development-v1:8;do
    parent="$root/${spec%:*}";count="${spec#*:}";[[ "$(< "$parent/run.exit")" == 0 ]]
    jq -e '.passed and .developmentOnly and .episodes==8 and .reservedFinalUntouched' "$parent/summary.json" > /dev/null
    for ((index=0;index<count;index++));do for file in case.json environment.bin;do sha256sum "$parent/catalog/$index/$file" >> "$out/prior-inputs.sha256";done;done
done
parent="$root/wide-student-catalog-v2";[[ "$(< "$parent/run.exit")" == 0 ]]
for ((index=0;index<8;index++));do for file in case.json environment.bin;do sha256sum "$parent/catalog/$index/$file" >> "$out/prior-inputs.sha256";done;done
for layout in 18 19 20 21 22 23;do
    parent=generalization-benchmark-v1;if (( layout<20 ));then parent=unseen-benchmark-v2;fi
    for scene in {0..15};do for file in case.json environment.bin;do sha256sum "$base/$parent/scenes/$layout/$scene/$file" >> "$out/prior-inputs.sha256";done;done
done
cut -d' ' -f1 "$out/prior-inputs.sha256" > "$out/prior-hashes.txt"
cd "$root/workspace"
"$generator" "$out/fit" 92 94 fit --wide-heading > "$out/fit.log" 2>&1
"$generator" "$out/validation" 200 202 validation --wide-heading > "$out/validation.log" 2>&1
"$validator" "$out/fit" 92 94 fit --wide-heading > "$out/fit-geometry.log" 2>&1
"$validator" "$out/validation" 200 202 validation --wide-heading > "$out/validation-geometry.log" 2>&1
mkdir "$out/catalog"
layouts=(92 93 200 201)
for ((index=0;index<4;index++));do
    fit=true;role=fit;layout="${layouts[$index]}";if (( index>=2 ));then fit=false;role=validation;fi
    rooms=1;if (( layout%2 ));then rooms=2;fi;scene="$out/$role/$layout/4"
    jq -e --argjson layout "$layout" --argjson fit "$fit" --argjson rooms "$rooms" '.generator=="diverse-v1" and .layoutId==$layout and .fit==$fit and .wideHeading and (.rooms|length)==$rooms and (.startPose|length)==3' "$scene/layout.json" > /dev/null
    mkdir "$out/catalog/$index";for file in case.json environment.bin layout.json;do cp -L "$scene/$file" "$out/catalog/$index/$file";done
    for file in case.json environment.bin;do
        digest="$(sha256sum "$out/catalog/$index/$file" | cut -d' ' -f1)";status=0;rg -Fxq "$digest" "$out/prior-hashes.txt" || status=$?
        if (( status==0 ));then echo "Wide return scene $layout/$file duplicates existing data or development." >&2;exit 1;fi
        if (( status!=1 ));then echo 'Could not check prior hashes.' >&2;exit "$status";fi
        printf '%s\n' "$digest" >> "$out/prior-hashes.txt"
    done
    sha256sum "$out/catalog/$index/"{case.json,environment.bin,layout.json} >> "$out/inputs.sha256"
    jq -nc --argjson index "$index" --argjson layout "$layout" --argjson fit "$fit" --argjson rooms "$rooms" --slurpfile meta "$out/catalog/$index/layout.json" '{episode:$index,layoutId:$layout,fit:$fit,rooms:$rooms,startPose:$meta[0].startPose}' >> "$out/rows.jsonl"
done
sha256sum -c "$out/inputs.sha256" > "$out/integrity.log"
sha256sum -c "$out/prior-inputs.sha256" > "$out/prior-integrity.log"
jq -s '{passed:true,episodes:length,fittingLayouts:map(select(.fit))|length,validationLayouts:map(select(.fit|not))|length,openLayouts:map(select(.rooms==1))|length,twoRoomLayouts:map(select(.rooms==2))|length,uniqueStartingPoses:(map(.startPose)|unique|length),wideHeading:true,headingsBeyond90Degrees:(map(select(.startPose[2]>1.57079632679 or .startPose[2]< -1.57079632679))|length),geometryChecked:true,exactFilesDisjointFrom350CorpusAndOtherScenes:true,similarGeometryStillPossible:true,reservedFinalUntouched:true,physicalSpawnNotYetChecked:true,rows:.}' "$out/rows.jsonl" > "$out/summary.json"
jq -e '.passed and .episodes==4 and .fittingLayouts==2 and .validationLayouts==2 and .openLayouts==2 and .twoRoomLayouts==2 and .uniqueStartingPoses==4 and .wideHeading and .headingsBeyond90Degrees>=2 and ([.rows[]|select(.fit and (.startPose[2]>1.57079632679 or .startPose[2]< -1.57079632679))]|length)>=1 and ([.rows[]|select((.fit|not) and (.startPose[2]>1.57079632679 or .startPose[2]< -1.57079632679))]|length)>=1 and .geometryChecked and .physicalSpawnNotYetChecked and .reservedFinalUntouched' "$out/summary.json" > /dev/null
echo 'Wide-heading teacher-search/student-return rooms prepared; physical spawns remain unchecked.'
