#!/usr/bin/env bash
set -euo pipefail
benchmark="${1:?Benchmark directory required}"
policy="${2:?Gated policy required}"
probe="${3:?Frozen compiled probe required}"
analyzer="${4:?Frozen analysis script required}"
out="${5:?New output directory required}"
[[ ! -e "$out" ]]
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
while [[ ! -f "$benchmark/run.exit" ]]; do
    [[ -f "$benchmark/run.pid" ]] && kill -0 "$(< "$benchmark/run.pid")" || { echo 'Benchmark ended without a status.' >&2; exit 1; }
    /usr/bin/sleep 20
done
[[ "$(< "$benchmark/run.exit")" == 0 ]]
sha="$(/usr/bin/sha256sum "$policy/weights.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$sha" '.episodes==32 and .completedRecordings==32 and .auditedEpisodes==32 and (.rows|length)==32 and ([.rows[].caseIndex]|sort)==[range(0;32)] and all(.rows[]; .recordingCompleted and .auditPassed and .policyWeightsSHA256==$sha and .taskEventHint==false and .suppliedMap==false)' "$benchmark/score.json" > /dev/null
/usr/bin/sha256sum "$probe" "$analyzer" "$policy/weights.bin" "$policy/policy" "$policy/receipt.json" "$benchmark/score.json" > "$out/inputs.sha256"
episodes=()
for ((index=0;index<32;index++)); do episodes+=("$benchmark/$index/$((9960000+index))"); done
/usr/bin/bash "$analyzer" "$probe" "$policy" "$out/analysis" "${episodes[@]}" > "$out/analysis.log" 2>&1
[[ "$(< "$out/analysis/run.exit")" == 0 ]]
/usr/bin/jq -e --arg sha "$sha" '.weightsSHA256==$sha and .episodes==32 and all(.rows[]; .replayExact)' "$out/analysis/summary.json" > /dev/null
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
echo 'All 32 development episodes were replayed for gate analysis.'
