#!/usr/bin/env bash
# Matched L4 substitution experiment. Run stages pilot, collect, prepare, train
# in order; GPU stages must run alone. Nothing here is a held-out evaluation.
# Both models continue the same mixed student with the same seed and settings.
# Treatment replaces L4 teacher shards 0..3 in place with student-driven L4.
set -euo pipefail
if [[ ${1:-} != --clean ]]; then
    exec env -i PATH=/usr/bin:/bin HOME="$HOME" bash "$0" --clean "$@"
fi
shift
stage=${1:?Expected pilot, collect, prepare or train}
[[ $# == 1 && $stage =~ ^(pilot|collect|prepare|train)$ ]] || exit 1
cd /home/teppo/Work/my/puppybot
export PUPPYBOT_PROJECT=$PWD LD_LIBRARY_PATH=$PWD/build/flex/rocm-runtime
H=$PWD/datasets/visual-control/chase-v1; S=$H/levels
P=$PWD/build/flex/sim/levels-v2/pitch82; B=$P/search-dagger-4workers
M=$P/search-dagger-l35-4workers; T=$P/search-dagger-l4-matched-pilot; O=$P/search-dagger-l4-matched
exec 9>> "$P/.l4-matched.lock"
flock -n 9 || { echo 'Another matched experiment stage is running' >&2; exit 1; }
available=$(df -B1 --output=avail "$P" | tail -1)
(( available >= 35 * 1024 * 1024 * 1024 )) || { echo 'At least 35 GiB free required' >&2; exit 1; }
sha256sum -c "$M/training-inputs.sha256" > /dev/null
jq -e '.status == "passed" and .games == 1024' "$M/source-audit.json" > /dev/null

# Capture before any collection, including the exact checkpoint and training
# tools. Original data and previous full input manifest are pinned too.
inputs=(build/flex/control/control build/flex/control/simulator build/flex/control/compiler build/flex/control/trainer
        build/flex/rocm-runtime/libamdhip64.so "$P/../../levels-v1/map-aggregate"
        "$S/runs/35-l4-matched.sh" "$S/collect.sh" "$H/collect.sh" "$H/aggregate.flex"
        "$S/audit-shards.py" "$S/audit-multi-shards.py" "$S/audit-student-labels.py"
        "$S/audit-mixed-students.py" "$S/audit-matched-l4.py" "$S/audit-matched-training.py" "$S/mask-stuck.py"
        "$M/training-inputs.sha256" "$M/source-audit.json" "$M/data/data.bin" "$M/data/map.bin")
for model in "$P/more1-s0" "$B/student-s0" "$M/student-s0"; do
    inputs+=("$model/receipt.json" "$model/weights.bin" "$model/policy")
    count=${#inputs[@]}
    while IFS= read -r -d '' file; do inputs+=("$file"); done < <(find "$model/kernels" -type f -print0 | sort -z)
    (( ${#inputs[@]} > count )) || { echo "Missing kernels: $model" >&2; exit 1; }
done
count=${#inputs[@]}
while IFS= read -r -d '' file; do inputs+=("$file"); done < <(find build/flex/control/kernels -type f -print0 | sort -z)
(( ${#inputs[@]} > count )) || { echo 'Missing training kernels' >&2; exit 1; }
for layout in 13 15 17; do for ((variant=0; variant<16; variant++)); do
    scene=$PWD/build/flex/sim/expanded-rooms-v1/scenes/$layout/$variant
    inputs+=("$scene/case.json" "$scene/environment.bin" "$scene/layout.json")
done; done
if [[ $stage == pilot ]]; then
    [[ ! -e "$T" ]] || { echo 'Pilot exists; preserve and inspect it' >&2; exit 1; }
    mkdir "$T"
    sha256sum "${inputs[@]}" > "$T/inputs.sha256"
    sha256sum -c "$T/inputs.sha256" > /dev/null
    PUPPYBOT_LEVELS=4 PUPPYBOT_CHASE_SHARDS=1 PUPPYBOT_CHASE_EPISODES=2 PUPPYBOT_CHASE_VALIDATION=1 PUPPYBOT_CHASE_POLICY="$M/student-s0" \
        nice -n 10 bash "$S/collect.sh" "$T" pilot 6000000 --camera-pitch 82 --record-map
    teacher=$P/kturn-L4/shard-4; old=$B/dagger-L3/shard-0; new=$T/pilot-L4/shard-0
    python3 -I "$S/audit-multi-shards.py" --expect-games 66 --expect-teacher-shards 1 --expect-student-shards 2 \
        --teacher "$teacher" --student-group "$P/more1-s0" 3 "$old" --student-group "$M/student-s0" 4 "$new" > "$T/source-audit.json"
    python3 -I "$S/audit-student-labels.py" "$new" > "$T/labels-audit.json"
    jq -e '.status == "passed" and .games == 2 and .teacherStudentDisagreementSteps > 0' "$T/labels-audit.json" > /dev/null
    "$P/../../levels-v1/map-aggregate" "$T/mixed" 300 0 "$teacher/data.bin" "$old/data.bin" "$new/data.bin"
    python3 -I "$S/mask-stuck.py" "$T/mixed/data.bin" --teacher-only "$teacher" "$old" "$new" > "$T/mixed/mask.json"
    python3 -I "$S/audit-mixed-students.py" "$T/mixed" 34 "$teacher" "$old" "$new" > "$T/preservation-audit.json"
    sha256sum -c "$T/inputs.sha256" > /dev/null
    sha256sum "$T/source-audit.json" "$T/labels-audit.json" "$T/preservation-audit.json" > "$T/pilot-audits.sha256"
    exit 0
fi
for file in inputs.sha256 source-audit.json labels-audit.json preservation-audit.json pilot-audits.sha256; do
    [[ -f "$T/$file" ]] || { echo "Pilot missing $file" >&2; exit 1; }
done
sha256sum -c "$T/inputs.sha256" > /dev/null
sha256sum -c "$T/pilot-audits.sha256" > /dev/null
jq -e '.status == "passed" and .games == 66' "$T/source-audit.json" > /dev/null
jq -e '.status == "passed" and .studentGames == 34' "$T/preservation-audit.json" > /dev/null
if [[ $stage == collect ]]; then
    [[ ! -e "$O" ]] || { echo 'Experiment exists; preserve and inspect it' >&2; exit 1; }
    mkdir "$O"
    sha256sum "${inputs[@]}" "$T/inputs.sha256" "$T/pilot-audits.sha256" > "$O/inputs.sha256"
    sha256sum -c "$O/inputs.sha256" > /dev/null
    PUPPYBOT_LEVELS=4 PUPPYBOT_CHASE_SHARDS=4 PUPPYBOT_CHASE_EPISODES=32 PUPPYBOT_CHASE_VALIDATION=2 PUPPYBOT_CHASE_POLICY="$M/student-s0" \
        nice -n 10 bash "$S/collect.sh" "$O" dagger 6400000 --camera-pitch 82 --record-map
    sha256sum -c "$O/inputs.sha256" > /dev/null
    exit 0
fi
sha256sum -c "$O/inputs.sha256" > /dev/null
teacher=(); old=(); replacement=()
for level in 0 1 2 3; do for shard in 0 1 2 3 4 5; do
    p=$P/kturn-L$level/shard-$shard; teacher+=("$p"); old+=("$p"); replacement+=("$p")
done; done
for level in 4 5; do for shard in 0 1 2 3 4 5 6 7; do
    p=$P/kturn-L$level/shard-$shard; old+=("$p")
    if [[ $level == 4 && $shard -lt 4 ]]; then replacement+=("$O/dagger-L4/shard-$shard"); else teacher+=("$p"); replacement+=("$p"); fi
done; done
l3=("$B"/dagger-L3/shard-{0,1,2,3}); l5=("$M"/dagger-L5/shard-{0,1,2,3}); l4=("$O"/dagger-L4/shard-{0,1,2,3})
old+=("${l3[@]}" "${l5[@]}"); replacement+=("${l3[@]}" "${l5[@]}")
(( ${#old[@]} == 48 && ${#replacement[@]} == 48 && ${#teacher[@]} == 36 )) || exit 1
if [[ $stage == prepare ]]; then
    for path in data training-inputs.sha256 source-audit.json l4-labels-audit.json sources.sha256 student-preservation.json matched-audit.json prepared.sha256; do
        [[ ! -e "$O/$path" ]] || { echo "Prepared or partial output retained: $O/$path" >&2; exit 1; }
    done
    python3 -I "$S/audit-multi-shards.py" --expect-games 1024 --expect-teacher-shards 36 --expect-student-shards 12 \
        --teacher "${teacher[@]}" --student-group "$P/more1-s0" 3 "${l3[@]}" --student-group "$B/student-s0" 5 "${l5[@]}" \
        --student-group "$M/student-s0" 4 "${l4[@]}" > "$O/source-audit.json"
    jq -e '.status == "passed" and .gamesBySourceLevel == {"teacher-L0":96,"teacher-L1":96,"teacher-L2":96,"teacher-L3":96,"teacher-L4":128,"teacher-L5":128,"student-L3":128,"student-L4":128,"student-L5":128}' "$O/source-audit.json" > /dev/null
    python3 -I "$S/audit-student-labels.py" "${l4[@]}" > "$O/l4-labels-audit.json"
    jq -e '.status == "passed" and .games == 128 and .teacherStudentDisagreementSteps > 0' "$O/l4-labels-audit.json" > /dev/null
    # Mask recomputation reads these records. Pin them before and after use.
    for shard in "${replacement[@]}"; do
        sha256sum "$shard/report.json" "$shard/data.bin" "$shard/map.bin"
        while IFS= read -r -d '' file; do sha256sum "$file"; done < <(find "$shard" -path '*/expert-*/*' \( -name decisions.jsonl -o -name chase.jsonl -o -path '*/scene/case.json' \) -type f -print0 | sort -z)
    done > "$O/sources.sha256"
    sources=(); for shard in "${replacement[@]}"; do sources+=("$shard/data.bin"); done
    "$P/../../levels-v1/map-aggregate" "$O/data" 300 0 "${sources[@]}"
    python3 -I "$S/mask-stuck.py" "$O/data/data.bin" --teacher-only "${replacement[@]}" > "$O/data/mask.json"
    python3 -I "$S/audit-mixed-students.py" "$O/data" 384 "${replacement[@]}" > "$O/student-preservation.json"
    pairs=(); for ((i=0; i<48; i++)); do pairs+=("${old[i]}" "${replacement[i]}"); done
    python3 -I "$S/audit-matched-l4.py" "$M/data" "$O/data" "${pairs[@]}" > "$O/matched-audit.json"
    jq -e '.status == "passed" and .games == 1024 and .unchangedGames == 896 and .replacedGames == 128' "$O/matched-audit.json" > /dev/null
    sha256sum -c "$O/sources.sha256" > /dev/null
    sha256sum -c "$O/inputs.sha256" > /dev/null
    sha256sum "$O/source-audit.json" "$O/l4-labels-audit.json" "$O/student-preservation.json" "$O/matched-audit.json" "$O/data/mask.json" "$O/data/data.bin" "$O/data/map.bin" > "$O/prepared.sha256"
    cat "$O/inputs.sha256" "$O/sources.sha256" "$O/prepared.sha256" > "$O/training-inputs.sha256"
    sha256sum -c "$O/training-inputs.sha256" > /dev/null
    exit 0
fi
sha256sum -c "$O/training-inputs.sha256" > /dev/null
for arm in control treatment; do
    available=$(df -B1 --output=avail "$P" | tail -1)
    (( available >= 32 * 1024 * 1024 * 1024 )) || { echo 'Less than 32 GiB free; stopping before next model' >&2; exit 1; }
    model=$O/$arm-s0; data=$M/data; [[ $arm != treatment ]] || data=$O/data
    if [[ ! -f "$model/receipt.json" ]]; then
        [[ ! -e "$model" ]] || { echo "Incomplete model retained: $model" >&2; exit 1; }
        [[ ! -e "$model.log" ]] || { echo "Existing model log retained: $model.log" >&2; exit 1; }
        nice -n 10 build/flex/control/control train --output "$model" --seed 6500000 --data "$data/data.bin" --memory-map "$data/map.bin" \
            --transition-weight-one --policy "$M/student-s0" --categorical --mirror-augment --carry-cue --epochs 8 --batch 2 --checkpoint-every 8 > "$model.log" 2>&1
    fi
    data_sha=$(sha256sum "$data/data.bin" | cut -d' ' -f1); map_sha=$(sha256sum "$data/map.bin" | cut -d' ' -f1)
    initial_sha=$(sha256sum "$M/student-s0/weights.bin" | cut -d' ' -f1)
    jq -e --arg d "$data_sha" --arg m "$map_sha" --arg i "$initial_sha" \
        '.dataSHA256 == $d and .memoryMapTargetsSHA256 == $m and .initialWeightsSHA256 == $i and .seed == 6500000 and .epochs == 8 and .batch == 2 and .checkpointEveryEpochs == 8 and .sequenceMirrorAugmentation == true and .carryCue == true and .speedTransitionLossWeight == 1' "$model/receipt.json" > /dev/null
    sha256sum -c "$O/training-inputs.sha256" > /dev/null
done
[[ ! -e "$O/training-match.json" ]] || { echo 'Existing training audit retained' >&2; exit 1; }
python3 -I "$S/audit-matched-training.py" "$M/student-s0" "$O/control-s0" "$O/treatment-s0" > "$O/training-match.json"
