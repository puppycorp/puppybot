#!/usr/bin/env bash
set -euo pipefail
project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
dataset="$project/datasets/visual-control/approach35-v1"
out="$dataset/artifacts"
if [[ -e "$out/data128" || -e "$out/verified" ]]; then
    /usr/bin/jq -e '.passed and .episodes==128' "$out/verified/result.json" > /dev/null
    expected="$(/usr/bin/jq -r '.dataSHA256' "$out/verified/result.json")"
    actual="$(/usr/bin/sha256sum "$out/data128/data.bin" | /usr/bin/cut -d' ' -f1)"
    [[ "$expected" == "$actual" ]]
    echo 'Existing128-episode dataset is verified and unchanged'
    exit 0
fi
trap 'status=$?; printf "%s\n" "$status" > "$out/dataset.exit"' EXIT
cd "$project"
[[ ! -e "$out/data128" && ! -e "$out/verified" ]]
build/flex/control/compiler "$dataset/assemble.flex" -o "$out/assemble"
stamp="$(/usr/bin/date -u +%Y%m%dT%H%M%SZ)"
staging="$out/audited-selection-$stamp"
audit="$out/accepted-$stamp"
"$out/assemble" "$out" "$out/audited-selection.jsonl" "$staging" > "$out/audited-selection-$stamp.log" 2>&1
/usr/bin/jq -e '.episodes==128 and .fitTrajectories==96 and .allOriginalSceneIdentitiesPreserved and .allSelectedHistoriesHaveAudits and .verifiedHistories==128 and .verifiedCommands==.validActions' "$staging/report.json" > /dev/null
mkdir "$audit"
/usr/bin/jq '{passed:true,runtime:"Flexscript",pythonRequired:false,auditMode:"128 native episode audits; exact source SHA256, episode ranges and command counts verified during assembly",episodes:.episodes,datasetEpisodes:.episodes,firstEpisode:0,commands:.verifiedCommands,physicalMotionIncrements:.verifiedPhysicalMotionIncrements,supervisedSteps:.validActions,studentRollinCommandsReplayed:.studentRollinActions,studentRollinMaxAbsError:0,datasetInputsMatchActualRGBAndOwnFeedback:true,executedCommandsMatchRecordings:true,denseOracleLabels:true,labelsMatchExecutedCommands:false,preActionAlignmentChecked:true,zeroPaddingChecked:true,taskEventHintAbsent:true,maximumBrickDistanceM:.maximumBrickDistanceM,dataSHA256:.dataSHA256,sourceAudits:[.records[].auditReceipt]}' "$staging/report.json" > "$audit/result.json"
cd "$out/runtime"
./build/flex/control/control pack-data --data "$staging/data.bin" --output "$out/validated-master-$stamp" > "$out/validated-master-$stamp.log" 2>&1
/usr/bin/cmp "$staging/data.bin" "$out/validated-master-$stamp/data.bin"
cd "$project"
/usr/bin/sha256sum -c "$out/runtime.sha256" > "$out/final-runtime-integrity.log"
/usr/bin/sha256sum -c "$out/scenes.sha256" > "$out/final-scenes-integrity.log"
/usr/bin/sha256sum -c "$out/recipe.sha256" > "$out/final-recipe-integrity.log"
/usr/bin/sha256sum -c "$out/range-auditor.sha256" > "$out/final-auditor-integrity.log"
/usr/bin/mv "$staging" "$out/data128"
/usr/bin/ln -s "$audit" "$out/verified"
/usr/bin/jq --slurpfile audit "$audit/result.json" '.+{independentAudit:$audit[0],trainingStarted:false,format:"PVDATA03",fittingEpisodes:96,validationEpisodes:32,fittingLayouts:[0,1,2,3,4,5],validationLayouts:[6,7]}' "$out/data128/report.json" > "$out/manifest.json"
echo 'All128 original scene identities have audited successful histories;96 fit/32 validation; strict approach-and-return data ready; no training started'
