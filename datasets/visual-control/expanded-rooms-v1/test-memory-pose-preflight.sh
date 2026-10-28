#!/usr/bin/env bash
# Preflight must bind the checked executable and reject absent image evidence.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]];mkdir -p "$out/regression/targets"
prepare="$out/preparer";regression="$out/regression";printf 'known binary\n' > "$prepare";sha256sum "$prepare" > "$regression/preparer.sha256"
printf '{"passed":true,"episodes":2,"verifiedAgainstPhysicalTrace":true,"sourceFilesStableDuringVerification":true,"preActionRGBAndFeedbackMatched":true,"inverseTransformChecked":true,"actorInputsUnchanged":true}\n' > "$regression/targets/receipt.json"
printf '{"verifiedEpisodes":1,"totalEpisodes":2}\n{"verifiedEpisodes":2,"totalEpisodes":2}\n' > "$regression/progress.log"
printf 'Memory pose targets and dataset masks passed validation.\n' > "$regression/open.log"
printf 'pose target disagrees with physical trace\n' > "$regression/rejected.log"
printf 'pose source RGB is not aligned to the dataset\n' > "$regression/rejected-rgb.log"
driver="$project/datasets/visual-control/expanded-rooms-v1/capture-memory-pose-preflight.sh"
bash "$driver" "$prepare" "$regression" "$out/good.json" > /dev/null
sha="$(sha256sum "$prepare" | cut -d' ' -f1)";jq -e --arg sha "$sha" '.passed and .preparerSHA256==$sha and .preActionRGBAndFeedbackMatched and .inverseTransformChecked and .poseAndImageTamperingRejected and .progressChecked' "$out/good.json" > /dev/null
printf 'different binary\n' > "$prepare"
if bash "$driver" "$prepare" "$regression" "$out/bad-binary.json" > "$out/bad-binary.log" 2>&1;then echo 'Preflight accepted an untested binary.' >&2;exit 1;fi
[[ ! -e "$out/bad-binary.json" ]]
printf 'known binary\n' > "$prepare"
jq 'del(.preActionRGBAndFeedbackMatched)' "$regression/targets/receipt.json" > "$out/bad-receipt.json";cp "$out/bad-receipt.json" "$regression/targets/receipt.json"
if bash "$driver" "$prepare" "$regression" "$out/bad-image.json" > "$out/bad-image.log" 2>&1;then echo 'Preflight accepted missing image verification.' >&2;exit 1;fi
[[ ! -e "$out/bad-image.json" ]]
echo 'Pose preflight rejects untested binaries and missing image verification.'
