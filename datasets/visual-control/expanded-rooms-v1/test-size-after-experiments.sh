#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
out="$base/size-regression-queued-v1"
[[ ! -e "$out/run.exit" && ! -e "$out/result" ]]
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
for name in contact-training-v1 return-training-v1 highres-development-run-v2 highres-full-data-v2 stopweight-experiment-v1; do
    while [[ ! -f "$base/$name/run.exit" ]]; do
        [[ -f "$base/$name/run.pid" ]] && kill -0 "$(< "$base/$name/run.pid")" || { echo "$name ended without a terminal status" >&2; exit 1; }
        /usr/bin/sleep 10
    done
done
cd "$project"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
"$out/size-tests" "$out/control" "$out/trainer" "$out/kernels" "$out/result" > "$out/test.log" 2>&1
/usr/bin/jq -e '.passed and .validDatasetAbove1GiBMappedPackedAndForwarded and .trainerAndWorkflowRejectAbove2GiB' "$out/result/result.json" > /dev/null
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
echo 'Legacy size regression passed after the queued GPU experiments.'
