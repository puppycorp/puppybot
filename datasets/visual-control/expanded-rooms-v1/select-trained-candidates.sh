#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
out="${PUPPYBOT_SELECTION_OUTPUT:-$base/trained-selection-v1}"
contact="$base/contact-training-v1"
returns="$base/return-training-v1"
unseen="$base/unseen-benchmark-v2"
[[ ! -e "$out/run.exit" && ! -e "$out/selection" ]]
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
printf '%s\n' "$BASHPID" > "$out/run.pid"
for job in "$contact/run" "$returns/run";do
    while [[ ! -f "$job.exit" ]];do
        [[ -f "$job.pid" ]] && kill -0 "$(< "$job.pid")" || { echo "Comparison disappeared without terminal status: $job" >&2;exit 1; }
        /usr/bin/sleep 10
    done
    [[ "$(< "$job.exit")" == 0 ]] || { echo "Comparison failed: $job" >&2;exit 1; }
done
cd "$project"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
/usr/bin/sha256sum -c "$unseen/inputs.sha256" > "$out/benchmark-integrity.log"
for comparison in "$contact/comparison.json" "$returns/comparison.json";do /usr/bin/jq -e '.allEpisodeAuditsPassed and .retainedPolicyOverwritten==false' "$comparison" > /dev/null;done
/usr/bin/bash "$out/gate.sh" "$out/selection" \
    "$unseen/score-contact-start.json" "$contact/initial" \
    "$unseen/score-contact-continued-202.json" "$contact/old" \
    "$unseen/score-contact-continued-222.json" "$contact/expanded" \
    "$unseen/score-return-start.json" "$returns/initial" \
    "$unseen/score-return-continued-222.json" "$returns/old" \
    "$unseen/score-return-continued-236.json" "$returns/expanded"
/usr/bin/jq -e '.reservedFinalStillRequired and (.retainedPolicyOverwritten|not)' "$out/selection/selection.json" > /dev/null
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
echo 'Six matched-comparison candidates checked; any qualifying model still needs held-out tests.'
