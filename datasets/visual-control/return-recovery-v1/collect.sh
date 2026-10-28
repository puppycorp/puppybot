#!/usr/bin/env bash
set -euo pipefail
project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
dataset="$project/datasets/visual-control/return-recovery-v1"
out="$dataset/artifacts"
base="$project/datasets/visual-control/approach35-v1/artifacts"
pilot="$project/build/flex/sim/approach35-v2"
[[ ! -e "$out" ]]
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/collection.exit"' EXIT
cd "$project"
/usr/bin/jq -s -e 'length==4 and all(.passed and .episodes==2 and .studentRollinMaxAbsError==0 and .studentRollinCommandsReplayed>=180)' \
    "$pilot"/pilot/verified-{0..2}/result.json "$pilot/pilot-swept3-verified/result.json" > "$out/pilot-gate.json"
[[ "$(/usr/bin/sha256sum "$base/data128/data.bin" | /usr/bin/cut -d' ' -f1)" == e45f28097f8f58b00b915b026c921b9013334c3795be205aca0dce2c13c3a148 ]]
mkdir "$out/native-path"
for command in bash cat cp chmod dirname ffmpeg flock ln mkdir mktemp mv patch sha256sum; do
    executable="$(command -v "$command")"
    ln -s "$executable" "$out/native-path/$command"
done
export PATH="$out/native-path"
if [[ -z "${FLEXSCRIPT_ROOT:-}" && -f "$project/build/flex/launch/gpu-inference-review/libs/ml/pup/gpu.flex" ]]; then
    export FLEXSCRIPT_ROOT="$project/build/flex/launch/gpu-inference-review"
fi
bash flex/scripts/build-control.sh > "$out/build.log" 2>&1
for check in tests action-tests oracle-tests motion-tests seek-tests; do
    "build/flex/control/$check" "$out/$check" > "$out/$check.log" 2>&1
done
build/flex/control/compiler "$dataset/subset.flex" -o "$out/subset"
build/flex/control/compiler "$dataset/merge.flex" -o "$out/merge"
runtime="$out/runtime"
mkdir -p "$runtime/build/flex/control" "$runtime/build/flex/sim"
cp build/flex/control/{control,simulator} "$runtime/build/flex/control/"
cp build/flex/sim/puppybot.bin "$runtime/build/flex/sim/puppybot.bin"
ln -s "$project/flex" "$runtime/flex"
cp -a "$project/build/flex/sim/approach35-train-v1/policy-warm5" "$out/student"
[[ "$(/usr/bin/sha256sum "$out/student/weights.bin" | /usr/bin/cut -d' ' -f1)" == 8aeffe83f433ebf53d03974a99058caa65f78a2f592b128214df7857befceaf5 ]]
/usr/bin/sha256sum "$runtime/build/flex/control/"{control,simulator} "$runtime/build/flex/sim/puppybot.bin" "$out/student/weights.bin" > "$out/runtime.sha256"
mkdir "$out/recipe-used"
cp "$dataset/"{protocol.json,subset.flex,merge.flex,coverage.jq,collect.sh} "$out/recipe-used/"
/usr/bin/sha256sum "$out/recipe-used/"* > "$out/recipe.sha256"
mkdir -p "$out/catalogs" "$out/runs"
: > "$out/catalog.jsonl"
for worker in 0 1 2 3; do
    mkdir "$out/catalogs/$worker"
    for (( index=0; index<8; index++ )); do
        layout=$index
        scene=$(((worker*3+layout*2)%16))
        fit=true; if (( index>=6 )); then fit=false; fi
        ln -s "$base/scenes/$layout/$scene" "$out/catalogs/$worker/$index"
        printf '{"worker":%s,"sourceIndex":%s,"layout":%s,"scene":%s,"fit":%s}\n' "$worker" "$index" "$layout" "$scene" "$fit" >> "$out/catalog.jsonl"
    done
