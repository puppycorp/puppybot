#!/usr/bin/env bash
# Check wide-heading development scenes reject existing training files.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-coverage-scale-catalog.sh" "$out" > /dev/null
mock="$out/mock";root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1";ln -s "$out/scale" "$root/coverage-scale-catalog-v1"
cat > "$out/wide-generator" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "$2" == 218 && "$3" == 226 && "$4" == wide-development && "$5" == --wide-heading ]]
for ((layout=218;layout<226;layout++));do
    scene="$1/$layout/4";mkdir -p "$scene"
    for file in case.json environment.bin;do printf 'wide %s %s\n' "$layout" "$file" > "$scene/$file";done
    rooms='[[0,0,1,1]]';if (( layout%2 ));then rooms='[[0,0,1,1],[1,0,2,1]]';fi
    jq -n --argjson layout "$layout" --argjson rooms "$rooms" '{generator:"diverse-v1",layoutId:$layout,fit:false,wideHeading:true,rooms:$rooms,startPose:[$layout,0,(if ($layout%2)==0 then 2 else -2 end)]}' > "$scene/layout.json"
done
if [[ "${PUPPYBOT_TEST_DUPLICATE:-0}" == 1 ]];then cp "$PUPPYBOT_PROJECT/build/flex/sim/expanded-rooms-v1/large-model-v1/coverage-v2-student-admission-v1/expanded/expert-0/scene/case.json" "$1/218/4/case.json";fi
EOF
chmod +x "$out/wide-generator"
driver="$project/datasets/visual-control/expanded-rooms-v1/prepare-wide-heading-development.sh"
export PUPPYBOT_PROJECT="$mock" PUPPYBOT_WIDE_GENERATOR="$out/wide-generator" PUPPYBOT_WIDE_VALIDATOR="$out/validator"
PUPPYBOT_WIDE_DEVELOPMENT_OUT="$out/wide" bash "$driver" > "$out/wide.log" 2>&1
jq -e '.passed and .developmentOnly and .episodes==8 and .openRooms==4 and .twoRoomLayouts==4 and .uniqueStartingPoses==8 and .wideHeading and .headingsBeyond90Degrees==8 and .physicalSpawnNotYetChecked' "$out/wide/summary.json" > /dev/null
if PUPPYBOT_TEST_DUPLICATE=1 PUPPYBOT_WIDE_DEVELOPMENT_OUT="$out/duplicate-wide" bash "$driver" > "$out/duplicate-wide.log" 2>&1;then echo 'Existing case was accepted.' >&2;exit 1;fi
[[ "$(< "$out/duplicate-wide/run.exit")" != 0 && ! -e "$out/duplicate-wide/summary.json" ]]
echo 'Wide-heading development catalog rejects existing cases.'
