#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
out="$base/qualified-evaluation-queue-v1"
resources="$base/heldout-resources-v1"
result="$base/qualified-evaluation-v1"
[[ ! -e "$out/run.exit" && ! -e "$result" ]]
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
for name in trained-selection-v2 stopweight-experiment-v1 size-regression-queued-v1;do
    while [[ ! -f "$base/$name/run.exit" ]];do
        [[ -f "$base/$name/run.pid" ]] && kill -0 "$(< "$base/$name/run.pid")" || { echo "$name ended without a terminal status" >&2;exit 1; }
        /usr/bin/sleep 10
    done
done
cd "$project"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
if [[ "$(< "$base/size-regression-queued-v1/run.exit")" != 0 ]];then echo 'The size regression failed; see its retained log.' >&2;fi
/usr/bin/bash "$resources/evaluate.sh" "$result" "$resources" "$base/trained-selection-v2" "$base/stopweight-experiment-v1" > "$out/evaluation.log" 2>&1
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
echo 'Qualification and any required held-out evaluation finished.'
