#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/expanded-rooms-v1"
admission="$root/contact-admission-v1"
out="$root/contact-labels-v1"
old="$root/labels-v3/targets/targets.bin"
[[ ! -e "$out/run.exit" && ! -e "$out/targets" ]]
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
printf '%s\n' "$BASHPID" > "$out/run.pid"
while [[ ! -f "$admission/run.exit" ]];do
    [[ -f "$admission/run.pid" ]] && kill -0 "$(< "$admission/run.pid")" || { echo 'Admission disappeared without a terminal status.' >&2;exit 1; }
    /usr/bin/sleep 10
done
[[ "$(< "$admission/run.exit")" == 0 ]] || { echo 'Admission did not pass; target labels not generated.' >&2;exit 1; }
cd "$project"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
data="$admission/merged-6/data.bin"
sha="$(/usr/bin/sha256sum "$data" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$sha" '.passed and .episodes==222 and .fittingHistories==174 and .validationHistories==48 and .dataSHA256==$sha and .allNewTripsIndependentlyAudited and .existingDataBytePreserved' "$admission/coverage.json" > /dev/null
"$out/survey" "$data" "$admission/merged-6" "$out/survey.json" 222 "$sha" "$out/candidates.jsonl" > "$out/survey.log" 2>&1
candidate_sha="$(/usr/bin/sha256sum "$out/candidates.jsonl" | /usr/bin/cut -d' ' -f1)"
"$out/prepare" "$data" "$admission/merged-6" "$out/candidates.jsonl" "$out/survey.json" "$sha" "$candidate_sha" "$out/targets" > "$out/prepare.log" 2>&1
"$out/preflight" "$data" "$out/targets" "$out/preflight.json" > "$out/preflight.log" 2>&1
"$out/preserve" "$old" "$out/targets/targets.bin" "$out/preserved.json" > "$out/preserved.log" 2>&1
/usr/bin/jq -e --arg sha "$sha" '.passed and .episodes==222 and .sourceDataSHA256==$sha and .actorInputsUnchanged' "$out/preflight.json" > /dev/null
/usr/bin/jq -e '.passed and .existingHistoriesPreserved==202 and .fittingHistories==160 and .expandedHistories==222 and .expandedFittingHistories==174' "$out/preserved.json" > /dev/null
/usr/bin/jq -e --arg sha "$sha" --arg candidates "$candidate_sha" '.passed and .sourceDataSHA256==$sha and .candidateManifestSHA256==$candidates and .episodes==222 and .fittingHistories==174 and .validationHistories==48 and .sequenceLength==354 and .fittingCandidates>=4309 and .validationCandidates>=1151 and .projectionAndPixelsIndependentlyRechecked and .visibilityHeuristicNotProvenSegmentation and .actorInputsUnchanged' "$out/targets/receipt.json" > /dev/null
[[ "$(/usr/bin/sha256sum "$data" | /usr/bin/cut -d' ' -f1)" == "$sha" ]]
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
echo 'Expanded target labels passed projection, input, split and retained-label checks; no model has been trained.'
