#!/usr/bin/env bash
# Retry only a completed benchmark that failed the known simulator identity check.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
root="$project/build/flex/sim/expanded-rooms-v1/large-model-v1"
kind="${1:?Expected pose or feedback}"
driver="${PUPPYBOT_REFERENCE_FIX_DRIVER:?Frozen corrected driver required}"
benchmark="${PUPPYBOT_REFERENCE_EPISODE_BENCHMARK:?Frozen episode benchmark required}"
out="${PUPPYBOT_REFERENCE_RETRY_QUEUE_OUT:?New queue directory required}"
case "$kind" in
    pose) previous="$root/large-pose-benchmark-v1";result="$root/large-pose-benchmark-v2";capacity="$root/contact-weight-benchmark-v2/run";;
    feedback) previous="$root/feedback-drop-benchmark-v1";result="$root/feedback-drop-benchmark-v2";capacity="$root/large-pose-benchmark-v2/run";;
    *) echo 'Expected pose or feedback.' >&2;exit 2;;
esac
[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
sha256sum "$driver" "$benchmark" > "$out/inputs.sha256"
while [[ ! -f "$previous/run.exit" ]];do [[ -f "$previous/run.pid" ]] && kill -0 "$(< "$previous/run.pid")" || { echo 'Previous benchmark ended without a status.' >&2;exit 1; };sleep 20;done
printf '%s\n' "$(< "$previous/run.exit")" > "$out/previous-status.txt"
if [[ "$(< "$previous/run.exit")" == 0 ]];then echo 'Previous benchmark succeeded; no retry needed.';exit 0;fi
[[ -f "$previous/candidate/run.exit" && "$(< "$previous/candidate/run.exit")" != 0 ]] || { echo 'Failure was not the episode benchmark.' >&2;exit 1; }
rg -q 'simulator.* differ:' "$previous/candidate.log" || { echo 'Failure was not the known simulator mismatch.' >&2;exit 1; }
sha256sum "$previous/run.exit" "$previous/candidate/run.exit" "$previous/candidate.log" >> "$out/inputs.sha256"
sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
if [[ "$kind" == pose ]];then
    PUPPYBOT_PROJECT="$project" PUPPYBOT_LARGE_POSE_BENCHMARK_SCRIPT="$benchmark" PUPPYBOT_LARGE_POSE_BENCHMARK_WAIT_RUN="$capacity" PUPPYBOT_LARGE_POSE_BENCHMARK_OUT="$result" bash "$driver" > "$out/retry.log" 2>&1
else
    PUPPYBOT_PROJECT="$project" PUPPYBOT_FEEDBACK_DROP_BENCHMARK_SCRIPT="$benchmark" PUPPYBOT_FEEDBACK_DROP_BENCHMARK_WAIT_RUN="$capacity" PUPPYBOT_FEEDBACK_DROP_BENCHMARK_OUT="$result" bash "$driver" > "$out/retry.log" 2>&1
fi
sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
echo 'Reference-simulator benchmark retry completed.'
