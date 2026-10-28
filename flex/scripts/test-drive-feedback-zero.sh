#!/usr/bin/env bash
# Confirm the zero-row verifier rejects the original checkpoint.
set -euo pipefail
verify="$(realpath "${1:?Zero verifier required}")";original="$(realpath "${2:?Original checkpoint required}")";ablated="$(realpath "${3:?Ablated checkpoint required}")"
out="$(realpath -m "${4:?New output directory required}")";[[ ! -e "$out" ]];mkdir "$out"
"$verify" "$ablated" "$out/ablated.json"
sha="$(sha256sum "$ablated" | cut -d' ' -f1)"
jq -e --arg sha "$sha" '.passed and .weightsSHA256==$sha and .bytesChecked==15360 and .driveFeedbackValuesZero==5' "$out/ablated.json" > /dev/null
if "$verify" "$original" "$out/original.json" > "$out/original.log" 2>&1;then echo 'Nonzero drive feedback weights were accepted.' >&2;exit 1;fi
[[ ! -e "$out/original.json" ]]
echo 'Zero verifier accepts ablated weights and rejects nonzero feedback rows.'
