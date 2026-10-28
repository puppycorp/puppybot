#!/usr/bin/env bash
# Start the frozen longer-training driver after the pose job has been launched.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
root="$project/build/flex/sim/expanded-rooms-v1/large-model-v1"
prepare="$root/memory-pose-316-v2/run";capacity="$root/large-pose-screen-v2/run"
driver="${PUPPYBOT_LONGER_316_FROZEN_DRIVER:?Frozen training driver required}"
training="${PUPPYBOT_LONGER_316_OUT:?New training output required}"
out="${PUPPYBOT_LONGER_316_QUEUE_OUT:?New queue output required}"
[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
sha256sum "$driver" > "$out/inputs.sha256"
attempt=0
while [[ ! -f "$prepare.exit" ]] && (( attempt<360 ));do sleep 20;attempt=$((attempt+1));done
[[ -f "$prepare.exit" ]] || { echo 'Pose preparation did not report a terminal status within two hours.' >&2;exit 1; }
[[ "$(< "$prepare.exit")" == 0 ]] || { echo 'Pose preparation failed; longer training not started.' >&2;exit 1; }
attempt=0
while [[ ! -f "$capacity.pid" && ! -f "$capacity.exit" ]] && (( attempt<30 ));do sleep 20;attempt=$((attempt+1));done
[[ -f "$capacity.pid" || -f "$capacity.exit" ]] || { echo 'Pose screen did not start within ten minutes; longer training not started.' >&2;exit 1; }
sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
PUPPYBOT_PROJECT="$project" PUPPYBOT_LONGER_316_WAIT_RUN="$capacity" PUPPYBOT_LONGER_316_OUT="$training" bash "$driver" > "$out/training.log" 2>&1
sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
echo 'Longer-training queued run finished.'
