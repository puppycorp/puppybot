#!/usr/bin/env bash
# Wait until the pose screen starts before invoking its frozen benchmark.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
root="$project/build/flex/sim/expanded-rooms-v1/large-model-v1"
prepare="$root/memory-pose-316-v2/run";screen="$root/large-pose-screen-v2/run"
driver="${PUPPYBOT_POSE_FROZEN_BENCHMARK_DRIVER:?Frozen comparison driver required}"
benchmark="${PUPPYBOT_POSE_FROZEN_EPISODE_BENCHMARK:?Frozen episode benchmark required}"
result="${PUPPYBOT_LARGE_POSE_BENCHMARK_OUT:?New benchmark output required}"
out="${PUPPYBOT_POSE_BENCHMARK_QUEUE_OUT:?New queue output required}"
[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
sha256sum "$driver" "$benchmark" > "$out/inputs.sha256"
attempt=0
while [[ ! -f "$prepare.exit" ]] && (( attempt<360 ));do sleep 20;attempt=$((attempt+1));done
[[ -f "$prepare.exit" ]] || { echo 'Pose preparation did not report a terminal status within two hours.' >&2;exit 1; }
[[ "$(< "$prepare.exit")" == 0 ]] || { echo 'Pose preparation failed; benchmark not started.' >&2;exit 1; }
attempt=0
while [[ ! -f "$screen.pid" && ! -f "$screen.exit" ]] && (( attempt<30 ));do sleep 20;attempt=$((attempt+1));done
[[ -f "$screen.pid" || -f "$screen.exit" ]] || { echo 'Pose screen did not start within ten minutes; benchmark not started.' >&2;exit 1; }
sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
PUPPYBOT_PROJECT="$project" PUPPYBOT_LARGE_POSE_BENCHMARK_SCRIPT="$benchmark" PUPPYBOT_LARGE_POSE_BENCHMARK_OUT="$result" bash "$driver" > "$out/benchmark.log" 2>&1
sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
echo 'Pose benchmark queue finished.'
