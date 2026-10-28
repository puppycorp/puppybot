#!/usr/bin/env bash
# Check an additional audited training corpus against the reserved development rooms.
set -euo pipefail
scenes="$(realpath "${1:?Prepared diverse development rooms required}")"
corpus="$(realpath "${2:?Audited corpus admission required}")"
out="${3:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out"
data="$corpus/expanded/data.bin";coverage="$corpus/coverage.json"
[[ "$(< "$scenes/run.exit")" == 0 && "$(< "$corpus/run.exit")" == 0 ]]
jq -e '.passed and .developmentOnly and .episodes==8 and .uniqueStartingPoses==8 and .reservedFinalUntouched' "$scenes/summary.json" > /dev/null
sha="$(sha256sum "$data" | cut -d' ' -f1)";count="$(jq -er '.episodes | select(type=="number" and .>=1 and .<=10000 and floor==.)' "$coverage")"
jq -e --arg sha "$sha" '.passed and .dataSHA256==$sha and .newHistoriesIndependentlyAudited and .actorInputsUnchanged' "$coverage" > /dev/null
sha256sum "$data" "$coverage" "$scenes/summary.json" > "$out/inputs.sha256"
for ((index=0;index<count;index++));do
    for file in case.json environment.bin;do sha256sum "$corpus/expanded/expert-$index/scene/$file" >> "$out/corpus-scenes.sha256";done
done
cut -d' ' -f1 "$out/corpus-scenes.sha256" > "$out/corpus-hashes.txt"
for ((index=0;index<8;index++));do
    for file in case.json environment.bin;do
        path="$scenes/catalog/$index/$file";digest="$(sha256sum "$path" | cut -d' ' -f1)";status=0;rg -Fxq "$digest" "$out/corpus-hashes.txt" || status=$?
        if (( status==0 ));then echo "Development case $index duplicates a training corpus file." >&2;exit 1;fi
        if (( status!=1 ));then echo 'Could not check corpus hashes.' >&2;exit "$status";fi
        sha256sum "$path" >> "$out/inputs.sha256"
    done
done
sha256sum -c "$out/inputs.sha256" > "$out/integrity.log"
sha256sum -c "$out/corpus-scenes.sha256" > "$out/corpus-integrity.log"
jq -n --arg sha "$sha" --arg scenes "$scenes" --argjson count "$count" '{passed:true,developmentOnly:true,dataSHA256:$sha,corpusHistories:$count,sceneDirectory:$scenes,episodes:8,exactCaseAndEnvironmentFilesDisjoint:true,similarGeometryStillPossible:true,actorInputsUnchanged:true,reservedFinalUntouched:true}' > "$out/summary.json"
echo 'Development scenes are exactly disjoint from the audited corpus.'
