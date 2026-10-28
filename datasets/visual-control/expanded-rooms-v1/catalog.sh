#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?}"
root="$project/build/flex/sim/expanded-rooms-v1"
out="$root/cohort-catalog-v1"
old="$project/build/flex/sim/late-search-v1/artifacts-v2/data172"
[[ ! -e "$out" ]]
mkdir "$out"
for ((i=0;i<172;i++));do /usr/bin/sha256sum "$old/expert-$i/scene/case.json" | /usr/bin/cut -d' ' -f1;done | /usr/bin/sort -u > "$out/existing-case-shas.txt"
validation_layouts=(6 7 6 7 6 7)
validation_scenes=(8 9 10 12 13 15)
for worker in {0..5};do
    mkdir "$out/$worker"
    for episode in {0..4};do
        fit=true;layout=$((12+worker));scene=$(((worker*2+episode*3)%16));source="$root/scenes/$layout/$scene"
        if (( episode==4 ));then fit=false;layout=${validation_layouts[$worker]};scene=${validation_scenes[$worker]};source="$project/datasets/visual-control/approach35-v1/artifacts/scenes/$layout/$scene";fi
        /usr/bin/jq -e --argjson layout "$layout" --argjson fit "$fit" '.layoutId==$layout and .fit==$fit' "$source/layout.json" >/dev/null
        sha="$(/usr/bin/sha256sum "$source/case.json" | /usr/bin/cut -d' ' -f1)"
        if /usr/bin/rg -Fxq "$sha" "$out/existing-case-shas.txt";then echo "Candidate scene already in admitted data: $layout/$scene" >&2;exit 1;fi
        cp -aL "$source" "$out/$worker/$episode"
        /usr/bin/jq -n --argjson worker "$worker" --argjson episode "$episode" --argjson fit "$fit" --argjson layout "$layout" --argjson scene "$scene" --arg sha "$sha" '{worker:$worker,episode:$episode,fit:$fit,layout:$layout,scene:$scene,caseSHA256:$sha}' >> "$out/records.jsonl"
    done
done
/usr/bin/jq -s '{fittingScenes:(map(select(.fit))|length),validationScenes:(map(select(.fit|not))|length),records:.}' "$out/records.jsonl" > "$out/report.json"
/usr/bin/jq -e '.fittingScenes==24 and .validationScenes==6 and ([.records[].caseSHA256]|unique|length)==30 and ([.records[]|select(.fit)|.layout]|unique)==[12,13,14,15,16,17] and ([.records[]|select(.fit|not)|.layout]|unique)==[6,7] and all(.records[]; .layout!=10 and .layout!=11 and .fit==(.episode<4))' "$out/report.json" >/dev/null
