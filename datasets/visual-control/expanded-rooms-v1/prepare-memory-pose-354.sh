#!/usr/bin/env bash
# Prepare physically checked recurrent-memory targets for the 354-history set.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
root="$project/build/flex/sim/expanded-rooms-v1/large-model-v1"
admission="$root/incomplete-return-admission-v1"
source="${PUPPYBOT_MEMORY_POSE_SOURCE:-$root/memory-pose-354-source-v2}"
preflight="${PUPPYBOT_MEMORY_POSE_PREFLIGHT:-$root/memory-pose-354-preflight-v2/preflight.json}"
out="${PUPPYBOT_MEMORY_POSE_OUT:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
if [[ -n "${PUPPYBOT_MEMORY_POSE_WAIT_RUN:-}" ]];then
    prior="$PUPPYBOT_MEMORY_POSE_WAIT_RUN"
    while [[ ! -f "$prior.exit" ]];do [[ -f "$prior.pid" ]] && kill -0 "$(< "$prior.pid")" || { echo 'Previous pose preparation ended without a status.' >&2;exit 1; };sleep 20;done
    printf '%s\n' "$(< "$prior.exit")" > "$out/prior-preparation-status.txt"
fi
while [[ ! -f "$admission/run.exit" ]];do [[ -f "$admission/run.pid" ]] && kill -0 "$(< "$admission/run.pid")" || { echo 'Admission ended without a status.' >&2;exit 1; };sleep 20;done
[[ "$(< "$admission/run.exit")" == 0 ]]
data="$admission/expanded/data.bin";sha="$(sha256sum "$data" | cut -d' ' -f1)"
jq -e --arg sha "$sha" '.passed and .episodes==354 and .fittingHistories==240 and .validationHistories==114 and .dataSHA256==$sha and .newHistoriesIndependentlyAudited and .existingDataBytePreserved and .actorInputsUnchanged and (.incompleteEpisodesClaimedSuccessful|not)' "$admission/coverage.json" > /dev/null
preparer_sha="$(sha256sum "$source/prepare-memory-pose" | cut -d' ' -f1)"
jq -e --arg sha "$preparer_sha" '.passed and .preparerSHA256==$sha and .physicalTraceChecked and .preActionRGBAndFeedbackMatched and .inverseTransformChecked and .poseAndImageTamperingRejected and .progressChecked' "$preflight" > /dev/null
sha256sum "$data" "$admission/coverage.json" "$admission/expanded/report.json" "$source/prepare-memory-pose" "$source/pose-open-tests" "$preflight" > "$out/inputs.sha256"
sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
"$source/prepare-memory-pose" "$data" "$admission/expanded" "$out/targets" > "$out/prepare.log" 2>&1
"$source/pose-open-tests" "$data" "$out/targets" > "$out/open.log" 2>&1
jq -e --arg sha "$sha" '.passed and .verifiedAgainstPhysicalTrace and .sourceFilesStableDuringVerification and .actorInputsUnchanged and .preActionRGBAndFeedbackMatched and .inverseTransformChecked and .normalizationMetres==8 and .episodes==354 and .fittingHistories==240 and .validationHistories==114 and .sourceDataSHA256==$sha' "$out/targets/receipt.json" > /dev/null
if [[ -n "${PUPPYBOT_MEMORY_POSE_WAIT_RUN:-}" && "$(< "$out/prior-preparation-status.txt")" == 0 ]];then
    cmp "${PUPPYBOT_MEMORY_POSE_WAIT_RUN%/run}/targets/targets.bin" "$out/targets/targets.bin"
    printf 'true\n' > "$out/prior-targets-identical.txt"
fi
sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
echo 'Physically verified training-only pose targets prepared for all 354 histories.'
