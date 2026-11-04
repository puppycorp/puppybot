#!/usr/bin/env bash
# Small, isolated level-5 DAgger pilot for runs/34: one worker, two games,
# then verify teacher labels and their preservation through mixed aggregation.
# No part of this pilot enters the 1024-game training experiment.
set -euo pipefail
cd /home/teppo/Work/my/puppybot
export PUPPYBOT_PROJECT=$PWD LD_LIBRARY_PATH=$PWD/build/flex/rocm-runtime
H=$PWD/datasets/visual-control/chase-v1; S=$H/levels
P=$PWD/build/flex/sim/levels-v2/pitch82; B=$P/search-dagger-4workers; O=$P/search-dagger-l35-pilot
available=$(df -B1 --output=avail "$P" | tail -1)
(( available >= 35 * 1024 * 1024 * 1024 )) || { echo 'At least 35 GiB free required' >&2; exit 1; }
[[ ! -e "$O" ]] || { echo 'Pilot directory already exists; preserve and inspect it' >&2; exit 1; }
sha256sum -c "$B/training-inputs.sha256" > /dev/null
mkdir "$O"
inputs=(build/flex/control/control build/flex/control/simulator build/flex/control/compiler
        build/flex/rocm-runtime/libamdhip64.so "$P/../../levels-v1/map-aggregate"
        "$S/runs/34-level35-pilot.sh" "$S/collect.sh" "$H/collect.sh" "$S/audit-shards.py" "$S/audit-multi-shards.py"
        "$S/audit-student-labels.py" "$S/audit-mixed-students.py" "$S/mask-stuck.py" "$B/training-inputs.sha256")
for model in "$P/more1-s0" "$B/student-s0"; do
    inputs+=("$model/receipt.json" "$model/weights.bin" "$model/policy")
    [[ -d "$model/kernels" ]] || { echo "Missing kernels: $model" >&2; exit 1; }
    count=${#inputs[@]}
    while IFS= read -r -d '' file; do inputs+=("$file"); done < <(find "$model/kernels" -type f -print0 | sort -z)
    (( ${#inputs[@]} > count )) || { echo "Empty kernels: $model" >&2; exit 1; }
done
for layout in 13 15 17; do for ((variant=0; variant<16; variant++)); do
    scene=$PWD/build/flex/sim/expanded-rooms-v1/scenes/$layout/$variant
    inputs+=("$scene/case.json" "$scene/environment.bin" "$scene/layout.json")
done; done
sha256sum "${inputs[@]}" > "$O/inputs.sha256"
sha256sum -c "$O/inputs.sha256" > /dev/null
PUPPYBOT_LEVELS=5 PUPPYBOT_CHASE_SHARDS=1 PUPPYBOT_CHASE_EPISODES=2 PUPPYBOT_CHASE_VALIDATION=1 PUPPYBOT_CHASE_POLICY="$B/student-s0" \
    nice -n 10 bash "$S/collect.sh" "$O" pilot 5250000 --camera-pitch 82 --record-map
teacher=$P/kturn-L3/shard-0; old=$B/dagger-L3/shard-0; new=$O/pilot-L5/shard-0
python3 -I "$S/audit-multi-shards.py" --expect-games 50 --expect-teacher-shards 1 --expect-student-shards 2 \
    --teacher "$teacher" --student-group "$P/more1-s0" 3 "$old" --student-group "$B/student-s0" 5 "$new" > "$O/source-audit.json"
python3 -I "$S/audit-student-labels.py" "$new" > "$O/labels-audit.json"
"$P/../../levels-v1/map-aggregate" "$O/mixed" 300 0 "$teacher/data.bin" "$old/data.bin" "$new/data.bin"
python3 -I "$S/mask-stuck.py" "$O/mixed/data.bin" --teacher-only "$teacher" "$old" "$new" > "$O/mixed/mask.json"
python3 -I "$S/audit-mixed-students.py" "$O/mixed" 34 "$teacher" "$old" "$new" > "$O/preservation-audit.json"
sha256sum -c "$O/inputs.sha256" > /dev/null
echo "Level-5 pilot and mixed-label preservation passed: $O"
