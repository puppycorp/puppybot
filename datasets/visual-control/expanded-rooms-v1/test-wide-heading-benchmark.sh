#!/usr/bin/env bash
# Wide benchmark must require verified spawns and reject altered smoke results.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-wide-heading-smoke.sh" "$out" > /dev/null
mock="$out/mock";root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1"
ln -s "$out/smoke" "$root/wide-heading-smoke-v1"
sha="$(sha256sum "$out/policy/weights.bin" | cut -d' ' -f1)"
driver="$project/datasets/visual-control/expanded-rooms-v1/benchmark-diverse-development.sh"
export PUPPYBOT_PROJECT="$mock" PUPPYBOT_TEST_POLICY_SHA="$sha" PUPPYBOT_DIVERSE_POLICY="$out/policy" PUPPYBOT_DIVERSE_WAIT_RUN="$root/capacity/run" PUPPYBOT_DIVERSE_SCENE_SET=wide-heading
PUPPYBOT_DIVERSE_BENCHMARK_OUT="$out/benchmark-wide" bash "$driver" > "$out/benchmark-wide.log" 2>&1
jq -e '.passed and .developmentOnly and .sceneSet=="wide-heading" and .episodes==8 and .auditedEpisodes==8 and .uniqueStartingPoses==8 and (.automaticPromotion|not)' "$out/benchmark-wide/score.json" > /dev/null
jq '.passed=false' "$out/smoke/0/verified/result.json" > "$out/bad-result.json";cp "$out/bad-result.json" "$out/smoke/0/verified/result.json"
if PUPPYBOT_DIVERSE_BENCHMARK_OUT="$out/bad-smoke" bash "$driver" > "$out/bad-smoke.log" 2>&1;then echo 'Failed spawn replay was accepted.' >&2;exit 1;fi
[[ "$(< "$out/bad-smoke/run.exit")" != 0 && ! -e "$out/bad-smoke/score.json" ]]
echo 'Wide-heading benchmark requires successful individual spawn replays.'
