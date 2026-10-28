#!/usr/bin/env bash
# Return curriculum rooms must be disjoint from all training and development.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-wide-student-catalog.sh" "$out" > /dev/null
mock="$out/mock";root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1";old="$root/coverage-scale-admission-v1";corpus="$root/return-reuse-admission-v1"
ln -s "$out/student" "$root/wide-student-catalog-v2"
mkdir -p "$corpus/expanded";printf '0\n' > "$corpus/run.exit";printf 'return corpus\n' > "$corpus/expanded/data.bin"
sha="$(sha256sum "$corpus/expanded/data.bin" | cut -d' ' -f1)"
jq -n --arg sha "$sha" '{passed:true,episodes:350,dataSHA256:$sha,newHistoriesIndependentlyAudited:true,actorInputsUnchanged:true}' > "$corpus/coverage.json"
for ((i=0;i<350;i++));do ln -s "$old/expanded/expert-$((i%348))" "$corpus/expanded/expert-$i";done
sed 's@\$output/86/4/case.json@\$output/92/4/case.json@' "$out/student-generator" > "$out/return-generator";chmod +x "$out/return-generator"
driver="$project/datasets/visual-control/expanded-rooms-v1/prepare-wide-return-catalog.sh"
export PUPPYBOT_PROJECT="$mock" PUPPYBOT_WIDE_RETURN_GENERATOR="$out/return-generator" PUPPYBOT_WIDE_RETURN_VALIDATOR="$out/validator"
PUPPYBOT_WIDE_RETURN_CATALOG_OUT="$out/return" bash "$driver" > "$out/return.log" 2>&1
jq -e '.passed and .episodes==4 and .fittingLayouts==2 and .validationLayouts==2 and .openLayouts==2 and .twoRoomLayouts==2 and .wideHeading and .headingsBeyond90Degrees==4 and .physicalSpawnNotYetChecked' "$out/return/summary.json" > /dev/null
if PUPPYBOT_TEST_DUPLICATE=1 PUPPYBOT_WIDE_RETURN_CATALOG_OUT="$out/duplicate-return" bash "$driver" > "$out/duplicate-return.log" 2>&1;then echo 'Reused training scene was accepted.' >&2;exit 1;fi
[[ "$(< "$out/duplicate-return/run.exit")" != 0 && ! -e "$out/duplicate-return/summary.json" ]]
echo 'Wide return catalog rejects reused scenes and checks both data splits.'