done
/usr/bin/jq -s '.' "$out/catalog.jsonl" > "$out/catalog.json"
/usr/bin/jq -e 'length==32 and (map(select(.fit))|length)==24 and all(.[];.fit==(.layout<6)) and (map([.layout,.scene])|unique|length)==32' "$out/catalog.json" > /dev/null
/usr/bin/find -L "$out/catalogs" -type f -print0 | /usr/bin/sort -z | /usr/bin/xargs -0 /usr/bin/sha256sum > "$out/scenes.sha256"
cd "$runtime"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/1000}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-1}"
pids=()
for worker in 0 1 2 3; do
    (
        trap 'status=$?; printf "%s\n" "$status" > "$out/worker-'"$worker"'.exit"' EXIT
        extra=(); if (( worker<2 )); then extra+=(--return-rollin); fi
        ./build/flex/control/control correct --policy "$out/student" --output "$out/runs/$worker" --scene-catalog "$out/catalogs/$worker" \
            --episodes 8 --validation 2 --rollin 150 --rollin-min 90 --label-rollin --return-via-home --horizon 512 --seed "$((9410000+worker*1000))" "${extra[@]}" > "$out/runs/$worker.log" 2>&1
        for (( index=0; index<8; index++ )); do
            /usr/bin/cmp "$out/catalogs/$worker/$index/case.json" "$out/runs/$worker/expert-$index/scene/case.json"
            /usr/bin/cmp "$out/catalogs/$worker/$index/environment.bin" "$out/runs/$worker/expert-$index/scene/environment.bin"
        done
        ./build/flex/control/control pack-data --data "$out/runs/$worker/data.bin" --output "$out/packed-$worker" > "$out/packed-$worker.log" 2>&1
        ./build/flex/control/control verify-data --run "$out/runs/$worker" --data "$out/packed-$worker/data.bin" --output "$out/verified-$worker" > "$out/verified-$worker.log" 2>&1
        expected="$(/usr/bin/sha256sum "$out/packed-$worker/data.bin" | /usr/bin/cut -d' ' -f1)"
        /usr/bin/jq -e --arg expected "$expected" '.passed and .episodes==8 and .studentRollinMaxAbsError==0 and .dataSHA256==$expected' "$out/verified-$worker/result.json" > /dev/null
    ) &
    pids+=("$!")
done
status=0
for pid in "${pids[@]}"; do if ! wait "$pid"; then status=1; fi; done
if (( status )); then echo 'A correction or source audit failed; all attempts retained and no aggregate published'; exit 1; fi
cd "$project"
"$out/subset" "$base/data128/data.bin" "$base/data128" "$out/base64"
"$out/merge" "$out/packed-0/data.bin" "$out/runs/0" "$out/packed-1/data.bin" "$out/runs/1" "$out/merge-01"
"$out/merge" "$out/packed-2/data.bin" "$out/runs/2" "$out/packed-3/data.bin" "$out/runs/3" "$out/merge-23"
"$out/merge" "$out/merge-01/data.bin" "$out/merge-01" "$out/merge-23/data.bin" "$out/merge-23" "$out/corrections32"
"$out/merge" "$out/base64/data.bin" "$out/base64" "$out/corrections32/data.bin" "$out/corrections32" "$out/merged96"
"$runtime/build/flex/control/control" pack-data --data "$out/merged96/data.bin" --output "$out/repacked96" > "$out/repacked96.log" 2>&1
/usr/bin/cmp "$out/merged96/data.bin" "$out/repacked96/data.bin"
/usr/bin/jq -n --slurpfile final "$out/merged96/report.json" --slurpfile base "$out/base64/report.json" --slurpfile corrections "$out/corrections32/report.json" \
    --slurpfile first "$out/merge-01/report.json" --slurpfile second "$out/merge-23/report.json" --slurpfile old "$base/verified/result.json" \
    --slurpfile catalog "$out/catalog.json" --slurpfile audits <(/usr/bin/jq -c '.' "$out"/verified-{0..3}/result.json) \
    -f "$out/recipe-used/coverage.jq" > "$out/coverage.json"
/usr/bin/sha256sum -c "$out/runtime.sha256" > "$out/runtime-integrity.log"
/usr/bin/sha256sum -c "$out/recipe.sha256" > "$out/recipe-integrity.log"
/usr/bin/sha256sum -c "$out/scenes.sha256" > "$out/scenes-integrity.log"
mv "$out/merged96" "$out/data96"
printf '0\n' > "$out/dataset.exit"
echo '96 histories accepted: 64 unchanged audited base trips plus32 audited late student recoveries'
