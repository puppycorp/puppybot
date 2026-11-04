#!/usr/bin/env bash
set -euo pipefail

summary="${1:?Demonstration summary executable required}"
fixtures="${2:?Pose fixture executable required}"
output="${3:?New output directory required}"
mkdir "$output"
"$fixtures" "$output/fixture"
"$summary" "$output/fixture/data.bin" > "$output/summary.json"
jq -e '.episodes==2 and .fittingHistories==1 and .sequenceLength==4 and
    .validFrames==[2,1,2,1] and .supervisedFrames==[2,1,2,1] and
    .historiesWithSupervision==[1,1,1,1] and .comparableActions==[2,1,2,1] and
    .expertExecutedDisagreements==[0,0,0,0] and
    .expertDirectionComparisons==[1,0,1,0] and .expertDirectionReversals==[0,0,0,0] and
    .executedDirectionComparisons==[1,0,1,0] and .executedDirectionReversals==[0,0,0,0] and
    .expertActionClasses==[[0,0,2,0,0,0,0,0],[0,0,1,0,0,0,0,0],
        [0,0,2,0,0,0,0,0],[0,0,1,0,0,0,0,0]]' "$output/summary.json" > /dev/null
[[ "$(jq -r .datasetSHA256 "$output/summary.json")" == "$(sha256sum "$output/fixture/data.bin" | cut -d' ' -f1)" ]]
cp "$output/fixture/data.bin" "$output/reversal.bin"
printf '\000\000\200\277' | dd of="$output/reversal.bin" bs=1 seek=$((32+4*21168+56+32)) conv=notrunc status=none
printf '\000\000\200\277' | dd of="$output/reversal.bin" bs=1 seek=$((32+4*21168+56+52)) conv=notrunc status=none
"$summary" "$output/reversal.bin" > "$output/reversal.json"
jq -e '.expertDirectionComparisons==[1,0,1,0] and .expertDirectionReversals==[1,0,0,0] and .executedDirectionComparisons==[1,0,1,0] and .executedDirectionReversals==[1,0,0,0]' "$output/reversal.json" > /dev/null
printf PVDATA03 > "$output/short.bin"
if "$summary" "$output/short.bin" > "$output/short.log" 2>&1; then
    echo 'Demonstration summary accepted a truncated header.' >&2; exit 1
fi
cp "$output/fixture/data.bin" "$output/unmasked.bin"
printf '\000\000\200\077' | dd of="$output/unmasked.bin" bs=1 seek=$((32+4*21168+24)) conv=notrunc status=none
if "$summary" "$output/unmasked.bin" > "$output/unmasked.log" 2>&1; then
    echo 'Demonstration summary accepted task-event input.' >&2; exit 1
fi
echo 'Demonstration summary counts and input guards passed.'
