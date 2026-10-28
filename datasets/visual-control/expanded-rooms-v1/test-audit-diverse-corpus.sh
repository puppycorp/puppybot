#!/usr/bin/env bash
# Reject an exact scene overlap with an additional audited corpus.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-diverse-development.sh" "$out" > /dev/null
corpus="$out/mock/build/flex/sim/expanded-rooms-v1/large-model-v1/coverage-v2-student-admission-v1";scenes="$out/good"
printf 'dataset\n' > "$corpus/expanded/data.bin";sha="$(sha256sum "$corpus/expanded/data.bin" | cut -d' ' -f1)"
jq --arg sha "$sha" '.dataSHA256=$sha' "$corpus/coverage.json" > "$out/coverage.tmp";cp "$out/coverage.tmp" "$corpus/coverage.json"
driver="$project/datasets/visual-control/expanded-rooms-v1/audit-diverse-corpus.sh"
bash "$driver" "$scenes" "$corpus" "$out/audit" > "$out/audit.log" 2>&1
jq -e --arg sha "$sha" '.passed and .dataSHA256==$sha and .corpusHistories==316 and .episodes==8 and .exactCaseAndEnvironmentFilesDisjoint and .similarGeometryStillPossible' "$out/audit/summary.json" > /dev/null
cp "$scenes/catalog/0/case.json" "$corpus/expanded/expert-0/scene/case.json"
if bash "$driver" "$scenes" "$corpus" "$out/duplicate" > "$out/duplicate.log" 2>&1;then echo 'Overlapping case was accepted.' >&2;exit 1;fi
[[ ! -e "$out/duplicate/summary.json" ]]
echo 'Diverse corpus audit rejects an exact case overlap.'
