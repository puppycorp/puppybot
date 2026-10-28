#!/usr/bin/env bash
# Synthetic receipt check; no simulator or dataset is admitted.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(/usr/bin/realpath -m "${1:?New output directory required}")"
[[ ! -e "$out" ]]
mock="$out/mock";root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1"
old="$root/gated-search-admission-v1";admission="$root/gated-search-cohort-admission-v1";cohort="$root/gated-search-cohort-v1";work="$cohort/worker-0"
mkdir -p "$old/expanded" "$admission/expanded" "$admission/targets" "$admission/audit-fit" "$admission/audit-validation" "$admission/labels-0" "$work/packed" "$work/runs/expert-0" "$work/runs/expert-1"
printf 'old data\n' > "$old/expanded/data.bin";printf 'expanded data\n' > "$admission/expanded/data.bin";printf 'target data\n' > "$admission/targets/targets.bin";printf 'worker data\n' > "$work/packed/data.bin"
old_sha="$(/usr/bin/sha256sum "$old/expanded/data.bin" | /usr/bin/cut -d' ' -f1)";sha="$(/usr/bin/sha256sum "$admission/expanded/data.bin" | /usr/bin/cut -d' ' -f1)";target_sha="$(/usr/bin/sha256sum "$admission/targets/targets.bin" | /usr/bin/cut -d' ' -f1)";worker_sha="$(/usr/bin/sha256sum "$work/packed/data.bin" | /usr/bin/cut -d' ' -f1)"
printf '0\n' > "$cohort/run.exit";printf '0\n' > "$admission/run.exit"
printf '{"successfulWorkers":1}\n' > "$cohort/summary.json";printf '{"passed":true}\n' > "$cohort/worker-0.json"
for worker in 1 2 3;do printf '{"passed":false}\n' > "$cohort/worker-$worker.json";done
for episode in 0 1;do printf '{"studentActions":120}\n' > "$work/runs/expert-$episode/supervision.json";done
/usr/bin/jq -n --arg sha "$worker_sha" '{passed:true,dataSHA256:$sha,studentActions:240,oracleTrainingOnly:true,actorInputsUnchanged:true,offlineAnalysisOnly:true}' > "$admission/labels-0/interventions.json"
/usr/bin/jq -n --arg sha "$sha" --arg old "$old_sha" '{passed:true,episodes:284,fittingHistories:205,validationHistories:79,addedSearchHistories:2,dataSHA256:$sha,oldDataSHA256:$old,studentRollinActionsReplayed:240,existingDataBytePreserved:true,existingTargetsBytePreserved:true,newHistoriesIndependentlyAudited:true,teacherLabelsTrainingOnly:true,actorInputsUnchanged:true,studentAutonomousSuccessClaimed:false,automaticPromotion:false}' > "$admission/coverage.json"
/usr/bin/jq -n --arg sha "$sha" --arg target "$target_sha" '{passed:true,episodes:284,fittingHistories:205,validationHistories:79,sourceDataSHA256:$sha,targetsSHA256:$target,actorInputsUnchanged:true}' > "$admission/targets/receipt.json"
for name in data-preserved targets-preserved;do printf '{"passed":true,"existingHistoriesPreserved":282,"expandedHistories":284,"expandedFittingHistories":205}\n' > "$admission/$name.json";done
for role in fit validation;do start=204;if [[ "$role" == validation ]];then start=283;fi
    /usr/bin/jq -n --arg sha "$sha" --argjson start "$start" '{passed:true,datasetEpisodes:284,episodes:1,firstEpisode:$start,dataSHA256:$sha,studentPolicies256:1,studentRollinCommandsReplayed:120,studentRollinMaxAbsError:0,datasetInputsMatchActualRGBAndOwnFeedback:true,executedCommandsMatchRecordings:true,preActionAlignmentChecked:true,zeroPaddingChecked:true,denseOracleLabels:true,taskEventHintAbsent:true}' > "$admission/audit-$role/result.json"
done
driver="$project/datasets/visual-control/expanded-rooms-v1/audit-gated-search-cohort-admission.sh"
PUPPYBOT_PROJECT="$mock" PUPPYBOT_COHORT_AUDIT_OUT="$out/good" /usr/bin/bash "$driver" > "$out/good.log" 2>&1
/usr/bin/jq -e '.passed and .episodes==284 and .studentRollinActionsReplayed==240 and .bothReplayReceiptsMatchDataset' "$out/good/result.json" > /dev/null
/usr/bin/jq '.dataSHA256="wrong"' "$admission/audit-validation/result.json" > "$admission/audit-validation/tmp.json"
mv "$admission/audit-validation/tmp.json" "$admission/audit-validation/result.json"
if PUPPYBOT_PROJECT="$mock" PUPPYBOT_COHORT_AUDIT_OUT="$out/bad" /usr/bin/bash "$driver" > "$out/bad.log" 2>&1;then echo 'Replay receipt for another dataset was accepted.' >&2;exit 1;fi
[[ "$(< "$out/bad/run.exit")" == 1 && ! -e "$out/bad/result.json" ]]
echo 'Synthetic cohort admission audit rejects mismatched replay dataset hashes.'
