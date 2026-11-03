#!/usr/bin/env bash
# Package a trained model's saved epoch checkpoint as its own policy, so it can be played and scored.
# Usage: checkpoint.sh MODEL_DIR EPOCH NEW_POLICY_DIR; epoch 0 is the untrained initial.bin, others epoch-EPOCH.bin.
set -euo pipefail
model="${1:?Model directory required}"; epoch="${2:?Epoch required}"; target="${3:?New policy directory required}"
source="$model/epoch-$epoch.bin"; [[ $epoch != 0 ]] || source="$model/initial.bin"
[[ -f "$source" && ! -e "$target" ]]
mkdir -p "$target/kernels"
cp "$source" "$target/weights.bin"
cp "$model/policy" "$target/policy"
cp "$model"/kernels/* "$target/kernels/"
jq --arg sha "$(sha256sum "$target/weights.bin" | cut -d' ' -f1)" --argjson epoch "$epoch" \
    '.checkpointSourceWeightsSHA256=.weightsSHA256 | .weightsSHA256=$sha | .checkpointSHA256=$sha | .checkpointEpoch=$epoch' \
    "$model/receipt.json" > "$target/receipt.json"
