#!/usr/bin/env bash
# Reproduce the search-level experiments of the README in order; finished steps (existing outputs) are skipped.
# Usage: run.sh [ROOT] (default build/flex/sim/levels-v1). Needs the fetch-v2 models for the baseline and
# build/flex/sim/chase-v1/train-d5-agg as the starting student.
# Written for the level numbering before 2 Nov 2026 (4 other room, 5 doorway drill); the current code swaps them.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$(realpath -m "${1:-$project/build/flex/sim/levels-v1}")"; here="$project/datasets/visual-control/chase-v1"
export LD_LIBRARY_PATH="$project/build/flex/rocm-runtime${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
cd "$project"; mkdir -p "$root"
score() { [[ -f "$root/eval-L4/score-$1.json" ]] || bash "$here/levels/score.sh" "$root" "$@"; }
# 1. Baseline: camera-sighting teacher and the fetch-v2 students.
score teacher teacher
for p in far-512-s0 far-512-s1 far-512-s2 base-s0 base-s1 base-s2; do score "$p" "build/flex/sim/fetch-v2/$p"; done
# 2. Exploring teacher.
score explore4 teacher --explore-teacher
[[ -f "$root/eval/score-explore-teacher.json" ]] || bash "$here/evaluate.sh" "$root/eval" explore-teacher teacher --fetch --explore-teacher
# 3. 128 teacher games each of L0-L4, merged in level then shard order; 3 students, 30 epochs.
PUPPYBOT_CHASE_SHARDS=8 PUPPYBOT_CHASE_EPISODES=16 bash "$here/levels/collect.sh" "$root" data 910000
[[ -f "$root/data-mix/data.bin" ]] || "$root/data-L4/aggregate" "$root/data-mix" 300 0 $(for L in 0 1 2 3 4; do for k in 0 1 2 3 4 5 6 7; do printf '%s ' "$root/data-L$L/shard-$k/data.bin"; done; done)
[[ -f "$root/score-mix.json" ]] || PUPPYBOT_EVAL_FLAGS=--fetch bash "$here/seeds.sh" "$root" mix 3 --data "$root/data-mix/data.bin" --policy build/flex/sim/chase-v1/train-d5-agg --categorical --mirror-augment --carry-cue --epochs 30 --batch 2 --checkpoint-every 10
for s in 0 1 2; do score "mix-s$s" "$root/mix-s$s"; done
# 4. DAgger round 1: mix-s2 drives 128 games per level, the exploring teacher labels every step. Training reads at
#    most 1024 games, so the round keeps teacher shards 0-3 (64 games) and every student-driven game per level.
PUPPYBOT_CHASE_POLICY="$root/mix-s2" PUPPYBOT_CHASE_SHARDS=4 PUPPYBOT_CHASE_EPISODES=32 PUPPYBOT_CHASE_VALIDATION=4 bash "$here/levels/collect.sh" "$root" dagger 960000
[[ -f "$root/data-agg1/data.bin" ]] || "$root/data-L4/aggregate" "$root/data-agg1" 300 0 $(for L in 0 1 2 3 4; do for k in 0 1 2 3; do printf '%s ' "$root/data-L$L/shard-$k/data.bin"; done; for k in 0 1 2 3; do printf '%s ' "$root/dagger-L$L/shard-$k/data.bin"; done; done)
[[ -f "$root/score-agg1.json" ]] || PUPPYBOT_EVAL_FLAGS=--fetch bash "$here/seeds.sh" "$root" agg1 3 --data "$root/data-agg1/data.bin" --policy "$root/mix-s2" --categorical --mirror-augment --carry-cue --epochs 15 --batch 2 --checkpoint-every 5
for s in 0 1 2; do score "agg1-s$s" "$root/agg1-s$s"; done
# 5. Manifest: every dataset and model checksum; compare with levels/manifest.json from the original run.
for d in "$root"/data-L? "$root"/dagger-L? "$root"/data-mix "$root"/data-agg1; do
    data="$d/data.bin"; [[ -f "$data" ]] || data="$d/data/data.bin"
    jq -n --arg name "$(basename "$d")" --arg sha "$(sha256sum "$data" | cut -d' ' -f1)" --argjson bytes "$(stat -c %s "$data")" '{name:$name,dataSHA256:$sha,bytes:$bytes}'
done | jq -s --argjson models "$(for m in "$root"/mix-s? "$root"/agg1-s?; do jq -n --arg name "$(basename "$m")" --arg sha "$(sha256sum "$m/weights.bin" | cut -d' ' -f1)" '{name:$name,weightsSHA256:$sha}'; done | jq -s .)" '{datasets:.,models:$models}' > "$root/manifest.json"
echo "Manifest: $root/manifest.json"
