#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/expanded-rooms-v1"
admission="$root/admission-v1"
out="$root/labels-v1"
old="$project/build/flex/sim/memory-pose-v1/target-candidates-v1/targets/targets.bin"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
printf '%s\n' "$BASHPID" > "$out/run.pid"
cd "$project"
while [[ ! -f "$admission/launcher.exit" ]];do
    [[ -f "$admission/launcher.pid" ]] && kill -0 "$(< "$admission/launcher.pid")" || { echo 'Admission launcher disappeared without a terminal status.';exit 1; }
    /usr/bin/sleep 10
done
[[ "$(< "$admission/launcher.exit")" == 0 && "$(< "$admission/dataset.exit")" == 0 ]]
/usr/bin/sha256sum -c "$out/recipe.sha256" > "$out/integrity-before.log"
[[ "$(/usr/bin/sha256sum "$old" | /usr/bin/cut -d' ' -f1)" == 9846229a1a28aa77c7e8653d1bbe14dbe6185c27d90a46b77d68b5e1bf0e5294 ]]
data="$admission/data202/data.bin"
sha="$(/usr/bin/sha256sum "$data" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$sha" '.passed and .episodes==202 and .fittingHistories==160 and .validationHistories==42 and .dataSHA256==$sha and .allNewTripsIndependentlyAudited and .allNewScenesDistinctFromPreviousAndEachOther' "$admission/coverage.json" > /dev/null
"$out/survey" "$data" "$admission/data202" "$out/survey.json" 202 "$sha" "$out/candidates.jsonl" > "$out/survey.log" 2>&1
candidate_sha="$(/usr/bin/sha256sum "$out/candidates.jsonl" | /usr/bin/cut -d' ' -f1)"
"$out/prepare" "$data" "$admission/data202" "$out/candidates.jsonl" "$out/survey.json" "$sha" "$candidate_sha" "$out/targets" > "$out/prepare.log" 2>&1
"$out/preflight" "$data" "$out/targets" "$out/preflight.json" > "$out/preflight.log" 2>&1
"$out/target-preserve" "$old" "$out/targets/targets.bin" "$out/preserved.json" > "$out/preserved.log" 2>&1
/usr/bin/jq -e --arg sha "$sha" '.passed and .episodes==202 and .sourceDataSHA256==$sha and .actorInputsUnchanged' "$out/preflight.json" > /dev/null
/usr/bin/jq -e '.passed and .existingHistoriesPreserved==172' "$out/preserved.json" > /dev/null
/usr/bin/jq -e --arg sha "$sha" --arg candidates "$candidate_sha" '.passed and .sourceDataSHA256==$sha and .candidateManifestSHA256==$candidates and .episodes==202 and .fittingHistories==160 and .validationHistories==42 and .sequenceLength==354 and .fittingCandidates>=3864 and .validationCandidates>=965 and .projectionAndPixelsIndependentlyRechecked and .visibilityHeuristicNotProvenSegmentation and .actorInputsUnchanged' "$out/targets/receipt.json" > /dev/null
[[ "$(/usr/bin/sha256sum "$data" | /usr/bin/cut -d' ' -f1)" == "$sha" ]]
/usr/bin/sha256sum -c "$out/recipe.sha256" > "$out/integrity-after.log"
echo 'Expanded target sidecar passed source, split and existing-label preservation checks.'
