#!/usr/bin/env bash
# Empty candidate splits are valid merge inputs, never standalone training data.
set -euo pipefail
prepare="${1:?Target preparation executable required}"
open="${2:?Target source checker required}"
merge_data="${3:?Dense merge executable required}"
merge_targets="${4:?Target merge executable required}"
fixtures="${5:?Pose fixtures required}"
out="${6:?New output directory required}"
mkdir "$out"
out="$(cd "$out" && pwd)"
"$fixtures" "$out/fixture"
data="$out/fixture/data.bin"
mkdir -p "$out/runs/expert-0" "$out/runs/expert-1"
for episode in 0 1;do printf '{}\n' > "$out/runs/expert-$episode/initial.json";printf '{}\n' > "$out/runs/expert-$episode/decisions.jsonl";done
: > "$out/candidates.jsonl"
data_sha="$(sha256sum "$data" | cut -d' ' -f1)";candidate_sha="$(sha256sum "$out/candidates.jsonl" | cut -d' ' -f1)"
jq -n --arg sha "$data_sha" '{episodes:2,actorInputsUnchanged:true,sourceDataSHA256:$sha,roles:[{role:"fitting",alsoInsideFreshColourDetection:0},{role:"validation",alsoInsideFreshColourDetection:0}]}' > "$out/survey.json"
args=("$data" "$out/runs" "$out/candidates.jsonl" "$out/survey.json" "$data_sha" "$candidate_sha")
if "$prepare" "${args[@]}" "$out/strict-prepare" > "$out/strict-prepare.log" 2>&1;then echo 'Empty target splits were accepted without opt-in.' >&2;exit 1;fi
"$prepare" "${args[@]}" "$out/empty-targets" --allow-empty-splits > "$out/prepare.log" 2>&1
jq -e '.passed and .fittingCandidates==0 and .validationCandidates==0 and .allowEmptyCandidateSplits and .actorInputsUnchanged' "$out/empty-targets/receipt.json" > /dev/null
dd if="$out/empty-targets/targets.bin" bs=1 skip=32 status=none | cmp -n 96 - /dev/zero
if "$open" "$data" "$out/empty-targets" strict > "$out/strict-open.log" 2>&1;then echo 'Standalone training accepted empty target splits.' >&2;exit 1;fi
"$open" "$data" "$out/empty-targets" merge > "$out/merge-open.log" 2>&1
cp -a "$out/empty-targets" "$out/corrupt-targets"
printf '\000\000\200\077' | dd of="$out/corrupt-targets/targets.bin" bs=1 seek=32 conv=notrunc status=none
bad_sha="$(sha256sum "$out/corrupt-targets/targets.bin" | cut -d' ' -f1)"
jq --arg sha "$bad_sha" '.targetsSHA256=$sha' "$out/corrupt-targets/receipt.json" > "$out/corrupt-targets/tmp.json"
mv "$out/corrupt-targets/tmp.json" "$out/corrupt-targets/receipt.json"
if "$open" "$data" "$out/corrupt-targets" merge > "$out/corrupt.log" 2>&1;then echo 'A nonzero masked target was accepted.' >&2;exit 1;fi
"$merge_data" "$out/merged" "$data" "$out/runs" "$data" "$out/runs" > "$out/merge-data.log" 2>&1
if "$merge_targets" "$out/merged" "$out/all-empty" "$data" "$out/empty-targets" "$data" "$out/empty-targets" > "$out/all-empty.log" 2>&1;then echo 'An all-empty aggregate was accepted.' >&2;exit 1;fi
[[ ! -e "$out/all-empty/receipt.json" ]]
rg -Fq 'aggregate target-position split is empty' "$out/all-empty.log"
echo 'Empty target splits remain masked, require opt-in and cannot form an empty training aggregate.'
