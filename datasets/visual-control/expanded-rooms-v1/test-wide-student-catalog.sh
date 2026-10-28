#!/usr/bin/env bash
# Wide student rooms must be disjoint from the admitted corpus and development.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-wide-heading-development.sh" "$out" > /dev/null
mock="$out/mock";root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1";old="$root/coverage-v2-student-admission-v1";corpus="$root/coverage-scale-admission-v1"
ln -s "$out/wide" "$root/wide-heading-development-v1"
mkdir -p "$corpus/expanded";printf '0\n' > "$corpus/run.exit";printf 'wide student corpus\n' > "$corpus/expanded/data.bin"
sha="$(sha256sum "$corpus/expanded/data.bin" | cut -d' ' -f1)"
jq -n --arg sha "$sha" '{passed:true,episodes:348,dataSHA256:$sha,newHistoriesIndependentlyAudited:true,actorInputsUnchanged:true}' > "$corpus/coverage.json"
for ((i=0;i<348;i++));do ln -s "$old/expanded/expert-$((i%316))" "$corpus/expanded/expert-$i";done
cat > "$out/student-generator" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
output="$1";first="$2";end="$3";role="$4";[[ "$5" == --wide-heading ]]
for ((layout=first;layout<end;layout++));do
    scene="$output/$layout/4";mkdir -p "$scene"
    for file in case.json environment.bin;do printf 'wide student %s %s\n' "$layout" "$file" > "$scene/$file";done
    fit=false;if [[ "$role" == fit ]];then fit=true;fi;rooms='[[0,0,1,1]]';if (( layout%2 ));then rooms='[[0,0,1,1],[1,0,2,1]]';fi
    jq -n --argjson layout "$layout" --argjson fit "$fit" --argjson rooms "$rooms" '{generator:"diverse-v1",layoutId:$layout,fit:$fit,wideHeading:true,rooms:$rooms,startPose:[$layout,0,(if ($layout%2)==0 then 2 else -2 end)]}' > "$scene/layout.json"
done
if [[ "${PUPPYBOT_TEST_DUPLICATE:-0}" == 1 && "$role" == fit ]];then cp "$PUPPYBOT_PROJECT/build/flex/sim/expanded-rooms-v1/large-model-v1/coverage-scale-admission-v1/expanded/expert-0/scene/case.json" "$output/86/4/case.json";fi
EOF
chmod +x "$out/student-generator"
driver="$project/datasets/visual-control/expanded-rooms-v1/prepare-wide-student-catalog.sh"
export PUPPYBOT_PROJECT="$mock" PUPPYBOT_WIDE_STUDENT_GENERATOR="$out/student-generator" PUPPYBOT_WIDE_STUDENT_VALIDATOR="$out/validator"
PUPPYBOT_WIDE_STUDENT_CATALOG_OUT="$out/student" bash "$driver" > "$out/student.log" 2>&1
jq -e '.passed and .episodes==8 and .fittingLayouts==4 and .validationLayouts==4 and .openLayouts==4 and .twoRoomLayouts==4 and .wideHeading and .headingsBeyond90Degrees==8 and .physicalSpawnNotYetChecked' "$out/student/summary.json" > /dev/null
if PUPPYBOT_TEST_DUPLICATE=1 PUPPYBOT_WIDE_STUDENT_CATALOG_OUT="$out/duplicate-student" bash "$driver" > "$out/duplicate-student.log" 2>&1;then echo 'Reused training scene was accepted.' >&2;exit 1;fi
[[ "$(< "$out/duplicate-student/run.exit")" != 0 && ! -e "$out/duplicate-student/summary.json" ]]
echo 'Wide student catalog rejects reused scenes and checks both data splits.'
