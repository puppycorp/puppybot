#!/usr/bin/env bash
# Synthetic smoke test checks pose and replay guard failures.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-diverse-development-benchmark.sh" "$out" > /dev/null
mock="$out/mock";root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1";wide="$root/wide-heading-development-v1";runtime="$root/phase-large-tests-v1/runtime"
cp -aL "$out/good" "$wide";printf '0\n' > "$wide/run.exit"
printf '{"passed":true,"developmentOnly":true,"episodes":8,"openRooms":4,"twoRoomLayouts":4,"uniqueStartingPoses":8,"wideHeading":true,"headingsBeyond90Degrees":4,"geometryChecked":true,"exactCaseAndEnvironmentFilesDisjointFromCorporaAndPriorDevelopment":true,"reservedFinalUntouched":true,"physicalSpawnNotYetChecked":true}\n' > "$wide/summary.json"
for ((i=0;i<8;i++));do jq --argjson i "$i" '.layoutId=(218+$i) | .wideHeading=true | .startPose[2]=(if ($i%2)==0 then 2 else -2 end)' "$wide/catalog/$i/layout.json" > "$out/wide-layout.tmp";cp "$out/wide-layout.tmp" "$wide/catalog/$i/layout.json";done
sha256sum "$wide/summary.json" "$wide"/catalog/{0..7}/{case.json,environment.bin,layout.json} > "$wide/inputs.sha256"
mkdir -p "$root/student-only-training-v1/policy" "$root/workspace/build/flex/control";cp "$out/policy/"* "$root/student-only-training-v1/policy/";cp "$runtime/build/flex/control/simulator" "$root/workspace/build/flex/control/simulator"
sha="$(sha256sum "$out/policy/weights.bin" | cut -d' ' -f1)";driver="$project/datasets/visual-control/expanded-rooms-v1/smoke-wide-heading-development.sh"
export PUPPYBOT_PROJECT="$mock" PUPPYBOT_TEST_POLICY_SHA="$sha" PUPPYBOT_WIDE_SMOKE_WAIT_RUN="$root/capacity/run"
PUPPYBOT_WIDE_SMOKE_OUT="$out/smoke" bash "$driver" > "$out/smoke.log" 2>&1
jq -e '.passed and .episodes==8 and .uniqueStartingPoses==8 and .physicalSpawnsChecked and .actionsReplayed==8 and .sceneAndInitialPosesMatched and .wholeEpisodePerformanceNotMeasured' "$out/smoke/summary.json" > /dev/null
for fault in PUPPYBOT_TEST_BAD_SCENE PUPPYBOT_TEST_BAD_POSE PUPPYBOT_TEST_BAD_AUDIT;do
    if env "$fault=1" PUPPYBOT_WIDE_SMOKE_OUT="$out/$fault-smoke" bash "$driver" > "$out/$fault-smoke.log" 2>&1;then echo "$fault was accepted." >&2;exit 1;fi
    [[ "$(< "$out/$fault-smoke/run.exit")" != 0 && ! -e "$out/$fault-smoke/summary.json" ]]
done
echo 'Wide-heading smoke check rejects scene, pose and replay failures.'
