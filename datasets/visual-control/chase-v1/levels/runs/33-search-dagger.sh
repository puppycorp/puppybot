#!/usr/bin/env bash
# Explore-kturn labels the more1-s0 student's own level-3 states. Mix those
# games with all kturn teacher games, keep coverage maps, and mask loops only
# in teacher-driven games. Evaluate with fresh seeds on training-layout
# selection scenes first; those layouts are not a held-out benchmark.
set -euo pipefail
cd /home/teppo/Work/my/puppybot
export PUPPYBOT_PROJECT=$PWD LD_LIBRARY_PATH=$PWD/build/flex/rocm-runtime
H=$PWD/datasets/visual-control/chase-v1; S=$H/levels
P=$PWD/build/flex/sim/levels-v2/pitch82; O=$P/search-dagger-4workers
available=$(df -B1 --output=avail "$P" | tail -1)
(( available >= 35 * 1024 * 1024 * 1024 )) || { echo 'At least 35 GiB free required before starting or resuming' >&2; exit 1; }
mkdir -p "$O"
inputs=(build/flex/control/control build/flex/control/simulator build/flex/control/compiler build/flex/control/trainer "$P/../../levels-v1/map-aggregate" "$P"/more1-s{0,1,2}/weights.bin "$P"/more1-s{0,1,2}/policy)
if [[ -f "$O/inputs.sha256" ]]; then sha256sum -c "$O/inputs.sha256"; else sha256sum "${inputs[@]}" > "$O/inputs.sha256"; fi
if [[ ! -f "$O/dagger-L3/data/data.bin" ]]; then
    PUPPYBOT_LEVELS=3 PUPPYBOT_CHASE_SHARDS=4 PUPPYBOT_CHASE_EPISODES=32 PUPPYBOT_CHASE_POLICY="$P/more1-s0" \
        nice -n 10 bash "$S/collect.sh" "$O" dagger 3100000 --camera-pitch 82 --record-map
fi
if [[ ${PUPPYBOT_DAGGER_STAGE:-all} == collect ]]; then
    sha256sum -c "$O/inputs.sha256"
    exit 0
fi
[[ ${PUPPYBOT_DAGGER_STAGE:-train} == train ]] || { echo 'PUPPYBOT_DAGGER_STAGE must be train or collect; use selection-pair.sh for evaluation' >&2; exit 1; }
# Stable ordering is essential: mask-stuck follows the aggregator's order.
shards=("$P"/kturn-L[0-5]/shard-? "$O"/dagger-L3/shard-?)
(( ${#shards[@]} == 52 )) || { echo 'Expected 48 teacher and 4 DAgger shards' >&2; exit 1; }
student_sha=$(sha256sum "$P/more1-s0/weights.bin" | cut -d' ' -f1)
python3 -I "$S/audit-shards.py" --student-weights "$student_sha" --student-model "$P/more1-s0" \
    --expect-teacher-shards 48 --expect-student-shards 4 --expect-games 1024 \
    --teacher "$P"/kturn-L[0-5]/shard-? --student "$O"/dagger-L3/shard-? > "$O/source-audit.json.tmp"
mv "$O/source-audit.json.tmp" "$O/source-audit.json"
sources=(); for shard in "${shards[@]}"; do sources+=("$shard/data.bin"); done
if [[ -f "$O/sources.sha256" ]]; then sha256sum -c "$O/sources.sha256"; else
    for shard in "${shards[@]}"; do sha256sum "$shard/data.bin" "$shard/map.bin"; done > "$O/sources.sha256"
fi
python3 -I - "${shards[@]}" <<'PY'
import json, sys
for shard in sys.argv[1:]:
    r = json.load(open(shard + '/report.json'))
    if max(r['seed'], 7800000) < min(r['seed'] + r['episodes'], 7800032):
        raise SystemExit(f'selection seed overlaps training shard: {shard}')
PY
if [[ ! -f "$O/data/mask.json" ]]; then
    [[ ! -e "$O/data" ]] || { echo 'Incomplete aggregate retained; inspect before retrying' >&2; exit 1; }
    "$P/../../levels-v1/map-aggregate" "$O/data" 300 0 "${sources[@]}"
    python3 -I "$S/mask-stuck.py" "$O/data/data.bin" --teacher-only "${shards[@]}" > "$O/data/mask.partial.json"
    mv "$O/data/mask.partial.json" "$O/data/mask.json"
fi
if [[ -f "$O/data.sha256" ]]; then sha256sum -c "$O/data.sha256"; else sha256sum "$O/data/data.bin" "$O/data/map.bin" > "$O/data.sha256"; fi
if [[ -f "$O/training-inputs.sha256" ]]; then
    sha256sum -c "$O/training-inputs.sha256"
else
    bash "$S/capture-training-inputs.sh" "$O/training-inputs.sha256" "$O/data"
fi
for s in 0 1 2; do
    available=$(df -B1 --output=avail "$P" | tail -1)
    (( available >= 10 * 1024 * 1024 * 1024 )) || { echo 'Less than 10 GiB free; stopping before the next model' >&2; exit 1; }
    model="$O/student-s$s"
    if [[ ! -f "$model/receipt.json" ]]; then
        [[ ! -e "$model" ]] || { echo "Incomplete model retained: $model" >&2; exit 1; }
        nice -n 10 build/flex/control/control train --output "$model" --seed $((3200000+s)) \
            --data "$O/data/data.bin" --memory-map "$O/data/map.bin" --transition-weight-one \
            --policy "$P/more1-s$s" --categorical --mirror-augment --carry-cue --epochs 8 --batch 2 --checkpoint-every 8 > "$model.log" 2>&1
    fi
done
sha256sum -c "$O/inputs.sha256"
sha256sum -c "$O/data.sha256"
sha256sum -c "$O/training-inputs.sha256"
