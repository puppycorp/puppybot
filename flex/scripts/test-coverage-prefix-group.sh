#!/usr/bin/env bash
# Check group provenance and reject an incorrect packed-data result.
set -euo pipefail
out="$(realpath -m "${1:?New output directory required}")"
[[ ! -e "$out" ]]; mkdir "$out"
project="$(cd "$(dirname "$0")/../.." && pwd)"
bash "$project/flex/scripts/test-coverage-conflict-pilot.sh" "$out/fixture" > "$out/fixture.log"
corpus="$out/fixture/scene-fixture/corpus"
printf 'synthetic packed data\n' > "$corpus/data.bin"
sha="$(sha256sum "$corpus/data.bin" | cut -d' ' -f1)"
for index in 0 1; do
    run="$corpus/expert-$index"
    jq -nc '{step:17},{step:27},{step:37}' > "$run/decisions.jsonl"
    for step in 17 27 37; do cp "$run/actor-7.rgb" "$run/actor-$step.rgb"; cp "$run/actor-7.feedback" "$run/actor-$step.feedback"; done
done
jq -n --arg sha "$sha" '{passed:true,driveFeedbackNeutralized:true,initialMemoryZero:true,prefixBytesIndependentlyCompared:true,dataSHA256:$sha,conflicts:[{prefixId:4,time:3,examples:[{episode:0,time:3,actionClass:0},{episode:1,time:3,actionClass:1}]}]}' > "$out/audit.json"
mkdir -p "$out/runtime/build/flex/control" "$out/runtime/build/flex/sim"
printf '#!/bin/sh\nexit 0\n' > "$out/runtime/build/flex/control/simulator"; chmod +x "$out/runtime/build/flex/control/simulator"
printf 'test-model\n' > "$out/runtime/build/flex/sim/puppybot.bin"
cat > "$out/query" <<'QUERY'
#!/usr/bin/env bash
set -euo pipefail
mkdir "$7"
class="$5"; if [[ "${TEST_WRONG_CLASS:-0}" == 1 ]]; then class=6; fi
jq -n --argjson time "$6" --argjson original "$class" '{decision:$time,replayedCommands:$time,observationFramesMatched:($time+1),corpusActionClass:$original,actorInputsUnchanged:true,recordedActionsReplayed:true,teacherLabelOnly:true,teacherUsesPrivilegedGeometry:true,autonomousSuccessClaimed:false,source:"coverage",actionClass:1,action:[0,1],goal:[1,0,0],actorRGBSHA256:"test"}' > "$7/result.json"
QUERY
chmod +x "$out/query"
analysis="$project/datasets/visual-control/expanded-rooms-v1/check-coverage-prefix-group.sh"
"$analysis" "$out/audit.json" 4 "$out/query" "$out/runtime" "$corpus" "$out/good" > "$out/good.log"
jq -e '.passed and .prefixId==4 and .episodes==2 and .sameCoverageLabel and .matchingOriginalLabels==1 and .recordedActionsAndObservationsReplayed and .originalSceneAndLayoutUsed and .teacherLabelsOnly and (.autonomousSuccessClaimed|not)' "$out/good/summary.json" > /dev/null
if TEST_WRONG_CLASS=1 "$analysis" "$out/audit.json" 4 "$out/query" "$out/runtime" "$corpus" "$out/bad" > "$out/bad.log" 2>&1; then echo 'Incorrect packed label accepted.' >&2; exit 1; fi
[[ "$(< "$out/bad/run.exit")" != 0 && ! -e "$out/bad/summary.json" ]]
echo 'Coverage prefix group binds scene, recording and packed labels and rejects mismatches.'
