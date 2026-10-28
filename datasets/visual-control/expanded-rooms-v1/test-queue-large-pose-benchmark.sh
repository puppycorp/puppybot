#!/usr/bin/env bash
# Failed preparation must not start a pose comparison.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
mock="$out/mock";root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1"
mkdir -p "$root/memory-pose-316-v2" "$root/large-pose-screen-v2"
printf '0\n' > "$root/memory-pose-316-v2/run.exit";printf '0\n' > "$root/large-pose-screen-v2/run.exit";printf 'benchmark\n' > "$out/episode-benchmark"
cat > "$out/driver" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ -f "$PUPPYBOT_LARGE_POSE_BENCHMARK_SCRIPT" ]]
mkdir "$PUPPYBOT_LARGE_POSE_BENCHMARK_OUT";printf 'called\n' > "$PUPPYBOT_LARGE_POSE_BENCHMARK_OUT/evidence"
EOF
queue="$project/datasets/visual-control/expanded-rooms-v1/queue-large-pose-benchmark.sh"
PUPPYBOT_PROJECT="$mock" PUPPYBOT_POSE_FROZEN_BENCHMARK_DRIVER="$out/driver" PUPPYBOT_POSE_FROZEN_EPISODE_BENCHMARK="$out/episode-benchmark" PUPPYBOT_LARGE_POSE_BENCHMARK_OUT="$out/benchmark" PUPPYBOT_POSE_BENCHMARK_QUEUE_OUT="$out/good" bash "$queue" > "$out/good.log" 2>&1
[[ -f "$out/benchmark/evidence" && "$(< "$out/good/run.exit")" == 0 ]]
printf '1\n' > "$root/memory-pose-316-v2/run.exit"
if PUPPYBOT_PROJECT="$mock" PUPPYBOT_POSE_FROZEN_BENCHMARK_DRIVER="$out/driver" PUPPYBOT_POSE_FROZEN_EPISODE_BENCHMARK="$out/episode-benchmark" PUPPYBOT_LARGE_POSE_BENCHMARK_OUT="$out/bad-benchmark" PUPPYBOT_POSE_BENCHMARK_QUEUE_OUT="$out/bad" bash "$queue" > "$out/bad.log" 2>&1;then echo 'Failed preparation was accepted.' >&2;exit 1;fi
[[ ! -e "$out/bad-benchmark" && "$(< "$out/bad/run.exit")" != 0 ]]
echo 'Pose benchmark queue rejects failed preparation.'
