#!/usr/bin/env bash
# Reserve 32 distinct non-development layouts for additional teacher data.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
base="$project/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1"
generator="${PUPPYBOT_SCALE_GENERATOR:?Frozen role-aware generator required}"
validator="${PUPPYBOT_SCALE_VALIDATOR:?Frozen geometry validator required}"
out="${PUPPYBOT_SCALE_CATALOG_OUT:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
for spec in coverage-v2-student-admission-v1:316 coverage-return-admission-v1:310;do
    corpus="$root/${spec%:*}";count="${spec#*:}";[[ "$(< "$corpus/run.exit")" == 0 ]]
    sha="$(sha256sum "$corpus/expanded/data.bin" | cut -d' ' -f1)"
    jq -e --arg sha "$sha" --argjson count "$count" '.passed and .episodes==$count and .dataSHA256==$sha and .newHistoriesIndependentlyAudited and .actorInputsUnchanged' "$corpus/coverage.json" > /dev/null
    sha256sum "$corpus/expanded/data.bin" "$corpus/coverage.json" >> "$out/inputs.sha256"
done
sha256sum "$generator" "$validator" "$root/workspace/flex/sim/cases/find-return-house.json" "$root/diverse-development-v1/summary.json" >> "$out/inputs.sha256"
cd "$root/workspace"
"$generator" "$out/fit" 70 86 fit > "$out/fit.log" 2>&1
"$generator" "$out/validation-a" 170 180 validation > "$out/validation-a.log" 2>&1
"$generator" "$out/validation-b" 188 194 validation > "$out/validation-b.log" 2>&1
"$validator" "$out/fit" 70 86 fit > "$out/fit-geometry.log" 2>&1
"$validator" "$out/validation-a" 170 180 validation > "$out/validation-a-geometry.log" 2>&1
"$validator" "$out/validation-b" 188 194 validation > "$out/validation-b-geometry.log" 2>&1
for spec in coverage-v2-student-admission-v1:316 coverage-return-admission-v1:310;do
    corpus="$root/${spec%:*}";count="${spec#*:}"
    for ((index=0;index<count;index++));do for file in case.json environment.bin;do sha256sum "$corpus/expanded/expert-$index/scene/$file" >> "$out/prior-inputs.sha256";done;done
done
for layout in 18 19 20 21 22 23;do
    parent=generalization-benchmark-v1;if (( layout<20 ));then parent=unseen-benchmark-v2;fi
    for scene in {0..15};do for file in case.json environment.bin;do sha256sum "$base/$parent/scenes/$layout/$scene/$file" >> "$out/prior-inputs.sha256";done;done
done
for ((index=0;index<8;index++));do for file in case.json environment.bin;do sha256sum "$root/diverse-development-v1/catalog/$index/$file" >> "$out/prior-inputs.sha256";done;done
cut -d' ' -f1 "$out/prior-inputs.sha256" > "$out/prior-hashes.txt"
mkdir "$out/catalog"
for ((index=0;index<32;index++));do
    fit=true;if (( index<16 ));then layout=$((70+index));scene="$out/fit/$layout/4";else
        fit=false;if (( index<26 ));then layout=$((170+index-16));scene="$out/validation-a/$layout/4";else layout=$((188+index-26));scene="$out/validation-b/$layout/4";fi
    fi
    rooms=1;if (( layout%2 ));then rooms=2;fi
    jq -e --argjson layout "$layout" --argjson fit "$fit" --argjson rooms "$rooms" '.generator=="diverse-v1" and .layoutId==$layout and .fit==$fit and (.rooms|length)==$rooms and (.startPose|length)==3' "$scene/layout.json" > /dev/null
    mkdir "$out/catalog/$index";for file in case.json environment.bin layout.json;do cp -L "$scene/$file" "$out/catalog/$index/$file";done
    for file in case.json environment.bin;do
        digest="$(sha256sum "$out/catalog/$index/$file" | cut -d' ' -f1)";status=0;rg -Fxq "$digest" "$out/prior-hashes.txt" || status=$?
        if (( status==0 ));then echo "Training scene $layout/$file duplicates existing data." >&2;exit 1;fi
        if (( status!=1 ));then echo 'Could not check prior hashes.' >&2;exit "$status";fi
        printf '%s\n' "$digest" >> "$out/prior-hashes.txt"
    done
    sha256sum "$out/catalog/$index/"{case.json,environment.bin,layout.json} >> "$out/inputs.sha256"
    jq -nc --argjson index "$index" --argjson layout "$layout" --argjson fit "$fit" --argjson rooms "$rooms" --slurpfile meta "$out/catalog/$index/layout.json" '{episode:$index,layoutId:$layout,fit:$fit,rooms:$rooms,startPose:$meta[0].startPose}' >> "$out/rows.jsonl"
done
sha256sum -c "$out/inputs.sha256" > "$out/integrity.log"
sha256sum -c "$out/prior-inputs.sha256" > "$out/prior-integrity.log"
jq -s '{passed:true,episodes:length,fittingLayouts:map(select(.fit))|length,validationLayouts:map(select(.fit|not))|length,openLayouts:map(select(.rooms==1))|length,twoRoomLayouts:map(select(.rooms==2))|length,uniqueStartingPoses:(map(.startPose)|unique|length),geometryChecked:true,exactCaseAndEnvironmentFilesDisjointFrom310And316CorporaAndDevelopment:true,similarGeometryStillPossible:true,reservedFinalUntouched:true,teacherEpisodesNotYetCollected:true,rows:.}' "$out/rows.jsonl" > "$out/summary.json"
jq -e '.passed and .episodes==32 and .fittingLayouts==16 and .validationLayouts==16 and .openLayouts==16 and .twoRoomLayouts==16 and .uniqueStartingPoses==32 and .reservedFinalUntouched and ([.rows[]|select(.fit and .rooms==1)]|length)==8 and ([.rows[]|select(.fit and .rooms==2)]|length)==8 and ([.rows[]|select((.fit|not) and .rooms==1)]|length)==8 and ([.rows[]|select((.fit|not) and .rooms==2)]|length)==8' "$out/summary.json" > /dev/null
echo 'Thirty-two distinct teacher-data layouts prepared and checked.'
