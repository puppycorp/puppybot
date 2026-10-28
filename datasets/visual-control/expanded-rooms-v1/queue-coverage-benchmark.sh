#!/usr/bin/env bash
# The previous paired benchmark is itself queued. Wait for its launcher to
# create a tracked job before handing over to the ordinary benchmark driver.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
root="$project/build/flex/sim/expanded-rooms-v1/large-model-v1"
launcher="${PUPPYBOT_PREVIOUS_BENCHMARK_LAUNCHER_PID:?Previous launcher PID required}"
driver="${PUPPYBOT_COVERAGE_BENCHMARK_DRIVER:?Frozen driver required}"
benchmark="${PUPPYBOT_COVERAGE_BENCHMARK_SCRIPT:?Frozen benchmark required}"
out="${PUPPYBOT_COVERAGE_BENCHMARK_OUT:?Benchmark output required}"
queue="${PUPPYBOT_COVERAGE_BENCHMARK_QUEUE:?New queue directory required}"
[[ "$launcher" =~ ^[0-9]+$ && ! -e "$queue" ]];mkdir "$queue"
trap 'status=$?; printf "%s\n" "$status" > "$queue/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$queue/run.pid"
previous="${PUPPYBOT_PREVIOUS_BENCHMARK_RUN:-$root/student-only-benchmark-v1/run}"
while [[ ! -f "$previous.pid" && ! -f "$previous.exit" ]];do
    kill -0 "$launcher" || { echo 'Previous benchmark launcher exited before its job appeared.' >&2;exit 1; }
    /usr/bin/sleep 20
done
PUPPYBOT_PROJECT="$project" PUPPYBOT_COVERAGE_BENCHMARK_SCRIPT="$benchmark" PUPPYBOT_COVERAGE_BENCHMARK_OUT="$out" /usr/bin/bash "$driver"
