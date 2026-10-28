#!/usr/bin/env bash
# Synthetic catalog checks disjoint scenes, role splits and duplicate rejection.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-diverse-development.sh" "$out" > /dev/null
mock="$out/mock";root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1";old="$root/coverage-v2-student-admission-v1";other="$root/coverage-return-admission-v1"
printf 'old data\n' > "$old/expanded/data.bin";sha="$(sha256sum "$old/expanded/data.bin" | cut -d' ' -f1)";jq --arg sha "$sha" '.dataSHA256=$sha' "$old/coverage.json" > "$out/coverage.tmp";cp "$out/coverage.tmp" "$old/coverage.json"
mkdir -p "$other/expanded";printf '0\n' > "$other/run.exit";printf 'other data\n' > "$other/expanded/data.bin";sha="$(sha256sum "$other/expanded/data.bin" | cut -d' ' -f1)"
jq -n --arg sha "$sha" '{passed:true,episodes:310,dataSHA256:$sha,newHistoriesIndependentlyAudited:true,actorInputsUnchanged:true}' > "$other/coverage.json"
for ((i=0;i<310;i++));do ln -s "$old/expanded/expert-$i" "$other/expanded/expert-$i";done
ln -s "$out/good" "$root/diverse-development-v1"
cat > "$out/generator" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
output="$1";first="$2";end="$3";role="$4"
for ((layout=first;layout<end;layout++));do
    scene="$output/$layout/4";mkdir -p "$scene"
    for file in case.json environment.bin;do printf 'scale %s %s\n' "$layout" "$file" > "$scene/$file";done
    fit=false;if [[ "$role" == fit ]];then fit=true;fi;rooms='[[0,0,1,1]]';if (( layout%2 ));then rooms='[[0,0,1,1],[1,0,2,1]]';fi
    jq -n --argjson layout "$layout" --argjson fit "$fit" --argjson rooms "$rooms" '{generator:"diverse-v1",layoutId:$layout,fit:$fit,rooms:$rooms,startPose:[$layout,0,0]}' > "$scene/layout.json"
done
if [[ "${PUPPYBOT_TEST_DUPLICATE:-0}" == 1 && "$role" == fit ]];then cp "$PUPPYBOT_PROJECT/build/flex/sim/expanded-rooms-v1/large-model-v1/coverage-v2-student-admission-v1/expanded/expert-0/scene/case.json" "$output/70/4/case.json";fi
EOF
printf '#!/usr/bin/env bash\nexit 0\n' > "$out/validator";chmod +x "$out/generator" "$out/validator"
driver="$project/datasets/visual-control/expanded-rooms-v1/prepare-coverage-scale-catalog.sh"
export PUPPYBOT_PROJECT="$mock" PUPPYBOT_SCALE_GENERATOR="$out/generator" PUPPYBOT_SCALE_VALIDATOR="$out/validator"
PUPPYBOT_SCALE_CATALOG_OUT="$out/scale" bash "$driver" > "$out/scale.log" 2>&1
jq -e '.passed and .episodes==32 and .fittingLayouts==16 and .validationLayouts==16 and .openLayouts==16 and .twoRoomLayouts==16 and .uniqueStartingPoses==32 and .teacherEpisodesNotYetCollected' "$out/scale/summary.json" > /dev/null
if PUPPYBOT_TEST_DUPLICATE=1 PUPPYBOT_SCALE_CATALOG_OUT="$out/duplicate" bash "$driver" > "$out/duplicate.log" 2>&1;then echo 'Previously used scene was accepted.' >&2;exit 1;fi
[[ "$(< "$out/duplicate/run.exit")" != 0 && ! -e "$out/duplicate/summary.json" ]]
echo 'Scaled teacher catalog rejects reused scenes and checks role splits.'
