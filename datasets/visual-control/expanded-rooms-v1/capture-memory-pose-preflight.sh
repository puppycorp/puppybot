#!/usr/bin/env bash
# Bind a completed physical and tampering regression to its preparer binary.
set -euo pipefail
prepare="$(realpath "${1:?Preparer executable required}")"
regression="$(realpath "${2:?Completed pose regression required}")"
out="${3:?New preflight file required}"
[[ ! -e "$out" ]]
jq -e '.passed and .episodes==2 and .verifiedAgainstPhysicalTrace and .sourceFilesStableDuringVerification and .preActionRGBAndFeedbackMatched and .inverseTransformChecked and .actorInputsUnchanged' "$regression/targets/receipt.json" > /dev/null
jq -se 'map({verifiedEpisodes,totalEpisodes})==[{verifiedEpisodes:1,totalEpisodes:2},{verifiedEpisodes:2,totalEpisodes:2}]' "$regression/progress.log" > /dev/null
rg -Fq 'Memory pose targets and dataset masks passed validation.' "$regression/open.log"
rg -Fq 'pose target disagrees with physical trace' "$regression/rejected.log"
rg -Fq 'pose source RGB is not aligned to the dataset' "$regression/rejected-rgb.log"
[[ ! -e "$regression/rejected" && ! -e "$regression/rejected-rgb" ]]
sha="$(sha256sum "$prepare" | cut -d' ' -f1)";receipt="$(sha256sum "$regression/targets/receipt.json" | cut -d' ' -f1)"
sha256sum -c "$regression/preparer.sha256" > /dev/null
[[ "$(cut -d' ' -f1 "$regression/preparer.sha256")" == "$sha" ]]
jq -n --arg sha "$sha" --arg receipt "$receipt" '{passed:true,preparerSHA256:$sha,regressionReceiptSHA256:$receipt,physicalTraceChecked:true,preActionRGBAndFeedbackMatched:true,inverseTransformChecked:true,poseAndImageTamperingRejected:true,progressChecked:true}' > "$out"
echo 'Pose-preparer preflight bound to the checked executable.'
