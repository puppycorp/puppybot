#!/usr/bin/env bash
# Live simulation check for opt-in unsuccessful, densely labelled prefixes.
set -euo pipefail
runtime="${1:?Control runtime required}"
policy="${2:?Student policy required}"
scene="${3:?Scene directory required}"
output="${4:?New output directory required}"
runtime="$(cd "$runtime" && pwd)"
policy="$(cd "$policy" && pwd)"
scene="$(cd "$scene" && pwd)"
mkdir "$output"
output="$(cd "$output" && pwd)"
if [[ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}${SDL_VIDEODRIVER:-}" ]]; then
    display_runtime="${XDG_RUNTIME_DIR:-/run/user/$UID}"
    display_sockets=()
    if [[ -d "$display_runtime" && -O "$display_runtime" ]]; then
        for candidate in "$display_runtime"/wayland-*; do
            if [[ -S "$candidate" && -O "$candidate" ]]; then display_sockets+=("$candidate"); fi
        done
    fi
    if (( ${#display_sockets[@]} != 1 )); then
        echo 'Visual control needs a local renderer. Set WAYLAND_DISPLAY or DISPLAY from your desktop session.' >&2
        exit 2
    fi
    export XDG_RUNTIME_DIR="$display_runtime"
    export WAYLAND_DISPLAY="${display_sockets[0]##*/}"
fi
cd "$runtime"
control=./build/flex/control/control
extra=();width="$(jq -r '.memoryWidth // 128' "$policy/receipt.json")";if [[ "$width" == 256 ]];then extra+=(--large-model);else [[ "$width" == 128 ]];fi
args=(--policy "$policy" --scene "$scene" --episodes 2 --validation 1 --rollin 3 --rollin-min 3 --horizon 5 --seed 2026000 --label-rollin "${extra[@]}")
if "$control" correct "${args[@]}" --output "$output/strict-collection" > "$output/strict-collection.log" 2>&1;then echo 'Incomplete collection was published without opt-in.' >&2;exit 1;fi
[[ -f "$output/strict-collection/data.partial.bin" && ! -e "$output/strict-collection/data.bin" ]]
rg -Fq 'correction failed: all episodes and partial dataset retained' "$output/strict-collection.log"
"$control" correct "${args[@]}" --allow-incomplete --output "$output/runs" > "$output/collect.log" 2>&1
jq -e '.complete and .episodes==2 and .teacherCompleted==0 and .incompleteEpisodes==2 and .incompletePrefixesRetained and .studentRollinActions==6 and (.studentSuccessClaimed|not)' "$output/runs/report.json" > /dev/null
for episode in 0 1;do
    jq -e '.allowIncomplete and .recordedHorizon==5 and .terminationReason=="horizon" and .studentStartAction==0 and .studentActions==3 and .denseOracleLabels and (.studentCompletedBeforeHandoff|not)' "$output/runs/expert-$episode/supervision.json" > /dev/null
    jq -e '(.success|not) and .steps==5 and (.taskEventHint|not)' "$output/runs/expert-$episode/result.json" > /dev/null
done
"$control" pack-data --data "$output/runs/data.bin" --output "$output/packed" > "$output/pack.log" 2>&1
if "$control" verify-data --run "$output/runs" --data "$output/packed/data.bin" --output "$output/default-rejected" "${extra[@]}" > "$output/default-rejected.log" 2>&1;then echo 'Incomplete data was accepted without opt-in.' >&2;exit 1;fi
[[ ! -e "$output/default-rejected/result.json" ]]
"$control" verify-data --run "$output/runs" --data "$output/packed/data.bin" --output "$output/verified" --allow-incomplete "${extra[@]}" > "$output/verified.log" 2>&1
jq -e '.passed and .episodes==2 and .incompleteEpisodes==2 and .successfulEpisodes==0 and .studentRollinCommandsReplayed==6 and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .denseOracleLabels and .zeroPaddingChecked and .taskEventHintAbsent and (.incompleteEpisodesClaimedSuccessful|not)' "$output/verified/result.json" > /dev/null
"$control" correct --policy "$policy" --scene "$scene" --episodes 2 --validation 1 --rollin 5 --rollin-min 5 --horizon 5 --seed 2026000 --label-rollin --allow-incomplete --output "$output/student-only" "${extra[@]}" > "$output/student-only.log" 2>&1
jq -e '.complete and .teacherCompleted==0 and .incompleteEpisodes==2 and .studentRollinActions==10 and (.studentSuccessClaimed|not)' "$output/student-only/report.json" > /dev/null
"$control" verify-data --run "$output/student-only" --data "$output/student-only/data.bin" --output "$output/student-only-verified" --allow-incomplete "${extra[@]}" > "$output/student-only-verified.log" 2>&1
jq -e '.passed and .incompleteEpisodes==2 and .successfulEpisodes==0 and .studentRollinCommandsReplayed==10 and .studentRollinMaxAbsError==0 and .denseOracleLabels and .taskEventHintAbsent' "$output/student-only-verified/result.json" > /dev/null
perl -e 'use strict;use warnings;local $/;open my $f,"<",$ARGV[0] or die $!;binmode $f;my $data=<$f>;my $header=substr($data,0,32);substr($header,24,8,pack("Q<",6));binmode STDOUT;print $header;for my $i (0..1){my $base=32+$i*5*21224;print substr($data,$base,5*21168),"\0"x21168,substr($data,$base+5*21168,5*56),"\0"x56;}' "$output/student-only/data.bin" > "$output/padded-data.bin"
"$control" verify-data --run "$output/student-only" --data "$output/padded-data.bin" --output "$output/padded-verified" --allow-incomplete "${extra[@]}" > "$output/padded-verified.log" 2>&1
jq -e '.passed and .incompleteEpisodes==2 and .studentRollinCommandsReplayed==10 and .zeroPaddingChecked and .taskEventHintAbsent' "$output/padded-verified/result.json" > /dev/null
cp -a --reflink=auto "$output/student-only" "$output/truncated-runs"
for episode in 0 1;do
    jq '.recordedHorizon=6 | .terminationReason="oracle-unavailable"' "$output/truncated-runs/expert-$episode/supervision.json" > "$output/truncated-$episode.json"
    mv "$output/truncated-$episode.json" "$output/truncated-runs/expert-$episode/supervision.json"
done
"$control" verify-data --run "$output/truncated-runs" --data "$output/student-only/data.bin" --output "$output/truncated-verified" --allow-incomplete "${extra[@]}" > "$output/truncated-verified.log" 2>&1
jq -e '.passed and .incompleteEpisodes==2 and .studentRollinCommandsReplayed==10 and (.incompleteReasonIndependentlyVerified|not) and (.incompleteEpisodesClaimedSuccessful|not)' "$output/truncated-verified/result.json" > /dev/null
cp -a --reflink=auto "$output/runs" "$output/altered-runs"
jq '.studentCompletedBeforeHandoff=true' "$output/altered-runs/expert-0/supervision.json" > "$output/altered.json"
mv "$output/altered.json" "$output/altered-runs/expert-0/supervision.json"
if "$control" verify-data --run "$output/altered-runs" --data "$output/packed/data.bin" --output "$output/altered-rejected" --allow-incomplete "${extra[@]}" > "$output/altered-rejected.log" 2>&1;then echo 'False student success metadata was accepted.' >&2;exit 1;fi
[[ ! -e "$output/altered-rejected/result.json" ]]
cp --reflink=auto "$output/packed/data.bin" "$output/altered-data.bin"
printf '\000\000\100\277' | dd of="$output/altered-data.bin" bs=1 seek=$((32+5*21168+28)) conv=notrunc status=none
if "$control" verify-data --run "$output/runs" --data "$output/altered-data.bin" --output "$output/label-rejected" --allow-incomplete "${extra[@]}" > "$output/label-rejected.log" 2>&1;then echo 'Altered oracle label was accepted.' >&2;exit 1;fi
[[ ! -e "$output/label-rejected/result.json" ]]
rg -Fq 'supervised correction differs from the oracle label' "$output/label-rejected.log"
if "$control" correct --policy "$policy" --scene "$scene" --episodes 2 --validation 1 --rollin 3 --rollin-min 3 --horizon 5 --seed 2026000 --allow-incomplete --output "$output/no-dense-rejected" "${extra[@]}" > "$output/no-dense.log" 2>&1;then echo 'Incomplete correction without dense labels was accepted.' >&2;exit 1;fi
rg -Fq 'incomplete corrections require dense labels' "$output/no-dense.log"
"$control" train --data "$output/packed/data.bin" --output "$output/trained" --from-scratch --categorical --epochs 1 --batch 1 --seed 7 --learning-rate-micros 100 > "$output/train.log" 2>&1
jq -e '.epochs==1 and .actionCodec=="joint-seven-v1" and (.taskFeedback|not)' "$output/trained/receipt.json" > /dev/null
if cmp -s "$output/trained/initial.bin" "$output/trained/first-after.bin";then echo 'Training on the audited incomplete data made no update.' >&2;exit 1;fi
echo 'Incomplete prefixes require explicit opt-in, replay exactly, reject tampering and train without task inputs.'
