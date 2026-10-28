#!/usr/bin/env bash
# Synthetic preflight rejects reused cases or environments.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
mock="$out/mock";base="$mock/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1";corpus="$root/coverage-v2-student-admission-v1"
mkdir -p "$corpus/expanded" "$root/correction-v1" "$root/workspace/flex/sim/cases"
printf '0\n' > "$corpus/run.exit";printf '{"passed":true,"episodes":316,"newHistoriesIndependentlyAudited":true,"actorInputsUnchanged":true}\n' > "$corpus/coverage.json";printf 'template\n' > "$root/workspace/flex/sim/cases/find-return-house.json"
for ((index=0;index<316;index++));do
    mkdir -p "$corpus/expanded/expert-$index/scene"
    for file in case.json environment.bin;do printf 'corpus %s %s\n' "$index" "$file" > "$corpus/expanded/expert-$index/scene/$file";done
done
for layout in 18 19 20 21 22 23;do
    parent=generalization-benchmark-v1;if (( layout<20 ));then parent=unseen-benchmark-v2;fi
    for scene in {0..15};do mkdir -p "$base/$parent/scenes/$layout/$scene";for file in case.json environment.bin;do printf 'prior %s %s %s\n' "$layout" "$scene" "$file" > "$base/$parent/scenes/$layout/$scene/$file";done;done
done
cat > "$root/correction-v1/generate-diverse" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
out="$1"
for ((layout=180;layout<188;layout++));do
    scene="$out/$layout/4";mkdir -p "$scene"
    for file in case.json environment.bin;do printf 'new %s %s\n' "$layout" "$file" > "$scene/$file";done
    rooms='[[0,0,1,1]]';if (( layout%2 ));then rooms='[[0,0,1,1],[1,0,2,1]]';fi
    jq -n --argjson layout "$layout" --argjson rooms "$rooms" '{generator:"diverse-v1",layoutId:$layout,fit:false,rooms:$rooms,startPose:[$layout,0,0]}' > "$scene/layout.json"
done
if [[ "${PUPPYBOT_TEST_DUPLICATE:-0}" == 1 ]];then cp "$PUPPYBOT_PROJECT/build/flex/sim/expanded-rooms-v1/large-model-v1/coverage-v2-student-admission-v1/expanded/expert-0/scene/environment.bin" "$out/180/4/environment.bin";fi
EOF
chmod +x "$root/correction-v1/generate-diverse"
driver="$project/datasets/visual-control/expanded-rooms-v1/prepare-diverse-development.sh"
PUPPYBOT_PROJECT="$mock" PUPPYBOT_DIVERSE_GENERATOR="$root/correction-v1/generate-diverse" PUPPYBOT_DIVERSE_DEVELOPMENT_OUT="$out/good" bash "$driver" > "$out/good.log" 2>&1
jq -e '.passed and .developmentOnly and .episodes==8 and .openRooms==4 and .twoRoomLayouts==4 and .uniqueStartingPoses==8 and .exactCaseAndEnvironmentFilesDisjointFrom316HistoryCorpusAndExistingDevelopment' "$out/good/summary.json" > /dev/null
if PUPPYBOT_PROJECT="$mock" PUPPYBOT_DIVERSE_GENERATOR="$root/correction-v1/generate-diverse" PUPPYBOT_TEST_DUPLICATE=1 PUPPYBOT_DIVERSE_DEVELOPMENT_OUT="$out/bad" bash "$driver" > "$out/bad.log" 2>&1;then echo 'Duplicate environment was accepted.' >&2;exit 1;fi
[[ "$(< "$out/bad/run.exit")" != 0 && ! -e "$out/bad/summary.json" ]]
echo 'Diverse development preparation rejects previously used environments.'
