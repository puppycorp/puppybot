#!/usr/bin/env bash
# A policy from an additional corpus requires a matching disjointness audit.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-diverse-development-benchmark.sh" "$out" > /dev/null
mock="$out/mock";root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1";source="$root/coverage-v2-student-admission-v1";corpus="$out/additional"
mkdir -p "$corpus/expanded"
for ((i=0;i<316;i++));do ln -s "$source/expanded/expert-$i" "$corpus/expanded/expert-$i";done
printf 'additional corpus\n' > "$corpus/expanded/data.bin";printf '0\n' > "$corpus/run.exit"
data_sha="$(sha256sum "$corpus/expanded/data.bin" | cut -d' ' -f1)"
jq -n --arg sha "$data_sha" '{passed:true,episodes:316,dataSHA256:$sha,newHistoriesIndependentlyAudited:true,actorInputsUnchanged:true}' > "$corpus/coverage.json"
bash "$project/datasets/visual-control/expanded-rooms-v1/audit-diverse-corpus.sh" "$root/diverse-development-v1" "$corpus" "$out/corpus-audit" > "$out/corpus-audit.log" 2>&1
jq --arg sha "$data_sha" '.dataSHA256=$sha' "$out/policy/receipt.json" > "$out/receipt.tmp";cp "$out/receipt.tmp" "$out/policy/receipt.json"
driver="$project/datasets/visual-control/expanded-rooms-v1/benchmark-diverse-development.sh"
policy_sha="$(sha256sum "$out/policy/weights.bin" | cut -d' ' -f1)"
export PUPPYBOT_PROJECT="$mock" PUPPYBOT_TEST_POLICY_SHA="$policy_sha" PUPPYBOT_DIVERSE_POLICY="$out/policy" PUPPYBOT_DIVERSE_WAIT_RUN="$root/capacity/run"
PUPPYBOT_DIVERSE_CORPUS_AUDIT="$out/corpus-audit" PUPPYBOT_DIVERSE_BENCHMARK_OUT="$out/additional-benchmark" bash "$driver" > "$out/additional-benchmark.log" 2>&1
jq -e '.passed and .episodes==8 and .auditedEpisodes==8 and .uniqueStartingPoses==8' "$out/additional-benchmark/score.json" > /dev/null
if PUPPYBOT_DIVERSE_BENCHMARK_OUT="$out/no-audit" bash "$driver" > "$out/no-audit.log" 2>&1;then echo 'Unaudited corpus was accepted.' >&2;exit 1;fi
[[ "$(< "$out/no-audit/run.exit")" != 0 && ! -e "$out/no-audit/score.json" ]]
echo 'Diverse benchmark requires a matching audit for additional corpora.'
