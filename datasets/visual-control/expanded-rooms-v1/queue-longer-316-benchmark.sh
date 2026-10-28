#!/usr/bin/env bash
# Wait for the queued training screen before starting the frozen benchmark.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
root="$project/build/flex/sim/expanded-rooms-v1/large-model-v1"
training="$root/longer-316-queue-v1/run";capacity="$root/feedback-drop-benchmark-v1/run"
driver="${PUPPYBOT_LONGER_316_FROZEN_BENCHMARK_DRIVER:?Frozen comparison driver required}"
benchmark="${PUPPYBOT_LONGER_316_FROZEN_EPISODE_BENCHMARK:?Frozen episode benchmark required}"
result="${PUPPYBOT_LONGER_316_BENCHMARK_OUT:?New benchmark output required}"
out="${PUPPYBOT_LONGER_316_BENCHMARK_QUEUE_OUT:?New queue output required}"
[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
sha256sum "$driver" "$benchmark" > "$out/inputs.sha256"
while [[ ! -f "$training.exit" ]];do [[ -f "$training.pid" ]] && kill -0 "$(< "$training.pid")" || { echo 'Training queue ended without a status.' >&2;exit 1; };sleep 20;done
[[ "$(< "$training.exit")" == 0 ]] || { echo 'Training screen failed; benchmark not started.' >&2;exit 1; }
sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
PUPPYBOT_PROJECT="$project" PUPPYBOT_LONGER_316_BENCHMARK_WAIT_RUN="$capacity" PUPPYBOT_LONGER_316_BENCHMARK_SCRIPT="$benchmark" PUPPYBOT_LONGER_316_BENCHMARK_OUT="$result" bash "$driver" > "$out/benchmark.log" 2>&1
sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
echo 'Longer-training benchmark queue finished.'
