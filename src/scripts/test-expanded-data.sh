#!/usr/bin/env bash
set -euo pipefail

output="${1:?New output directory required}"
tools="${2:-$PWD/build/flex/control}"
mkdir "$output"
output="$(cd "$output" && pwd)"
"$tools/pose-fixtures" "$output/fixture"
"$tools/target-fixtures" "$output/fixture/data.bin" "$output/fixture/mirrored-data.bin" "$output/fixture-targets"
for i in 0 1; do
    mkdir -p "$output/runs/expert-$i"
    printf '{}\n' > "$output/runs/expert-$i/initial.json"
    printf '{}\n' > "$output/runs/expert-$i/decisions.jsonl"
done
"$tools/merge-dense-many" "$output/data-4" "$output/fixture/data.bin" "$output/runs" "$output/fixture/mirrored-data.bin" "$output/runs"
"$tools/merge-targets-two" "$output/fixture/data.bin" "$output/fixture-targets/target-0" "$output/fixture/mirrored-data.bin" "$output/fixture-targets/target-mirrored" "$output/data-4" "$output/targets-4"
for size in 4 8 16 32 64 128; do
    next=$((size*2))
    "$tools/merge-dense-many" "$output/data-$next" "$output/data-$size/data.bin" "$output/data-$size" "$output/data-$size/data.bin" "$output/data-$size"
    "$tools/merge-targets-two" "$output/data-$size/data.bin" "$output/targets-$size" "$output/data-$size/data.bin" "$output/targets-$size" "$output/data-$next" "$output/targets-$next"
done
"$tools/merge-dense-many" "$output/data-258" "$output/data-256/data.bin" "$output/data-256" "$output/fixture/data.bin" "$output/runs"
"$tools/merge-targets-two" "$output/data-256/data.bin" "$output/targets-256" "$output/fixture/data.bin" "$output/fixture-targets/target-0" "$output/data-258" "$output/targets-258"
for size in 256 512; do
    next=$((size*2))
    "$tools/merge-dense-many" "$output/data-$next" "$output/data-$size/data.bin" "$output/data-$size" "$output/data-$size/data.bin" "$output/data-$size"
    "$tools/merge-targets-two" "$output/data-$size/data.bin" "$output/targets-$size" "$output/data-$size/data.bin" "$output/targets-$size" "$output/data-$next" "$output/targets-$next"
done
if "$tools/merge-dense-many" "$output/too-many" "$output/data-1024/data.bin" "$output/data-1024" "$output/fixture/data.bin" "$output/runs" > "$output/too-many.log" 2>&1; then echo 'More than 1024 histories were accepted.' >&2; exit 1; fi
[[ ! -e "$output/too-many" ]]
"$tools/dataset-limit-tests" "$output/data-1024/data.bin" PVDATA04
"$tools/merge-targets-many" "$output/data-1024" "$output/targets-1024-many" "$output/data-512/data.bin" "$output/targets-512" "$output/data-512/data.bin" "$output/targets-512"
cmp "$output/targets-1024/targets.bin" "$output/targets-1024-many/targets.bin"
for episode in 0 127 511 512 1023; do
    [[ "$(readlink "$output/data-1024/expert-$episode")" == "$(readlink -f "$output/data-1024/expert-$episode")" ]]
