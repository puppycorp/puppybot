#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/expanded-rooms-v1"
old="$root/admission-v3/data202"
out="$root/return-pilot-catalog-v1"
[[ ! -e "$out" ]]
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
old_sha="$(/usr/bin/sha256sum "$old/data.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$old_sha" '.passed and .episodes==202 and .dataSHA256==$sha' "$root/admission-v3/coverage.json" > /dev/null
declare -A cases fitting_env heldout_env
for ((i=0;i<202;i++));do
    hash="$(/usr/bin/sha256sum "$old/expert-$i/scene/case.json" | /usr/bin/cut -d' ' -f1)";cases["$hash"]=1
    if (( i<160 ));then hash="$(/usr/bin/sha256sum "$old/expert-$i/scene/environment.bin" | /usr/bin/cut -d' ' -f1)";fitting_env["$hash"]=1;fi
done
for pilot in correction-rollin-pilot-v1 correction-contact-pilot-v1;do
    for episode in 0 1;do hash="$(/usr/bin/sha256sum "$root/$pilot/catalog/$episode/case.json" | /usr/bin/cut -d' ' -f1)";cases["$hash"]=1;done
done
for worker in {0..3};do
    for episode in {0..3};do hash="$(/usr/bin/sha256sum "$root/contact-cohort-v1/catalog/$worker/$episode/case.json" | /usr/bin/cut -d' ' -f1)";cases["$hash"]=1;done
done
for layout in 18 19;do
    source="$root/development-scenes-v1/$layout"
    hash="$(/usr/bin/sha256sum "$source/environment.bin" | /usr/bin/cut -d' ' -f1)";heldout_env["$hash"]=1
    for scene in {0..15};do hash="$(/usr/bin/sha256sum "$source/$scene/case.json" | /usr/bin/cut -d' ' -f1)";cases["$hash"]=1;done
done
for layout in 20 21 22 23;do
    source="$root/generalization-scenes-v1/$layout"
    hash="$(/usr/bin/sha256sum "$source/environment.bin" | /usr/bin/cut -d' ' -f1)";heldout_env["$hash"]=1
    for scene in {0..15};do hash="$(/usr/bin/sha256sum "$source/$scene/case.json" | /usr/bin/cut -d' ' -f1)";cases["$hash"]=1;done
done
for episode in 0 1;do
    fit=true;layout=12;root_scenes="$root/scenes"
    if (( episode==1 ));then fit=false;layout=25;root_scenes="$root/contact-validation-scenes-v1";fi
    found=0
    for scene in {0..15};do
        source="$root_scenes/$layout/$scene"
        /usr/bin/jq -e --argjson layout "$layout" --argjson fit "$fit" '.layoutId==$layout and .fit==$fit' "$source/layout.json" > /dev/null
        hash="$(/usr/bin/sha256sum "$source/case.json" | /usr/bin/cut -d' ' -f1)"
        env="$(/usr/bin/sha256sum "$source/environment.bin" | /usr/bin/cut -d' ' -f1)"
        if [[ "${cases[$hash]+yes}" || "${heldout_env[$env]+yes}" ]];then continue;fi
        if ! $fit && [[ "${fitting_env[$env]+yes}" ]];then continue;fi
        cases["$hash"]=1;cp -aL "$source" "$out/$episode"
        /usr/bin/jq -n --argjson episode "$episode" --argjson layout "$layout" --argjson scene "$scene" --argjson fit "$fit" --arg hash "$hash" --arg env "$env" '{episode:$episode,layout:$layout,scene:$scene,fit:$fit,caseSHA256:$hash,environmentSHA256:$env}' >> "$out/records.jsonl"
        found=1;break
    done
    [[ "$found" == 1 ]] || { echo "No unused case for layout $layout" >&2;exit 1; }
done
/usr/bin/jq -s --arg old "$old_sha" '{passed:(length==2 and .[0].fit and (.[1].fit|not) and ([.[].caseSHA256]|unique|length)==2),sourceDataSHA256:$old,casesExcludePriorCohortsAndDevelopment:true,environmentsExcludeDevelopmentAndGeneralization:true,validationEnvironmentExcludedFromFitting:true,reservedFinalLayoutsExcluded:true,records:.}' "$out/records.jsonl" > "$out/report.json"
/usr/bin/jq -e '.passed and .records[0].layout==12 and .records[1].layout==25' "$out/report.json" > /dev/null
echo 'Two distinct return-recovery pilot cases selected.'
