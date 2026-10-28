#!/usr/bin/env bash
# Reproduce teacher search, recurrent student return and teacher recovery.
set -euo pipefail
project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
policy="$(cd "${1:?Policy required}" && pwd)"
out="${2:?New output directory required}"
runtime="$(cd "${3:-$project}" && pwd)"
mkdir "$out";out="$(cd "$out" && pwd)"
if [[ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}${SDL_VIDEODRIVER:-}" ]];then
    display_runtime="${XDG_RUNTIME_DIR:-/run/user/$UID}";display_sockets=()
    if [[ -d "$display_runtime" && -O "$display_runtime" ]];then
        for candidate in "$display_runtime"/wayland-*;do if [[ -S "$candidate" && -O "$candidate" ]];then display_sockets+=("$candidate");fi;done
    fi
    if (( ${#display_sockets[@]} != 1 ));then echo 'Visual control needs a local renderer. Set WAYLAND_DISPLAY or DISPLAY from your desktop session.' >&2;exit 2;fi
    export XDG_RUNTIME_DIR="$display_runtime" WAYLAND_DISPLAY="${display_sockets[0]##*/}"
fi
"$project/build/flex/control/diverse-generator" "$out/fit" 58 59 fit > "$out/generate-fit.log"
"$project/build/flex/control/diverse-generator" "$out/validation" 158 159 validation > "$out/generate-validation.log"
mkdir "$out/catalog";cp -a "$out/fit/58/4" "$out/catalog/0";cp -a "$out/validation/158/4" "$out/catalog/1"
extra=();width="$(jq -r '.memoryWidth // 128' "$policy/receipt.json")";if [[ "$width" == 256 ]];then extra+=(--large-model);else [[ "$width" == 128 ]];fi
cd "$runtime";control=./build/flex/control/control
"$control" correct --policy "$policy" --scene-catalog "$out/catalog" --output "$out/runs" --episodes 2 --validation 1 --rollin 5 --rollin-min 5 --horizon 300 --label-rollin --return-rollin --coverage-teacher --seed 1992000 "${extra[@]}" > "$out/collect.log" 2>&1
"$control" pack-data --data "$out/runs/data.bin" --output "$out/packed" > "$out/pack.log" 2>&1
"$control" verify-data --run "$out/runs" --data "$out/packed/data.bin" --output "$out/verified" "${extra[@]}" > "$out/verify.log" 2>&1
actions="$(jq -r '.studentRollinActions' "$out/runs/report.json")"
jq -e --argjson actions "$actions" '.passed and .episodes==2 and .studentRollinCommandsReplayed==$actions and .studentRollinMaxAbsError==0 and .denseOracleLabels and .taskEventHintAbsent' "$out/verified/result.json" > /dev/null
for i in 0 1;do
    jq -e '.searchTeacher=="coverage-camera-v2" and .studentBeginsAfterConsumption and .studentStartAction>=1 and .studentActions>=1 and .studentActions<=5 and .denseOracleLabels and .teacherPlannerUsesPrivilegedGeometry and (.searchGoalsUseUnseenBrickPosition|not)' "$out/runs/expert-$i/supervision.json" > /dev/null
    bash "$project/datasets/visual-control/expanded-rooms-v1/audit-coverage-teacher-v2.sh" "$out/runs/expert-$i" "$out/goal-audit-$i"
done
echo 'Coverage search and student return windows passed physical, recurrent and goal checks.'
