#!/usr/bin/env bash
set -euo pipefail
summary="${1:?Summary executable required}"
fixtures="${2:?Pose fixture executable required}"
output="${3:?New output directory required}"
mkdir "$output"
"$fixtures" "$output/fixture"
data="$output/fixture/data.bin"
for episode in 0 1;do
    mkdir -p "$output/runs/expert-$episode"
    jq -n '{studentStartAction:0,studentActions:3,denseOracleLabels:true,studentBeginsAfterConsumption:false}' > "$output/runs/expert-$episode/supervision.json"
    row=$((32+episode*4*21224+4*21168+56))
    printf '\000\000\200\277' | dd of="$data" bs=1 seek=$((row+52)) conv=notrunc status=none
    if (( episode==1 ));then printf '\000\000\200\277' | dd of="$data" bs=1 seek=$((row+32)) conv=notrunc status=none;fi
done
sha="$(sha256sum "$data" | cut -d' ' -f1)"
jq -n --arg sha "$sha" '{passed:true,episodes:2,datasetEpisodes:2,studentRollinMaxAbsError:0,studentRollinCommandsReplayed:6,denseOracleLabels:true,datasetInputsMatchActualRGBAndOwnFeedback:true,executedCommandsMatchRecordings:true,preActionAlignmentChecked:true,zeroPaddingChecked:true,taskEventHintAbsent:true,dataSHA256:$sha}' > "$output/audit.json"
"$summary" "$data" "$output/runs" "$output/audit.json" > "$output/summary.json"
jq -e '.passed and .studentActions==6 and .fitSearch==[1,2,1,1,0,0,1,0,1,1,1,1] and .validationSearch==[1,2,0,0,0,0,1,1,0,0,0,1] and .fitReturn==[1,1,0,0,0,0,0,0,0,0,0,0] and .validationReturn==[1,1,0,0,0,0,0,0,0,0,0,0] and .matrixRowsTeacherColumnsStudent and .fitSearchMatrix[2][2]==1 and .fitSearchMatrix[2][5]==1 and .validationSearchMatrix[2][2]==1 and .validationSearchMatrix[5][5]==1 and .fitReturnMatrix[2][2]==1 and .validationReturnMatrix[2][2]==1 and ([.fitSearchMatrix[][]]|add)==2 and ([.validationSearchMatrix[][]]|add)==2 and .oracleTrainingOnly and .actorInputsUnchanged' "$output/summary.json" > /dev/null
jq '.studentRollinCommandsReplayed=5' "$output/audit.json" > "$output/bad-audit.json"
if "$summary" "$data" "$output/runs" "$output/bad-audit.json" > "$output/bad.log" 2>&1;then echo 'Inconsistent replay count was accepted.' >&2;exit 1;fi
jq '.studentStartAction=1' "$output/runs/expert-0/supervision.json" > "$output/invalid.json"
mv "$output/invalid.json" "$output/runs/expert-0/supervision.json"
if "$summary" "$data" "$output/runs" "$output/audit.json" > "$output/bad-window.log" 2>&1;then echo 'Noninitial student roll-in was accepted.' >&2;exit 1;fi
echo 'Search intervention summary checks phase boundaries, commands and audited roll-in counts.'
