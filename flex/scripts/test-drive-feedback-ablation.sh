#!/usr/bin/env bash
# Confirm only the five drive-feedback rows change in a real checkpoint.
set -euo pipefail
ablate="$(realpath "${1:?Ablation binary required}")"
source="$(realpath "${2:?Large policy checkpoint required}")"
out="$(realpath -m "${3:?New output directory required}")";[[ ! -e "$out" ]];mkdir "$out"
"$ablate" "$source" "$out/weights.bin" "$out/report.json" > "$out/ablate.log" 2>&1
source_sha="$(sha256sum "$source" | cut -d' ' -f1)";weights_sha="$(sha256sum "$out/weights.bin" | cut -d' ' -f1)"
jq -e --arg source "$source_sha" --arg weights "$weights_sha" '.passed and .sourceSHA256==$source and .weightsSHA256==$weights and .tensor=="memory.weight_ih_T" and .driveFeedbackValuesZeroed==5 and .bytesZeroed==15360 and .nonzeroBytesChanged>0 and .contactFeedbackPreserved and .otherWeightsPreserved and (.trainingPerformed|not) and (.automaticPromotion|not)' "$out/report.json" > /dev/null
first="$(jq -er '.firstByte|select(type=="number" and .>=0 and floor==.)' "$out/report.json")";removed="$(jq -er '.bytesZeroed' "$out/report.json")";size="$(stat -c %s "$source")";[[ "$(stat -c %s "$out/weights.bin")" == "$size" && $((first+removed)) -le "$size" ]]
cmp -n "$first" "$source" "$out/weights.bin"
cmp -i "$((first+removed))" "$source" "$out/weights.bin"
dd if="$out/weights.bin" of="$out/zeroed.bin" bs=1 skip="$first" count="$removed" status=none
cmp -n "$removed" "$out/zeroed.bin" /dev/zero
if "$ablate" "$source" "$out/weights.bin" "$out/second.json" > "$out/overwrite.log" 2>&1;then echo 'Ablation overwrote an existing checkpoint.' >&2;exit 1;fi
if "$ablate" "$out/weights.bin" "$out/no-change.bin" "$out/no-change.json" > "$out/no-change.log" 2>&1;then echo 'Already ablated weights were accepted.' >&2;exit 1;fi
printf 'invalid\n' > "$out/invalid.bin"
if "$ablate" "$out/invalid.bin" "$out/invalid-out.bin" "$out/invalid-report.json" > "$out/invalid.log" 2>&1;then echo 'Malformed checkpoint was accepted.' >&2;exit 1;fi
echo 'Drive-feedback ablation changes only the intended checkpoint rows.'
