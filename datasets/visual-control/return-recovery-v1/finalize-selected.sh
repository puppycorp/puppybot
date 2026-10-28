#!/usr/bin/env bash
set -euo pipefail
project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
dataset="$project/datasets/visual-control/return-recovery-v1"
a="$dataset/artifacts-primitive"
base="$project/datasets/visual-control/approach35-v1/artifacts"
root="$project/build/flex/sim/approach35-v2"
[[ ! -e "$a/data96" && ! -e "$a/selected32-v1" ]]
trap 'status=$?; printf "%s\n" "$status" > "$a/finalize-selected.exit"' EXIT
cd "$project"
[[ -f "$a/collection.exit" ]]
for worker in 0 1 2 3; do [[ -f "$a/worker-$worker.exit" ]]; done
build/flex/control/compiler "$dataset/assemble-selected.flex" -o "$a/assemble-selected"
jq -c --arg a "$a" --slurpfile overrides "$a/selection-overrides.json" '
 sort_by([(.fit|not),.worker,.sourceIndex]) | to_entries[] |
 .key as $i | .value as $c |
 {datasetIndex:$i,fit:$c.fit,worker:$c.worker,catalogIndex:$c.sourceIndex,episodeIndex:$c.sourceIndex,
  sourceData:($a+(if $c.worker<2 then "/packed-"+($c.worker|tostring)+"/data.bin" else "/runs/"+($c.worker|tostring)+"/data.partial.bin" end)),
  sourceRun:($a+"/runs/"+($c.worker|tostring)),
  auditReceipt:($a+(if $c.worker==1 then "/verified-1/result.json" else "/individual-"+($c.worker|tostring)+"/"+($c.sourceIndex|tostring)+"/result.json" end))} |
 .+($overrides[0]|map(select(.worker==$c.worker and .catalogIndex==$c.sourceIndex))|first // {})
' "$a/catalog.json" > "$a/selected-records.jsonl"
mkdir "$a/selection-guards"
for variant in duplicate wrong-scene wrong-audit; do
 expression='.[1]=(.[0]+{datasetIndex:1})|.[]'
 message='duplicate or misplaced correction scene'
 if [[ "$variant" == wrong-scene ]]; then expression='.[0].episodeIndex=1|.[]'; message='selection substituted another physical scene'; fi
 if [[ "$variant" == wrong-audit ]]; then expression='.[0].auditReceipt=.[1].auditReceipt|.[]'; message='audit does not cover the selected source SHA and episode'; fi
 jq -cs "$expression" "$a/selected-records.jsonl" > "$a/selection-guards/$variant.jsonl"
 if "$a/assemble-selected" "$a" "$a/selection-guards/$variant.jsonl" "$a/selection-guards/$variant-output" > "$a/selection-guards/$variant.log" 2>&1; then
  echo 'An invalid history selection was accepted'; exit 1
 fi
 [[ "$(< "$a/selection-guards/$variant.log")" == *"$message"* && ! -e "$a/selection-guards/$variant-output" ]]
done
"$a/assemble-selected" "$a" "$a/selected-records.jsonl" "$a/selected32-v1" > "$a/selected32-v1.log" 2>&1
"$a/subset" "$base/data128/data.bin" "$base/data128" "$a/base64"
"$a/merge" "$a/base64/data.bin" "$a/base64" "$a/selected32-v1/data.bin" "$a/selected32-v1" "$a/assembled-selected96-v1"
"$a/runtime/build/flex/control/control" pack-data --data "$a/assembled-selected96-v1/data.bin" --output "$a/repacked-selected96-v1" > "$a/repacked-selected96-v1.log" 2>&1
cmp "$a/assembled-selected96-v1/data.bin" "$a/repacked-selected96-v1/data.bin"
jq -n --slurpfile final "$a/assembled-selected96-v1/report.json" --slurpfile base "$a/base64/report.json" --slurpfile selected "$a/selected32-v1/report.json" --slurpfile old "$base/verified/result.json" -f "$dataset/coverage-selected.jq" > "$a/coverage.json"
sha256sum -c "$a/runtime.sha256" > "$a/final-selected-runtime-integrity.log"
sha256sum -c "$a/scenes.sha256" > "$a/final-selected-scene-integrity.log"
sha256sum -c "$a/recipe.sha256" > "$a/final-selected-collection-recipe-integrity.log"
mkdir "$a/finalizer-used"
cp "$dataset/"{assemble-selected.flex,coverage-selected.jq,finalize-selected.sh} "$a/finalizer-used/"
cp "$a/"{selected-records.jsonl,selection-overrides.json} "$a/finalizer-used/"
sha256sum "$a/finalizer-used/"* "$a/assemble-selected" > "$a/finalizer.sha256"
mv "$a/assembled-selected96-v1" "$a/data96"
printf '0\n' > "$a/dataset.exit"
echo '96 histories accepted through audited exact-source selection; failed attempts and original roles preserved'
