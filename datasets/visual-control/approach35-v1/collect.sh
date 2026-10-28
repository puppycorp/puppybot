#!/usr/bin/env bash
set -euo pipefail
project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
dataset="$project/datasets/visual-control/approach35-v1"
out="$dataset/artifacts"
mkdir -p "$out"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$UID}"
if [[ -z "${WAYLAND_DISPLAY:-}${DISPLAY:-}" ]]; then
    display_sockets=()
    for candidate in "$XDG_RUNTIME_DIR"/wayland-*; do
        if [[ -S "$candidate" && -O "$candidate" ]]; then display_sockets+=("$candidate"); fi
    done
    if (( ${#display_sockets[@]} != 1 )); then
        echo 'Set WAYLAND_DISPLAY or DISPLAY from the local desktop session.' >&2
        exit 2
    fi
    export WAYLAND_DISPLAY="${display_sockets[0]##*/}"
fi
cd "$project"
[[ ! -e "$out/runs" && ! -e "$out/pilot" ]]
trap 'status=$?; printf "%s\n" "$status" > "$out/collection.exit"' EXIT
mkdir "$out/native-path"
for command in bash cat cp chmod dirname ffmpeg flock ln mkdir mktemp mv patch sha256sum; do
    executable="$(command -v "$command")"
    ln -s "$executable" "$out/native-path/$command"
done
export PATH="$out/native-path"
if [[ -z "${FLEXSCRIPT_ROOT:-}" && -f "$project/build/flex/launch/gpu-inference-review/libs/ml/pup/gpu.flex" ]]; then
    export FLEXSCRIPT_ROOT="$project/build/flex/launch/gpu-inference-review"
fi
/usr/bin/bash flex/scripts/build-control.sh
build/flex/control/compiler "$dataset/generate.flex" -o "$out/generate"
build/flex/control/compiler "$dataset/merge.flex" -o "$out/merge"
if [[ ! -d "$out/scenes" ]]; then "$out/generate" "$out/scenes"; fi
runtime="$out/runtime"
mkdir -p "$runtime/build/flex/control" "$runtime/build/flex/sim"
cp build/flex/control/{control,simulator} "$runtime/build/flex/control/"
cp build/flex/sim/puppybot.bin "$runtime/build/flex/sim/puppybot.bin"
ln -s "$project/flex" "$runtime/flex"
cp -a build/flex/sim/teach-v13/final-v2/policy "$out/reference-policy"
[[ "$(/usr/bin/sha256sum "$out/reference-policy/weights.bin" | /usr/bin/cut -d' ' -f1)" == 1a7033fd0607ddbf2137fb082d5cf9a56b2e9d0fe485fc51bdb77725f91ce7f2 ]]
/usr/bin/sha256sum "$runtime/build/flex/control/"{control,simulator} "$runtime/build/flex/sim/puppybot.bin" "$out/reference-policy/weights.bin" > "$out/runtime.sha256"
/usr/bin/find -L "$out/scenes" -type f -print0 | /usr/bin/sort -z | /usr/bin/xargs -0 /usr/bin/sha256sum > "$out/scenes.sha256"
mkdir "$out/recipe-used"
cp "$dataset/"{protocol.json,generate.flex,merge.flex,collect.sh} "$out/recipe-used/"
/usr/bin/sha256sum "$out/recipe-used/"{protocol.json,generate.flex,merge.flex,collect.sh} > "$out/recipe.sha256"
mkdir -p "$out/catalogs" "$out/pilot-catalog"
: > "$out/catalog.jsonl"
for worker in 0 1 2 3; do
    mkdir "$out/catalogs/$worker"
    for (( index=0; index<32; index++ )); do
        group=$((worker/2*3))
        fit=true
        if (( index>=24 )); then
            layout=$((6+worker/2)); scene=$((worker%2*8+index-24)); fit=false
        elif (( worker%2==0 )); then
            layout="$group"; scene="$index"
            if (( index>=16 )); then layout=$((group+1)); scene=$((index-16)); fi
        else
            layout=$((group+1)); scene=$((index+8))
            if (( index>=8 )); then layout=$((group+2)); scene=$((index-8)); fi
        fi
        ln -s "$out/scenes/$layout/$scene" "$out/catalogs/$worker/$index"
        printf '{"worker":%s,"sourceIndex":%s,"layout":%s,"scene":%s,"fit":%s,"runSeed":%s}\n' "$worker" "$index" "$layout" "$scene" "$fit" "$((9100000+worker*1000+index))" >> "$out/catalog.jsonl"
    done
done
/usr/bin/jq -s '{episodes:length,fittingEpisodes:(map(select(.fit))|length),validationEpisodes:(map(select(.fit|not))|length),records:.}' "$out/catalog.jsonl" > "$out/catalog.json"
/usr/bin/jq -e '.episodes==128 and .fittingEpisodes==96 and .validationEpisodes==32 and ([.records[]|[.layout,.scene]]|unique|length)==128 and all(.records[];.fit==(.layout<6))' "$out/catalog.json" > /dev/null
for layout in {0..7}; do
    mkdir "$out/pilot-catalog/$layout"
    ln -s "$out/scenes/$layout/0" "$out/pilot-catalog/$layout/0"
    ln -s "$out/scenes/$layout/15" "$out/pilot-catalog/$layout/1"
done
mkdir "$out/pilot"
cd "$runtime"
for wave in 0 4; do
    pids=()
    for (( layout=wave; layout<wave+4; layout++ )); do
        (
            ./build/flex/control/control correct --policy "$out/reference-policy" --output "$out/pilot/$layout" --scene-catalog "$out/pilot-catalog/$layout" --episodes 2 --validation 1 --rollin 0 --label-rollin --horizon 300 --seed "$((9001000+layout*100))" > "$out/pilot/$layout.log" 2>&1
            ./build/flex/control/control pack-data --data "$out/pilot/$layout/data.bin" --output "$out/pilot/packed-$layout" > "$out/pilot/packed-$layout.log" 2>&1
            ./build/flex/control/control verify-data --run "$out/pilot/$layout" --data "$out/pilot/packed-$layout/data.bin" --output "$out/pilot/verified-$layout" > "$out/pilot/verified-$layout.log" 2>&1
        ) &
        pids+=("$!")
    done
    status=0
    for pid in "${pids[@]}"; do if ! wait "$pid"; then status=1; fi; done
    if (( status )); then echo 'Layout pilot failed; preserve its records and stop before full collection'; exit 1; fi
done
/usr/bin/jq -s -e 'length==8 and all(.passed and .episodes==2 and .denseOracleLabels)' "$out"/pilot/verified-{0..7}/result.json > /dev/null
printf '0\n' > "$out/pilot.exit"
mkdir "$out/runs"
pids=()
for worker in 0 1 2 3; do
    (
        rollin=0
        minimum=0
        if (( worker%2 )); then rollin=32; minimum=8; fi
        ./build/flex/control/control correct --policy "$out/reference-policy" --output "$out/runs/$worker" --scene-catalog "$out/catalogs/$worker" --episodes 32 --validation 8 --rollin "$rollin" --rollin-min "$minimum" --label-rollin --horizon 300 --seed "$((9100000+worker*1000))" > "$out/runs/$worker.log" 2>&1
        ./build/flex/control/control pack-data --data "$out/runs/$worker/data.bin" --output "$out/packed-$worker" > "$out/packed-$worker.log" 2>&1
    ) &
    pids+=("$!")
done
status=0
for pid in "${pids[@]}"; do if ! wait "$pid"; then status=1; fi; done
if (( status )); then echo 'A dataset scene failed; all records retained and no aggregate published'; exit 1; fi
"$out/merge" "$out/packed-0/data.bin" "$out/runs/0" "$out/packed-1/data.bin" "$out/runs/1" "$out/merge-01"
"$out/merge" "$out/packed-2/data.bin" "$out/runs/2" "$out/packed-3/data.bin" "$out/runs/3" "$out/merge-23"
"$out/merge" "$out/merge-01/data.bin" "$out/merge-01" "$out/merge-23/data.bin" "$out/merge-23" "$out/collected-master"
./build/flex/control/control verify-data --run "$out/collected-master" --data "$out/collected-master/data.bin" --output "$out/verified" > "$out/verified.log" 2>&1
/usr/bin/jq -e '.passed and .episodes==128 and .denseOracleLabels and .studentRollinCommandsReplayed>0 and .studentRollinMaxAbsError==0' "$out/verified/result.json" > /dev/null
/usr/bin/sha256sum -c "$out/runtime.sha256" > "$out/final-runtime-integrity.log"
/usr/bin/sha256sum -c "$out/scenes.sha256" > "$out/final-scenes-integrity.log"
/usr/bin/sha256sum -c "$out/recipe.sha256" > "$out/final-recipe-integrity.log"
mv "$out/collected-master" "$out/data128"
printf '0\n' > "$out/dataset.exit"
echo '128 stricter-task histories collected and independently audited; no model training started'
