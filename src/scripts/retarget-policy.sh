#!/usr/bin/env bash
# Copy a trained policy so the current build can run it on CUDA or HIP (RDNA).
# Weights are unchanged; the inference binary and kernels are the current build's.
# Usage: retarget-policy.sh POLICY_DIR NEW_POLICY_DIR
set -euo pipefail
project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source_dir="${1:?Policy directory required}"; target="${2:?New policy directory required}"
receipt="$source_dir/receipt.json"
binary="$(jq -r '.binarySHA256' "$receipt")"
# The receipt names no binary, so pick the inference build from the recorded architecture.
codec="$(jq -r '.actionCodec' "$receipt")"; heat="$(jq -r '.heatmapActorFeatures // false' "$receipt")"; width="$(jq -r '.memoryWidth // 128' "$receipt")"; side="$(jq -r '.imageSide // 84' "$receipt")"
case "$codec/$heat/$width/$side" in
    continuous-tanh-v1/false/128/84) policy=policy ;;
    joint-seven-v1/false/128/84) policy=policy-categorical ;;
    joint-seven-phase-v1/false/128/84) policy=policy-categorical-phase ;;
    *) echo "Unsupported policy architecture $codec/$heat/$width/$side; retarget it by retraining." >&2; exit 1 ;;
esac
mkdir "$target"
cp "$source_dir/weights.bin" "$target/weights.bin"
cp "$project/build/flex/control/$policy" "$target/policy"
mkdir "$target/kernels"
for kernel in activation binary convolution join matmul; do
    for suffix in ptx hip; do cp "$project/build/flex/control/kernels/$kernel.$suffix" "$target/kernels/"; done
done
kernels="$(cd "$target/kernels" && sha256sum * | jq -R 'split("  ")|{(.[1]):.[0]}' | jq -s add)"
jq --arg binary "$(sha256sum "$target/policy" | cut -d' ' -f1)" --arg original "$binary" --argjson kernels "$kernels" \
    '.binarySHA256=$binary | .kernels=$kernels | .retargetedFromBinarySHA256=$original | .inferenceRuntime="Flexscript/Pup CUDA or HIP (RDNA)"' \
    "$receipt" > "$target/receipt.json"
echo "Retargeted $source_dir to $target ($policy)."
