#!/usr/bin/env bash
set -euo pipefail
summary="${1:?Summary executable required}"
fixtures="${2:?Pose fixture executable required}"
output="${3:?New output directory required}"
mkdir "$output"
"$fixtures" "$output/fixture"
data="$output/fixture/data.bin"
for episode in 0 1; do
    mkdir -p "$output/runs/expert-$episode"
    jq -n '{studentStartAction:1,studentActions:2,denseOracleLabels:true,studentBeginsAfterConsumption:true}' > "$output/runs/expert-$episode/supervision.json"
    for step in 1 2; do
        row=$((32+episode*4*21224+4*21168+step*56))
        printf '\000\000\200\077' | dd of="$data" bs=1 seek=$((row+36)) conv=notrunc status=none
    done
    row=$((32+episode*4*21224+4*21168+2*56))
    printf '\000\000\200\277' | dd of="$data" bs=1 seek=$((row+52)) conv=notrunc status=none
    if (( episode==0 )); then printf '\000\000\200\277' | dd of="$data" bs=1 seek=$((row+32)) conv=notrunc status=none; fi
done
sha="$(sha256sum "$data" | cut -d' ' -f1)"
jq -n --arg sha "$sha" '{passed:true,episodes:2,datasetEpisodes:2,studentRollinMaxAbsError:0,studentRollinCommandsReplayed:4,denseOracleLabels:true,datasetInputsMatchActualRGBAndOwnFeedback:true,executedCommandsMatchRecordings:true,preActionAlignmentChecked:true,zeroPaddingChecked:true,taskEventHintAbsent:true,dataSHA256:$sha}' > "$output/audit.json"
"$summary" "$data" "$output/runs" "$output/audit.json" > "$output/summary.json"
jq -e '.passed and .studentActions==4 and .fitting==[1,2,0,0,0,0,1,1,0,0,0,1] and .validation==[1,2,1,1,0,0,1,0,1,1,1,1] and .oracleTrainingOnly and .actorInputsUnchanged' "$output/summary.json" > /dev/null
jq '.studentRollinCommandsReplayed=3' "$output/audit.json" > "$output/bad-audit.json"
if "$summary" "$data" "$output/runs" "$output/bad-audit.json" > "$output/bad.log" 2>&1; then echo 'Inconsistent replay count was accepted.' >&2; exit 1; fi
echo 'Return intervention summary checks windows, direction changes and replay counts.'
