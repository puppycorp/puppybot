#!/usr/bin/env bash
# Check prepared pose labels independently and reject a mismatched trace.
set -euo pipefail
project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
data="$(realpath "${1:?Packed two-episode data required}")"
runs="$(realpath "${2:?Recorded runs required}")"
out="${3:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out";out="$(cd "$out" && pwd)"
prepare="${PUPPYBOT_MEMORY_POSE_PREPARE:-$project/build/flex/control/prepare-memory-pose}";open="$project/build/flex/control/pose-open-tests"
sha256sum "$prepare" > "$out/preparer.sha256"
"$prepare" "$data" "$runs" "$out/targets" > "$out/prepare.log" 2> "$out/progress.log"
jq -se 'map({verifiedEpisodes,totalEpisodes})==[{verifiedEpisodes:1,totalEpisodes:2},{verifiedEpisodes:2,totalEpisodes:2}]' "$out/progress.log" > /dev/null
"$open" "$data" "$out/targets" > "$out/open.log"
sha="$(sha256sum "$data" | cut -d' ' -f1)"
jq -e --arg sha "$sha" '.passed and .verifiedAgainstPhysicalTrace and .sourceFilesStableDuringVerification and .actorInputsUnchanged and .preActionRGBAndFeedbackMatched and .inverseTransformChecked and .normalizationMetres==8 and .episodes==2 and .fittingHistories==1 and .validationHistories==1 and .sourceDataSHA256==$sha' "$out/targets/receipt.json" > /dev/null
# t=10 is the pre-action pose after the first ten recorded actions. jq and
# od independently reconstruct the expected initial-relative displacement.
read -r forward sideways sine cosine mask < <(od -An -v -t f4 -j $((32+10*20)) -N 20 "$out/targets/targets.bin" | tr '\n' ' '; printf '\n')
jq -n --argjson f "$forward" --argjson y "$sideways" --argjson s "$sine" --argjson c "$cosine" --argjson mask "$mask" --slurpfile initial "$runs/expert-0/initial.json" --slurpfile decisions "$runs/expert-0/decisions.jsonl" '
    $initial[0].pose as $p | $decisions[9].state.pose as $q |
    ($q[0]-$p[0]) as $dx | ($q[1]-$p[1]) as $dy |
    (($p[2]|cos)*$dx+($p[2]|sin)*$dy)/8 as $expectedF |
    (($p[2]|cos)*$dy-($p[2]|sin)*$dx)/8 as $expectedY |
    ($q[2]-$p[2]) as $heading |
    ($f-$expectedF|fabs)<0.00001 and ($y-$expectedY|fabs)<0.00001 and ($s-($heading|sin)|fabs)<0.00001 and ($c-($heading|cos)|fabs)<0.00001 and $mask==1' | jq -e . > /dev/null
mkdir "$out/tampered"
for i in 0 1;do
    mkdir "$out/tampered/expert-$i"
    for file in decisions.jsonl trace.jsonl;do ln -s "$runs/expert-$i/$file" "$out/tampered/expert-$i/$file";done
    if (( i==0 ));then jq '.pose[0]+=.25' "$runs/expert-0/initial.json" > "$out/tampered/expert-0/initial.json"
    else ln -s "$runs/expert-$i/initial.json" "$out/tampered/expert-$i/initial.json";fi
done
if "$prepare" "$data" "$out/tampered" "$out/rejected" > "$out/rejected.log" 2>&1;then echo 'A mismatched initial pose was accepted.' >&2;exit 1;fi
rg -Fq 'pose target disagrees with physical trace' "$out/rejected.log"
[[ ! -e "$out/rejected" ]]
cp "$data" "$out/changed-data.bin"
byte="$(od -An -tu1 -j32 -N1 "$out/changed-data.bin")";printf -v replacement '\\%03o' "$((byte^1))"
printf '%b' "$replacement" | dd of="$out/changed-data.bin" bs=1 seek=32 conv=notrunc status=none
if "$prepare" "$out/changed-data.bin" "$runs" "$out/rejected-rgb" > "$out/rejected-rgb.log" 2>&1;then echo 'An unmatched RGB frame was accepted.' >&2;exit 1;fi
rg -Fq 'pose source RGB is not aligned to the dataset' "$out/rejected-rgb.log"
[[ ! -e "$out/rejected-rgb" ]]
sha256sum -c "$out/preparer.sha256" > "$out/preparer-integrity.log"
echo 'Prepared memory poses match an independent calculation and reject a mismatched trace.'
