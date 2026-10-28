#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/expanded-rooms-v1"
old="$root/admission-v3/data202"
out="$root/contact-cohort-catalog-v3"
[[ ! -e "$out" ]]
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
sha="$(/usr/bin/sha256sum "$old/data.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$sha" '.passed and .episodes==202 and .dataSHA256==$sha' "$root/admission-v3/coverage.json" > /dev/null
declare -A prior_cases prior_environments heldout_cases heldout_environments
for ((i=0;i<202;i++));do
    hash="$(/usr/bin/sha256sum "$old/expert-$i/scene/case.json" | /usr/bin/cut -d' ' -f1)"
    prior_cases["$hash"]=1
    hash="$(/usr/bin/sha256sum "$old/expert-$i/scene/environment.bin" | /usr/bin/cut -d' ' -f1)"
    prior_environments["$hash"]=1
done
for pilot in correction-rollin-pilot-v1 correction-contact-pilot-v1;do
    for episode in 0 1;do
        hash="$(/usr/bin/sha256sum "$root/$pilot/catalog/$episode/case.json" | /usr/bin/cut -d' ' -f1)"
        prior_cases["$hash"]=1
        hash="$(/usr/bin/sha256sum "$root/$pilot/catalog/$episode/environment.bin" | /usr/bin/cut -d' ' -f1)"
        prior_environments["$hash"]=1
    done
done
for layout in 18 19;do
    source="$root/development-scenes-v1/$layout"
    hash="$(/usr/bin/sha256sum "$source/environment.bin" | /usr/bin/cut -d' ' -f1)";heldout_environments["$hash"]=1
    for scene in {0..15};do hash="$(/usr/bin/sha256sum "$source/$scene/case.json" | /usr/bin/cut -d' ' -f1)";heldout_cases["$hash"]=1;done
done
for layout in 20 21 22 23;do
    source="$root/generalization-scenes-v1/$layout"
    hash="$(/usr/bin/sha256sum "$source/environment.bin" | /usr/bin/cut -d' ' -f1)";heldout_environments["$hash"]=1
    for scene in {0..15};do hash="$(/usr/bin/sha256sum "$source/$scene/case.json" | /usr/bin/cut -d' ' -f1)";heldout_cases["$hash"]=1;done
done
for worker in {0..3};do
    mkdir "$out/$worker"
    for episode in {0..3};do
        fit=true;layout=$((12+(worker*3+episode)%6))
        if (( episode==3 ));then fit=false;layout=$((24+worker%2));fi
        found=0
        for scene in {0..15};do
            source="$root/scenes/$layout/$scene"
            if ! $fit;then source="$root/contact-validation-scenes-v1/$layout/$scene";fi
            /usr/bin/jq -e --argjson layout "$layout" --argjson fit "$fit" '.layoutId==$layout and .fit==$fit' "$source/layout.json" > /dev/null
            hash="$(/usr/bin/sha256sum "$source/case.json" | /usr/bin/cut -d' ' -f1)"
            env="$(/usr/bin/sha256sum "$source/environment.bin" | /usr/bin/cut -d' ' -f1)"
            if [[ "${prior_cases[$hash]+yes}" || "${heldout_cases[$hash]+yes}" || "${heldout_environments[$env]+yes}" ]];then continue;fi
            if ! $fit && [[ "${prior_environments[$env]+yes}" ]];then continue;fi
            prior_cases["$hash"]=1
            cp -aL "$source" "$out/$worker/$episode"
            /usr/bin/jq -n --argjson worker "$worker" --argjson episode "$episode" --argjson fit "$fit" --argjson layout "$layout" --argjson scene "$scene" --arg hash "$hash" --arg env "$env" '{worker:$worker,episode:$episode,fit:$fit,layout:$layout,scene:$scene,caseSHA256:$hash,environmentSHA256:$env}' >> "$out/records.jsonl"
            found=1;break
        done
        [[ "$found" == 1 ]] || { echo "No unused scene for layout $layout" >&2;exit 1; }
    done
done
/usr/bin/jq -s --arg sha "$sha" '{passed:(length==16 and ([.[].caseSHA256]|unique|length)==16 and ([.[]|select(.fit)]|length)==12 and ([.[]|select(.fit|not)]|length)==4 and ([.[]|select(.fit)|.layout]|unique)==[12,13,14,15,16,17] and ([.[]|select(.fit|not)|.layout]|unique)==[24,25] and all(.[];.fit==(.episode<3))),sourceDataSHA256:$sha,caseHashesExcludePriorAndPilots:true,caseAndEnvironmentHashesExcludeDevelopmentAndGeneralization:true,reservedFinalLayoutsExcluded:true,selection:"First unused indexed case in each predetermined layout",records:.}' "$out/records.jsonl" > "$out/report.json"
/usr/bin/jq -e '.passed' "$out/report.json" > /dev/null
echo 'Sixteen distinct on-policy collection scenes selected; no episodes have been collected.'