done
jq -e '.episodes==1024 and .fittingHistories==512 and .validationHistories==512 and .mergedDataAndPaddingChecked' "$output/targets-1024/receipt.json" > /dev/null
"$tools/preflight-expanded-targets" "$output/data-1024/data.bin" "$output/targets-1024" "$output/preflight-1024.json"
jq -e '.passed and .episodes==1024 and .fittingHistories==512 and .validationHistories==512 and .actorInputsUnchanged' "$output/preflight-1024.json" > /dev/null
[[ "$(head -c 8 "$output/data-256/data.bin")" == PVDATA03 ]]
[[ "$(head -c 8 "$output/data-258/data.bin")" == PVDATA04 ]]
jq -e '.episodes==258 and .fitTrajectories==129 and (.records|length)==258 and ([.records[].fit]|map(select(.))|length)==129 and .preservesFitValidationSplits' "$output/data-258/report.json" > /dev/null
jq -e '.passed and .episodes==258 and .fittingHistories==129 and .validationHistories==129 and .mergedDataAndPaddingChecked' "$output/targets-258/receipt.json" > /dev/null
"$tools/data-preserve-added" "$output/data-256/data.bin" "$output/data-258/data.bin" "$output/data-preserved.json"
"$tools/target-preserve-added" "$output/targets-256/targets.bin" "$output/targets-258/targets.bin" "$output/targets-preserved.json"
for receipt in "$output/data-preserved.json" "$output/targets-preserved.json"; do
    jq -e '.passed and .existingHistoriesPreserved==256 and .expandedHistories==258 and .expandedFittingHistories==129' "$receipt" > /dev/null
done
cp "$output/data-258/data.bin" "$output/tampered-data.bin"
printf '\377' | dd of="$output/tampered-data.bin" bs=1 seek=32 conv=notrunc status=none
if "$tools/data-preserve-added" "$output/data-256/data.bin" "$output/tampered-data.bin" "$output/rejected-data.json" > "$output/rejected-data.log" 2>&1; then echo 'Changed existing image was accepted.' >&2; exit 1; fi
cp "$output/targets-258/targets.bin" "$output/tampered-targets.bin"
printf '\377' | dd of="$output/tampered-targets.bin" bs=1 seek=32 conv=notrunc status=none
if "$tools/target-preserve-added" "$output/targets-256/targets.bin" "$output/tampered-targets.bin" "$output/rejected-targets.json" > "$output/rejected-targets.log" 2>&1; then echo 'Changed existing label was accepted.' >&2; exit 1; fi
"$tools/summarize-demonstrations" "$output/data-258/data.bin" > "$output/summary.json"
jq -e '.episodes==258 and .fittingHistories==129 and .supervisedFrames==[258,129,258,129]' "$output/summary.json" > /dev/null
cp "$output/data-258/data.bin" "$output/invalid-legacy.bin"
printf PVDATA03 | dd of="$output/invalid-legacy.bin" bs=1 conv=notrunc status=none
if "$tools/summarize-demonstrations" "$output/invalid-legacy.bin" > "$output/invalid-legacy.log" 2>&1; then echo 'Legacy format accepted more than 256 histories.' >&2; exit 1; fi
# A sparse valid header exercises the old 2 GiB guard and the new mapping path
# without allocating or hashing gigabytes of physical test data.
truncate -s $((32+257*400*21224)) "$output/sparse.bin"
printf 'PVDATA04\001\001\000\000\000\000\000\000\200\000\000\000\000\000\000\000\220\001\000\000\000\000\000\000' | dd of="$output/sparse.bin" bs=1 conv=notrunc status=none
"$tools/dataset-limit-tests" "$output/sparse.bin" PVDATA04
printf PVDATA03 | dd of="$output/sparse.bin" bs=1 conv=notrunc status=none
if "$tools/dataset-limit-tests" "$output/sparse.bin" PVDATA03 > "$output/sparse-legacy.log" 2>&1; then echo 'Legacy format accepted more than 2 GiB.' >&2; exit 1; fi
truncate -s $((8589934592+1)) "$output/too-large.bin"
printf PVDATA04 | dd of="$output/too-large.bin" bs=1 conv=notrunc status=none
if "$tools/dataset-limit-tests" "$output/too-large.bin" PVDATA04 > "$output/too-large.log" 2>&1; then echo 'Expanded format accepted more than 8 GiB.' >&2; exit 1; fi
echo 'Expanded data preserves split and target bytes; legacy limits remain enforced.'
