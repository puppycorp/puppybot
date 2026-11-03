#!/usr/bin/env bash
# Model size comparison: the small (128-value memory, 324k parameters) and large (256-value memory, wider
# encoder) categorical students, both from scratch on the same 640 exploring-teacher games, 40 epochs,
# SEEDS seeds each; every model is scored on the standard test and on levels 1-4. The large model trains at
# a 2e-4 learning rate: at the default 7e-4 it stays at the action prior (loss 1.82) from the first epoch.
# Usage: size.sh [ROOT] (default build/flex/sim/levels-v1, which must hold data-mix); PUPPYBOT_SIZE_SEEDS (default 3).
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$(realpath -m "${1:-$project/build/flex/sim/levels-v1}")"; here="$project/datasets/visual-control/chase-v1"; seeds="${PUPPYBOT_SIZE_SEEDS:-3}"
export LD_LIBRARY_PATH="$project/build/flex/rocm-runtime${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
cd "$project"
for size in small large; do
    flags=(); rate=(); [[ $size == small ]] || { flags=(--large-model); rate=(--learning-rate-micros 200); }
    [[ -f "$root/score-$size.json" ]] || PUPPYBOT_EVAL_FLAGS="--fetch ${flags[*]}" bash "$here/seeds.sh" "$root" "$size" "$seeds" --data "$root/data-mix/data.bin" --from-scratch --categorical --mirror-augment --carry-cue --epochs 40 --batch 2 --checkpoint-every 10 "${rate[@]}" "${flags[@]}"
    echo "$size standard $(jq -c .deliveriesPerMinute "$root/score-$size.json")"
    for ((s=0; s<seeds; s++)); do [[ -f "$root/eval-L4/score-$size-s$s.json" ]] || bash "$here/levels/score.sh" "$root" "$size-s$s" "$root/$size-s$s" "${flags[@]}" > /dev/null; done
    for L in 1 2 3 4; do echo "$size L$L $(jq -s -c 'map(.meanDeliveriesPerMinute) | {runs:., mean:(add/length)}' $(for ((s=0; s<seeds; s++)); do printf '%s ' "$root/eval-L$L/score-$size-s$s.json"; done))"; done
done
