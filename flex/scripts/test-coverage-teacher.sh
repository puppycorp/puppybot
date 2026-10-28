#!/usr/bin/env bash
# Check the opt-in teacher against live observations and student-action replay.
set -euo pipefail
project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
policy="$(cd "${1:?Policy required}" && pwd)"
scene="$(cd "${2:?Scene required}" && pwd)"
out="${3:?New output directory required}"
runtime="$(cd "${4:-$project}" && pwd)"
mkdir "$out";out="$(cd "$out" && pwd)"
if [[ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}${SDL_VIDEODRIVER:-}" ]]; then
    display_runtime="${XDG_RUNTIME_DIR:-/run/user/$UID}";display_sockets=()
    if [[ -d "$display_runtime" && -O "$display_runtime" ]]; then
        for candidate in "$display_runtime"/wayland-*; do
            if [[ -S "$candidate" && -O "$candidate" ]]; then display_sockets+=("$candidate"); fi
        done
    fi
    if (( ${#display_sockets[@]} != 1 )); then echo 'Visual control needs a local renderer. Set WAYLAND_DISPLAY or DISPLAY from your desktop session.' >&2;exit 2;fi
    export XDG_RUNTIME_DIR="$display_runtime" WAYLAND_DISPLAY="${display_sockets[0]##*/}"
fi
cd "$runtime";control=./build/flex/control/control
if "$control" correct --policy "$policy" --scene "$scene" --output "$out/no-labels" --episodes 2 --validation 1 --rollin 1 --horizon 5 --coverage-teacher > "$out/no-labels.log" 2>&1;then echo 'Coverage teacher was accepted without dense labels.' >&2;exit 1;fi
rg -Fq 'coverage teacher requires dense labels' "$out/no-labels.log"
"$control" correct --policy "$policy" --scene "$scene" --output "$out/runs" --episodes 2 --validation 1 --rollin 5 --rollin-min 5 --horizon 5 --seed 2026000 --label-rollin --allow-incomplete --coverage-teacher > "$out/collect.log" 2>&1
"$control" verify-data --run "$out/runs" --data "$out/runs/data.bin" --output "$out/verified" --allow-incomplete > "$out/verify.log" 2>&1
jq -e '.passed and .episodes==2 and .studentRollinCommandsReplayed==10 and .studentRollinMaxAbsError==0 and .incompleteEpisodes==2 and .denseOracleLabels and .taskEventHintAbsent' "$out/verified/result.json" > /dev/null
for i in 0 1;do
    jq -e '.searchTeacher=="coverage-camera-v2" and .teacherUsesRoomBounds and (.searchGoalsUseUnseenBrickPosition|not) and .teacherPlannerUsesPrivilegedGeometry' "$out/runs/expert-$i/supervision.json" > /dev/null
    bash "$project/datasets/visual-control/expanded-rooms-v1/audit-coverage-teacher-v2.sh" "$out/runs/expert-$i" "$out/goal-audit-$i"
    jq -e '.passed and .steps==5 and .brickPositionNotReadBySearchReconstruction' "$out/goal-audit-$i/result.json" > /dev/null
done
echo 'Coverage-teacher labels and goals match two recorded student-controlled episodes.'
