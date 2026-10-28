#!/usr/bin/env bash
set -euo pipefail
project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
out="$(realpath -m "${1:?New output directory required}")"
mkdir "$out";mock="$out/mock";root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1";mkdir -p "$root/student-only-benchmark-v1"
printf '0\n' > "$root/student-only-benchmark-v1/run.exit"
cat > "$out/driver" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ -f "${PUPPYBOT_PREVIOUS_BENCHMARK_RUN:-$PUPPYBOT_PROJECT/build/flex/sim/expanded-rooms-v1/large-model-v1/student-only-benchmark-v1/run}.exit" ]]
printf 'started\n' > "$PUPPYBOT_COVERAGE_BENCHMARK_OUT"
EOF
driver="$project/datasets/visual-control/expanded-rooms-v1/queue-coverage-benchmark.sh"
PUPPYBOT_PROJECT="$mock" PUPPYBOT_PREVIOUS_BENCHMARK_LAUNCHER_PID="$$" PUPPYBOT_COVERAGE_BENCHMARK_DRIVER="$out/driver" PUPPYBOT_COVERAGE_BENCHMARK_SCRIPT="$out/unused" PUPPYBOT_COVERAGE_BENCHMARK_OUT="$out/result" PUPPYBOT_COVERAGE_BENCHMARK_QUEUE="$out/good" bash "$driver"
[[ "$(< "$out/good/run.exit")" == 0 && "$(< "$out/result")" == started ]]
rm "$root/student-only-benchmark-v1/run.exit"
mkdir "$root/other-benchmark";printf '0\n' > "$root/other-benchmark/run.exit"
PUPPYBOT_PROJECT="$mock" PUPPYBOT_PREVIOUS_BENCHMARK_RUN="$root/other-benchmark/run" PUPPYBOT_PREVIOUS_BENCHMARK_LAUNCHER_PID="$$" PUPPYBOT_COVERAGE_BENCHMARK_DRIVER="$out/driver" PUPPYBOT_COVERAGE_BENCHMARK_SCRIPT="$out/unused" PUPPYBOT_COVERAGE_BENCHMARK_OUT="$out/other-result" PUPPYBOT_COVERAGE_BENCHMARK_QUEUE="$out/other" bash "$driver"
[[ "$(< "$out/other/run.exit")" == 0 && "$(< "$out/other-result")" == started ]]
if PUPPYBOT_PROJECT="$mock" PUPPYBOT_PREVIOUS_BENCHMARK_LAUNCHER_PID=99999999 PUPPYBOT_COVERAGE_BENCHMARK_DRIVER="$out/driver" PUPPYBOT_COVERAGE_BENCHMARK_SCRIPT="$out/unused" PUPPYBOT_COVERAGE_BENCHMARK_OUT="$out/bad-result" PUPPYBOT_COVERAGE_BENCHMARK_QUEUE="$out/bad" bash "$driver" > "$out/bad.log" 2>&1;then echo 'Missing previous launcher was accepted.' >&2;exit 1;fi
[[ "$(< "$out/bad/run.exit")" == 1 && ! -e "$out/bad-result" ]]
echo 'Coverage benchmark queue starts for a tracked predecessor and rejects a missing launcher.'
