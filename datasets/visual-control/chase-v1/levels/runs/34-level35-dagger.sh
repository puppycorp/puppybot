#!/usr/bin/env bash
# Selection experiment: ask explore-kturn to label student-s0's own level-5
# states, while retaining all previous level-3 DAgger games. To stay within
# the 1024-game limit, remove 32 teacher games from each of levels 0-3.
# That removal is a confound: this is not an isolated test of L5 data alone.
# Existing L4 and L5 teacher games are retained. New data and checkpoints go
# into a separate directory; no existing experiments are overwritten.
#
# Usage: PUPPYBOT_DAGGER_STAGE=collect|train bash .../34-level35-dagger.sh
# Collect and train are separate so the completed collection can be audited
# before training. Run one GPU task at a time. Selection is a later, separate
# step and is not a held-out evaluation.
set -euo pipefail
cd /home/teppo/Work/my/puppybot
export PUPPYBOT_PROJECT=$PWD LD_LIBRARY_PATH=$PWD/build/flex/rocm-runtime
stage=${PUPPYBOT_DAGGER_STAGE:?Set PUPPYBOT_DAGGER_STAGE to collect or train}
[[ $stage == collect || $stage == train ]] || { echo 'Stage must be collect or train' >&2; exit 1; }
H=$PWD/datasets/visual-control/chase-v1; S=$H/levels
P=$PWD/build/flex/sim/levels-v2/pitch82; B=$P/search-dagger-4workers; T=$P/search-dagger-l35-pilot; O=$P/search-dagger-l35-4workers
available=$(df -B1 --output=avail "$P" | tail -1)
(( available >= 35 * 1024 * 1024 * 1024 )) || { echo 'At least 35 GiB free required before starting or resuming' >&2; exit 1; }
[[ -f "$B/source-audit.json" && -f "$B/training-inputs.sha256" ]] || { echo 'Missing previous experiment audit or manifest' >&2; exit 1; }
sha256sum -c "$B/training-inputs.sha256" > /dev/null
for report in inputs.sha256 source-audit.json labels-audit.json preservation-audit.json; do
    [[ -f "$T/$report" ]] || { echo "Run and audit the separate level-5 pilot first: $T/$report" >&2; exit 1; }
