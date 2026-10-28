#!/usr/bin/env bash
# Exercise matched-scene dispatch and reject a changed simulator observation.
set -euo pipefail
out="$(realpath -m "${1:?New output directory required}")"
[[ ! -e "$out" ]]; mkdir "$out"
project="$(cd "$(dirname "$0")/../.." && pwd)"
bash "$project/flex/scripts/test-coverage-conflict-pilot.sh" "$out/fixture" > "$out/fixture.log"
scene_audit="$out/fixture/scene-fixture/good/summary.json"
input="$(jq -r '.groups[0].rows[0].inputSHA256' "$scene_audit")"
mkdir -p "$out/runtime/build/flex/control" "$out/runtime/build/flex/sim"
printf '#!/bin/sh\nexit 0\n' > "$out/runtime/build/flex/control/simulator"
chmod +x "$out/runtime/build/flex/control/simulator"
printf 'test-model\n' > "$out/runtime/build/flex/sim/puppybot.bin"
cat > "$out/query" <<'QUERY'
#!/usr/bin/env bash
set -euo pipefail
mkdir "$3"
hash="$TEST_INPUT_SHA"; if [[ "${TEST_BAD_INPUT:-0}" == 1 ]]; then hash=bad; fi
jq -n --arg hash "$hash" '{actorInputSHA256:$hash,actorInputsUnchanged:true,teacherLabelOnly:true,teacherUsesPrivilegedGeometry:true,autonomousSuccessClaimed:false,source:"coverage",actionClass:1,action:[0,1],coverageIndex:2,goal:[1,0,0],initialPose:[0,0,0]}' > "$3/result.json"
QUERY
chmod +x "$out/query"
analysis="$project/datasets/visual-control/expanded-rooms-v1/check-coverage-initial-group.sh"
TEST_INPUT_SHA="$input" "$analysis" "$scene_audit" 0 "$out/query" "$out/runtime" "$out/good" > "$out/good.log"
jq -e '.passed and .episodes==2 and .sameCoverageLabel and .matchingOriginalLabels==1 and .actorInputsMatched and .originalSceneAndLayoutUsed and .teacherUsesPrivilegedGeometry and (.autonomousSuccessClaimed|not) and .originalActionCounts==[{actionClass:0,count:1},{actionClass:1,count:1}] and .coverageActionCounts==[{actionClass:1,count:2}]' "$out/good/summary.json" > /dev/null
if TEST_INPUT_SHA="$input" TEST_BAD_INPUT=1 "$analysis" "$scene_audit" 0 "$out/query" "$out/runtime" "$out/bad" > "$out/bad.log" 2>&1; then echo 'Changed simulator observation accepted.' >&2; exit 1; fi
[[ "$(< "$out/bad/run.exit")" != 0 && ! -e "$out/bad/summary.json" ]]
echo 'Coverage initial group dispatch checks scene provenance and rejects changed observations.'
