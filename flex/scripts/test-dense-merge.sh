#!/usr/bin/env bash
set -euo pipefail
project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$project"
output="${1:?New output directory required}"
mkdir "$output"
output="$(cd "$output" && pwd)"
build/flex/control/pose-fixtures "$output/fixture"
build/flex/control/control pack-data --data "$output/fixture/data.bin" --output "$output/packed" > "$output/pack.log"
for episode in 0 1; do
    mkdir -p "$output/runs/expert-$episode"
    printf '{}\n' > "$output/runs/expert-$episode/initial.json"
    printf '{}\n' > "$output/runs/expert-$episode/decisions.jsonl"
done
reference=build/flex/control/merge-dense-reference
merge=build/flex/control/merge-dense-many
"$reference" "$output/fixture/data.bin" "$output/runs" "$output/packed/data.bin" "$output/runs" "$output/reference-two"
"$reference" "$output/reference-two/data.bin" "$output/reference-two" "$output/fixture/mirrored-data.bin" "$output/runs" "$output/reference-three"
"$merge" "$output/actual" "$output/fixture/data.bin" "$output/runs" "$output/packed/data.bin" "$output/runs" "$output/fixture/mirrored-data.bin" "$output/runs"
cmp "$output/reference-three/data.bin" "$output/actual/data.bin"
jq -e '.episodes==6 and .fitTrajectories==3 and .sequenceLength==4 and .preservesFitValidationSplits and ([.records[].fit]==[true,true,true,false,false,false]) and ([.records[].source]==[0,1,2,0,1,2])' "$output/actual/report.json" > /dev/null
for episode in 0 1 2 3 4 5; do
    original=0; if (( episode>=3 )); then original=1; fi
    [[ "$(readlink -f "$output/actual/expert-$episode")" == "$(readlink -f "$output/runs/expert-$original")" ]]
    [[ "$(readlink "$output/actual/expert-$episode")" == "$(readlink -f "$output/runs/expert-$original")" ]]
done
build/flex/control/target-fixtures "$output/fixture/data.bin" "$output/fixture/mirrored-data.bin" "$output/targets"
"$merge" "$output/target-data" "$output/fixture/data.bin" "$output/runs" "$output/fixture/mirrored-data.bin" "$output/runs"
build/flex/control/merge-targets-two "$output/fixture/data.bin" "$output/targets/target-0" "$output/fixture/mirrored-data.bin" "$output/targets/target-mirrored" "$output/target-data" "$output/target-labels"
build/flex/control/merge-targets-many "$output/target-data" "$output/target-labels-many" "$output/fixture/data.bin" "$output/targets/target-0" "$output/fixture/mirrored-data.bin" "$output/targets/target-mirrored"
cmp "$output/target-labels/targets.bin" "$output/target-labels-many/targets.bin"
jq -e '.passed and .episodes==4 and .fittingHistories==2 and .validationHistories==2 and (.sourceTargetSHA256|length)==2' "$output/target-labels-many/receipt.json" > /dev/null
"$merge" "$output/target-three" "$output/fixture/data.bin" "$output/runs" "$output/fixture/mirrored-data.bin" "$output/runs" "$output/fixture/data.bin" "$output/runs"
build/flex/control/merge-targets-many "$output/target-three" "$output/target-three-labels" "$output/fixture/data.bin" "$output/targets/target-0" "$output/fixture/mirrored-data.bin" "$output/targets/target-mirrored" "$output/fixture/data.bin" "$output/targets/target-0"
jq -e '.passed and .episodes==6 and .fittingHistories==3 and .validationHistories==3 and (.sourceTargetSHA256|length)==3' "$output/target-three-labels/receipt.json" > /dev/null
if build/flex/control/merge-targets-many "$output/target-three" "$output/rejected-order" "$output/fixture/mirrored-data.bin" "$output/targets/target-mirrored" "$output/fixture/data.bin" "$output/targets/target-0" "$output/fixture/data.bin" "$output/targets/target-0" > "$output/rejected-order.log" 2>&1; then echo 'Changed source order was accepted.' >&2; exit 1; fi
[[ ! -e "$output/rejected-order" ]]
build/flex/control/target-preserve-added "$output/targets/target-0/targets.bin" "$output/target-labels/targets.bin" "$output/target-preserved.json"
jq -e '.passed and .existingHistoriesPreserved==2 and .expandedHistories==4' "$output/target-preserved.json" > /dev/null
for split in 0 1; do
    input_offset=$((32+split*48)); output_offset=$((32+(1+split*2)*48))
    dd if="$output/targets/target-mirrored/targets.bin" of="$output/new-labels-$split" bs=1 skip="$input_offset" count=48 status=none
    dd if="$output/target-labels/targets.bin" of="$output/merged-labels-$split" bs=1 skip="$output_offset" count=48 status=none
    cmp "$output/new-labels-$split" "$output/merged-labels-$split"