done
sha256sum -c "$T/inputs.sha256" > /dev/null
jq -e '.status == "passed" and .games == 50' "$T/source-audit.json" > /dev/null
jq -e '.status == "passed" and .games == 2 and .teacherStudentDisagreementSteps > 0' "$T/labels-audit.json" > /dev/null
jq -e '.status == "passed" and .studentGames == 34' "$T/preservation-audit.json" > /dev/null
mkdir -p "$O"
if [[ ! -f "$O/inputs.sha256" ]]; then
    [[ ! -e "$O/dagger-L5" && ! -e "$O/data" && ! -e "$O/student-s0" ]] || { echo 'Refusing to create a manifest after work started' >&2; exit 1; }
    inputs=(build/flex/control/control build/flex/control/simulator build/flex/control/compiler build/flex/control/trainer
            build/flex/rocm-runtime/libamdhip64.so "$P/../../levels-v1/map-aggregate"
            "$S/runs/34-level35-dagger.sh" "$S/runs/34-level35-pilot.sh" "$S/collect.sh" "$H/collect.sh" "$S/audit-shards.py" "$S/audit-multi-shards.py" "$S/audit-student-labels.py" "$S/audit-mixed-students.py" "$S/mask-stuck.py"
            "$B/source-audit.json" "$B/training-inputs.sha256" "$T/inputs.sha256" "$T/source-audit.json" "$T/labels-audit.json" "$T/preservation-audit.json")
    for model in "$P/more1-s0" "$B"/student-s{0,1,2}; do
        inputs+=("$model/receipt.json" "$model/weights.bin" "$model/policy")
        [[ -d "$model/kernels" ]] || { echo "Missing kernels: $model" >&2; exit 1; }
        count=${#inputs[@]}
        while IFS= read -r -d '' file; do inputs+=("$file"); done < <(find "$model/kernels" -type f -print0 | sort -z)
        (( ${#inputs[@]} > count )) || { echo "Empty kernels: $model" >&2; exit 1; }
    done
    count=${#inputs[@]}
    while IFS= read -r -d '' file; do inputs+=("$file"); done < <(find build/flex/control/kernels -type f -print0 | sort -z)
    (( ${#inputs[@]} > count )) || { echo 'Missing training kernels' >&2; exit 1; }
    for layout in 13 15 17; do for ((variant=0; variant<16; variant++)); do
        scene=$PWD/build/flex/sim/expanded-rooms-v1/scenes/$layout/$variant
        inputs+=("$scene/case.json" "$scene/environment.bin" "$scene/layout.json")
    done; done
    temp=$(mktemp "$O/inputs.tmp.XXXXXX"); trap 'rm -f "$temp"' EXIT
    sha256sum "${inputs[@]}" > "$temp"; sha256sum -c "$temp" > /dev/null; ln "$temp" "$O/inputs.sha256"
fi
sha256sum -c "$O/inputs.sha256" > /dev/null
if [[ ! -f "$O/dagger-L5/data/data.bin" ]]; then
    [[ $stage == collect ]] || { echo 'Complete the separate collection stage first' >&2; exit 1; }
    [[ ! -e "$O/dagger-L5" ]] || { echo 'Incomplete collection retained; inspect before retrying' >&2; exit 1; }
    PUPPYBOT_LEVELS=5 PUPPYBOT_CHASE_SHARDS=4 PUPPYBOT_CHASE_EPISODES=32 PUPPYBOT_CHASE_POLICY="$B/student-s0" \
        nice -n 10 bash "$S/collect.sh" "$O" dagger 4300000 --camera-pitch 82 --record-map
fi
if [[ $stage == collect ]]; then sha256sum -c "$O/inputs.sha256" > /dev/null; exit 0; fi

teacher=()
for level in 0 1 2 3; do for shard in 0 1 2 3 4 5; do teacher+=("$P/kturn-L$level/shard-$shard"); done; done
for level in 4 5; do for shard in 0 1 2 3 4 5 6 7; do teacher+=("$P/kturn-L$level/shard-$shard"); done; done
l3=("$B"/dagger-L3/shard-{0,1,2,3}); l5=("$O"/dagger-L5/shard-{0,1,2,3})
shards=("${teacher[@]}" "${l3[@]}" "${l5[@]}")
(( ${#teacher[@]} == 40 && ${#l3[@]} == 4 && ${#l5[@]} == 4 )) || { echo 'Wrong source composition' >&2; exit 1; }
if [[ -f "$O/sources.sha256" ]]; then sha256sum -c "$O/sources.sha256" > /dev/null; fi
python3 -I "$S/audit-multi-shards.py" --expect-games 1024 --expect-teacher-shards 40 --expect-student-shards 8 \
    --teacher "${teacher[@]}" --student-group "$P/more1-s0" 3 "${l3[@]}" \
    --student-group "$B/student-s0" 5 "${l5[@]}" > "$O/source-audit.json.tmp"
jq -e '.status == "passed" and .gamesBySourceLevel == {"teacher-L0":96,"teacher-L1":96,"teacher-L2":96,"teacher-L3":96,"teacher-L4":256,"teacher-L5":128,"student-L3":128,"student-L5":128}' "$O/source-audit.json.tmp" > /dev/null
mv "$O/source-audit.json.tmp" "$O/source-audit.json"
python3 -I "$S/audit-student-labels.py" "${l3[@]}" > "$O/l3-labels-audit.json.tmp"
python3 -I "$S/audit-student-labels.py" "${l5[@]}" > "$O/l5-labels-audit.json.tmp"
jq -e -s 'length == 2 and all(.[]; .status == "passed" and .games == 128 and .teacherStudentDisagreementSteps > 0)' "$O/l3-labels-audit.json.tmp" "$O/l5-labels-audit.json.tmp" > /dev/null
mv "$O/l3-labels-audit.json.tmp" "$O/l3-labels-audit.json"
mv "$O/l5-labels-audit.json.tmp" "$O/l5-labels-audit.json"
if [[ ! -f "$O/sources.sha256" ]]; then
    temp=$(mktemp "$O/sources.tmp.XXXXXX"); trap 'rm -f "$temp"' EXIT
    for shard in "${shards[@]}"; do sha256sum "$shard/report.json" "$shard/data.bin" "$shard/map.bin"; done > "$temp"
    sha256sum -c "$temp" > /dev/null; ln "$temp" "$O/sources.sha256"
fi
if [[ ! -f "$O/data/mask.json" ]]; then
    [[ ! -e "$O/data" ]] || { echo 'Incomplete aggregate retained; inspect before retrying' >&2; exit 1; }
    sources=(); for shard in "${shards[@]}"; do sources+=("$shard/data.bin"); done
    "$P/../../levels-v1/map-aggregate" "$O/data" 300 0 "${sources[@]}"
    python3 -I "$S/mask-stuck.py" "$O/data/data.bin" --teacher-only "${shards[@]}" > "$O/data/mask.partial.json"
    mv "$O/data/mask.partial.json" "$O/data/mask.json"
fi
python3 -I "$S/audit-mixed-students.py" "$O/data" 256 "${shards[@]}" > "$O/preservation-audit.json.tmp"
mv "$O/preservation-audit.json.tmp" "$O/preservation-audit.json"
if [[ -f "$O/audits.sha256" ]]; then sha256sum -c "$O/audits.sha256" > /dev/null; else
    sha256sum "$O/source-audit.json" "$O/l3-labels-audit.json" "$O/l5-labels-audit.json" "$O/preservation-audit.json" > "$O/audits.sha256"
fi
if [[ -f "$O/data.sha256" ]]; then sha256sum -c "$O/data.sha256" > /dev/null; else sha256sum "$O/data/data.bin" "$O/data/map.bin" > "$O/data.sha256"; fi
if [[ -f "$O/training-inputs.sha256" ]]; then
    sha256sum -c "$O/training-inputs.sha256" > /dev/null
else
    # The collection manifest already pins every source model, binary and kernel.
    temp=$(mktemp "$O/training-inputs.tmp.XXXXXX"); trap 'rm -f "$temp"' EXIT
    cat "$O/inputs.sha256" "$O/sources.sha256" "$O/audits.sha256" "$O/data.sha256" > "$temp"
    sha256sum -c "$temp" > /dev/null; ln "$temp" "$O/training-inputs.sha256"
fi
for seed in 0 1 2; do
    available=$(df -B1 --output=avail "$P" | tail -1)
    (( available >= 32 * 1024 * 1024 * 1024 )) || { echo 'Less than 32 GiB free; stopping before next model' >&2; exit 1; }
    model=$O/student-s$seed
    if [[ ! -f "$model/receipt.json" ]]; then
        [[ ! -e "$model" ]] || { echo "Incomplete model retained: $model" >&2; exit 1; }
        nice -n 10 build/flex/control/control train --output "$model" --seed $((4400000+seed)) \
            --data "$O/data/data.bin" --memory-map "$O/data/map.bin" --transition-weight-one \
            --policy "$B/student-s$seed" --categorical --mirror-augment --carry-cue --epochs 8 --batch 2 --checkpoint-every 8 > "$model.log" 2>&1
    fi
done
sha256sum -c "$O/training-inputs.sha256" > /dev/null
