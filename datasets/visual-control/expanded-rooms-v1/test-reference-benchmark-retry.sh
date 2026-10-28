#!/usr/bin/env bash
# Retry only a known, terminal simulator mismatch and never duplicate success.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
mock="$out/mock";root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1"
mkdir -p "$root/large-pose-benchmark-v1/candidate" "$root/feedback-drop-benchmark-v1/candidate"
printf 'episode benchmark\n' > "$out/benchmark"
cat > "$out/driver" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ -n "${PUPPYBOT_LARGE_POSE_BENCHMARK_OUT:-}" ]];then
    [[ "$PUPPYBOT_LARGE_POSE_BENCHMARK_WAIT_RUN" == "$PUPPYBOT_PROJECT/build/flex/sim/expanded-rooms-v1/large-model-v1/contact-weight-benchmark-v2/run" ]]
    mkdir "$PUPPYBOT_LARGE_POSE_BENCHMARK_OUT"
else
    [[ "$PUPPYBOT_FEEDBACK_DROP_BENCHMARK_WAIT_RUN" == "$PUPPYBOT_PROJECT/build/flex/sim/expanded-rooms-v1/large-model-v1/large-pose-benchmark-v2/run" ]]
    mkdir "$PUPPYBOT_FEEDBACK_DROP_BENCHMARK_OUT"
fi
EOF
for n in large-pose-benchmark-v1 feedback-drop-benchmark-v1;do
    printf '1\n' > "$root/$n/run.exit";printf '1\n' > "$root/$n/candidate/run.exit";printf 'simulator build/simulator differ: byte 25\n' > "$root/$n/candidate.log"
done
queue="$project/datasets/visual-control/expanded-rooms-v1/queue-reference-benchmark-retry.sh"
export PUPPYBOT_PROJECT="$mock" PUPPYBOT_REFERENCE_FIX_DRIVER="$out/driver" PUPPYBOT_REFERENCE_EPISODE_BENCHMARK="$out/benchmark"
PUPPYBOT_REFERENCE_RETRY_QUEUE_OUT="$out/pose" bash "$queue" pose > "$out/pose.log" 2>&1
PUPPYBOT_REFERENCE_RETRY_QUEUE_OUT="$out/feedback" bash "$queue" feedback > "$out/feedback.log" 2>&1
[[ -d "$root/large-pose-benchmark-v2" && -d "$root/feedback-drop-benchmark-v2" ]]
printf '0\n' > "$root/large-pose-benchmark-v1/run.exit"
PUPPYBOT_REFERENCE_RETRY_QUEUE_OUT="$out/skip" bash "$queue" pose > "$out/skip.log" 2>&1
rg -Fq 'no retry needed' "$out/skip.log"
printf '1\n' > "$root/large-pose-benchmark-v1/run.exit";printf 'other failure\n' > "$root/large-pose-benchmark-v1/candidate.log"
if PUPPYBOT_REFERENCE_RETRY_QUEUE_OUT="$out/unexpected" bash "$queue" pose > "$out/unexpected.log" 2>&1;then echo 'Unexpected failure was accepted for retry.' >&2;exit 1;fi
[[ "$(< "$out/unexpected/run.exit")" != 0 ]]
echo 'Reference benchmark retry handles only terminal simulator mismatches.'
