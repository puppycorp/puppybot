#!/usr/bin/env bash
# A failed training queue must never start the benchmark.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
mock="$out/mock";root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1"
mkdir -p "$root/longer-316-queue-v1"
printf '0\n' > "$root/longer-316-queue-v1/run.exit";printf 'benchmark\n' > "$out/episode-benchmark"
cat > "$out/driver" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "$PUPPYBOT_LONGER_316_BENCHMARK_WAIT_RUN" == "$PUPPYBOT_PROJECT/build/flex/sim/expanded-rooms-v1/large-model-v1/feedback-drop-benchmark-v1/run" ]]
mkdir "$PUPPYBOT_LONGER_316_BENCHMARK_OUT";printf 'called\n' > "$PUPPYBOT_LONGER_316_BENCHMARK_OUT/evidence"
EOF
queue="$project/datasets/visual-control/expanded-rooms-v1/queue-longer-316-benchmark.sh"
PUPPYBOT_PROJECT="$mock" PUPPYBOT_LONGER_316_FROZEN_BENCHMARK_DRIVER="$out/driver" PUPPYBOT_LONGER_316_FROZEN_EPISODE_BENCHMARK="$out/episode-benchmark" PUPPYBOT_LONGER_316_BENCHMARK_OUT="$out/benchmark" PUPPYBOT_LONGER_316_BENCHMARK_QUEUE_OUT="$out/good" bash "$queue" > "$out/good.log" 2>&1
[[ -f "$out/benchmark/evidence" && "$(< "$out/good/run.exit")" == 0 ]]
printf '1\n' > "$root/longer-316-queue-v1/run.exit"
if PUPPYBOT_PROJECT="$mock" PUPPYBOT_LONGER_316_FROZEN_BENCHMARK_DRIVER="$out/driver" PUPPYBOT_LONGER_316_FROZEN_EPISODE_BENCHMARK="$out/episode-benchmark" PUPPYBOT_LONGER_316_BENCHMARK_OUT="$out/bad-benchmark" PUPPYBOT_LONGER_316_BENCHMARK_QUEUE_OUT="$out/bad" bash "$queue" > "$out/bad.log" 2>&1;then echo 'Failed training was accepted.' >&2;exit 1;fi
[[ ! -e "$out/bad-benchmark" && "$(< "$out/bad/run.exit")" != 0 ]]
echo 'Benchmark queue rejects failed training.'