done
cp -a "$output/target-data" "$output/tampered-target-data"
jq '.records[1].fit=false' "$output/tampered-target-data/report.json" > "$output/tampered-target-data/report.tmp"
mv "$output/tampered-target-data/report.tmp" "$output/tampered-target-data/report.json"
if build/flex/control/merge-targets-two "$output/fixture/data.bin" "$output/targets/target-0" "$output/fixture/mirrored-data.bin" "$output/targets/target-mirrored" "$output/tampered-target-data" "$output/rejected-targets" > "$output/rejected-targets.log" 2>&1; then echo 'Mismatched target split was accepted.' >&2; exit 1; fi
[[ ! -e "$output/rejected-targets" ]]
cp -a "$output/target-data" "$output/tampered-pixels"
printf '\377' | dd of="$output/tampered-pixels/data.bin" bs=1 seek=32 conv=notrunc status=none
changed_sha="$(/usr/bin/sha256sum "$output/tampered-pixels/data.bin" | /usr/bin/cut -d' ' -f1)"
jq --arg sha "$changed_sha" '.dataSHA256=$sha' "$output/tampered-pixels/report.json" > "$output/tampered-pixels/report.tmp"
mv "$output/tampered-pixels/report.tmp" "$output/tampered-pixels/report.json"
if build/flex/control/merge-targets-two "$output/fixture/data.bin" "$output/targets/target-0" "$output/fixture/mirrored-data.bin" "$output/targets/target-mirrored" "$output/tampered-pixels" "$output/rejected-pixels" > "$output/rejected-pixels.log" 2>&1; then echo 'Changed source pixels were accepted.' >&2; exit 1; fi
rg -Fq 'aggregate changed source history' "$output/rejected-pixels.log"
[[ ! -e "$output/rejected-pixels" ]]
if build/flex/control/merge-targets-many "$output/tampered-pixels" "$output/rejected-pixels-many" "$output/fixture/data.bin" "$output/targets/target-0" "$output/fixture/mirrored-data.bin" "$output/targets/target-mirrored" > "$output/rejected-pixels-many.log" 2>&1; then echo 'Many-source merge accepted changed source pixels.' >&2; exit 1; fi
rg -Fq 'aggregate changed source history' "$output/rejected-pixels-many.log"
[[ ! -e "$output/rejected-pixels-many" ]]
printf PVDATA03 > "$output/short.bin"
if "$merge" "$output/rejected-short" "$output/short.bin" "$output/runs" "$output/fixture/data.bin" "$output/runs" > "$output/rejected-short.log" 2>&1; then echo 'Short dataset header was accepted.' >&2; exit 1; fi
[[ ! -e "$output/rejected-short" ]]
if "$merge" "$output/rejected-missing" "$output/fixture/data.bin" "$output/missing" "$output/packed/data.bin" "$output/runs" > "$output/rejected-missing.log" 2>&1; then echo 'Missing recorded history was accepted.' >&2; exit 1; fi
[[ ! -e "$output/rejected-missing/data.bin" ]]
echo 'Dense data and target merges preserve bytes, padding, history links and roles.'
