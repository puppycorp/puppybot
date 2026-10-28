#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/odometry-aux-v1"
source="$project/build/flex/sim/late-search-v1/artifacts-v2/data172"
[[ ! -e "$root/accepted" && ! -e "$root/accepted.exit" ]]
trap 'status=$?; printf "%s\n" "$status" > "$root/accepted.exit"' EXIT
while [[ ! -f "$root/prepare.exit" ]];do
    kill -0 230617 || { echo 'CPU preparation handle disappeared without terminal status';exit 1; }
    /usr/bin/sleep 5
done
[[ "$(< "$root/prepare.exit")" == 0 ]]
"$root/guards" "$root/targets-tool" "$source/data.bin" "$source" "$root/targets/targets.bin" "$root/guards-output" > "$root/guards.log" 2>&1
/usr/bin/jq -e '.passed and .changedSplitRoleRejected and .oneFrameMisalignmentRejected and .nonzeroPaddingRejected' "$root/guards-output/result.json" > /dev/null
sha="$(/usr/bin/sha256sum "$root/targets/targets.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -ne --arg sha "$sha" --slurpfile prepared "$root/targets/report.json" --slurpfile verified "$root/verified.json" '$prepared[0].prepared and $verified[0].passed and $prepared[0].targetsSHA256==$sha and $verified[0].targetsSHA256==$sha and $prepared[0].sourceDataSHA256==$verified[0].sourceDataSHA256 and $prepared[0].preActionFrames==$verified[0].preActionFramesChecked and $prepared[0].fittingHistories==136 and $prepared[0].validationHistories==36' > /dev/null
mkdir "$root/accepted"
cp "$root/targets/targets.bin" "$root/accepted/targets.bin"
/usr/bin/jq -n --slurpfile prepared "$root/targets/report.json" --slurpfile verified "$root/verified.json" --slurpfile guards "$root/guards-output/result.json" '$prepared[0]+{schema:"puppybot.relative-pose-supervision.v1",passed:true,verifiedAgainstPhysicalTrace:true,verification:$verified[0],negativeGuards:$guards[0],privilegedTrainingTargetsOnly:true,actorInputsUnchanged:true,modelTrainingNotYetImplemented:true}' > "$root/accepted/receipt.json"
/usr/bin/cmp "$root/accepted/targets.bin" "$root/targets/targets.bin"
echo 'Relative-pose labels admitted for possible training-only memory supervision; no model or actor inputs changed.'
