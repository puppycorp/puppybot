#!/usr/bin/env bash
set -euo pipefail

summary="${1:?Episode summary executable required}"
aggregate="${2:?Aggregate summary executable required}"
fixtures="${3:?Pose fixture executable required}"
output="${4:?New output directory required}"
mkdir "$output"
"$fixtures" "$output/fixture"
"$summary" "$output/fixture/data.bin" > "$output/episodes.json"
"$aggregate" "$output/fixture/data.bin" > "$output/aggregate.json"
jq -e --slurpfile total "$output/aggregate.json" '
    .episodes==2 and .fittingHistories==1 and .sequenceLength==4 and
    .datasetSHA256==$total[0].datasetSHA256 and
    [.rows[].index]==[0,1] and [.rows[].fit]==[true,false] and
    [.rows[].supervisedFrames]==[[2,1],[2,1]] and
    [.rows[].searchClasses]==[[0,0,2,0,0,0,0,0],[0,0,2,0,0,0,0,0]] and
    [.rows[].returnClasses]==[[0,0,1,0,0,0,0,0],[0,0,1,0,0,0,0,0]] and
    ([.rows[].supervisedFrames[]]|add)==($total[0].supervisedFrames|add)' "$output/episodes.json" > /dev/null
cp "$output/fixture/data.bin" "$output/unmasked.bin"
printf '\000\000\200\077' | dd of="$output/unmasked.bin" bs=1 seek=$((32+4*21168+24)) conv=notrunc status=none
if "$summary" "$output/unmasked.bin" > "$output/unmasked.log" 2>&1; then
    echo 'Episode summary accepted task-event input.' >&2; exit 1
fi
cp "$output/fixture/data.bin" "$output/reversion.bin"
printf '\000\000\200\077' | dd of="$output/reversion.bin" bs=1 seek=$((32+4*21168+56+36)) conv=notrunc status=none
printf '\000\000\000\000' | dd of="$output/reversion.bin" bs=1 seek=$((32+4*21168+2*56+36)) conv=notrunc status=none
if "$summary" "$output/reversion.bin" > "$output/reversion.log" 2>&1; then
    echo 'Episode summary accepted a return-to-search transition.' >&2; exit 1
fi
echo 'Per-episode demonstration counts and input guards passed.'
