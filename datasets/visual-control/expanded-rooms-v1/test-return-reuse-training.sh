#!/usr/bin/env bash
# Reuse training must actually sample the added return history.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-wide-student-training.sh" "$out" > /dev/null
mock="$out/mock";root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1";old="$root/coverage-scale-admission-v1";admission="$root/return-reuse-admission-v1"
mkdir -p "$admission/expanded" "$admission/targets" "$admission/audit-fit" "$admission/audit-validation";printf '0\n' > "$admission/run.exit"
printf 'return data\n' > "$admission/expanded/data.bin";printf '{}\n' > "$admission/expanded/report.json";printf 'return targets\n' > "$admission/targets/targets.bin";printf '{}\n' > "$admission/targets/receipt.json";printf '{}\n' > "$admission/audit-fit/result.json";printf '{}\n' > "$admission/audit-validation/result.json"
old_sha="$(sha256sum "$old/expanded/data.bin" | cut -d' ' -f1)";data_sha="$(sha256sum "$admission/expanded/data.bin" | cut -d' ' -f1)"
jq -n --arg old "$old_sha" --arg data "$data_sha" '{passed:true,episodes:350,fittingHistories:238,validationHistories:112,addedReturnHistories:2,studentReturnActionsReplayed:120,teacherAssisted:true,autonomousWholeEpisodeSuccessClaimed:false,dataSHA256:$data,oldDataSHA256:$old,existingDataBytePreserved:true,existingTargetsBytePreserved:true,newHistoriesIndependentlyAudited:true,teacherLabelsTrainingOnly:true,actorInputsUnchanged:true,automaticPromotion:false}' > "$admission/coverage.json"
driver="$project/datasets/visual-control/expanded-rooms-v1/train-return-reuse.sh"
export PUPPYBOT_PROJECT="$mock" PUPPYBOT_RETURN_REUSE_TRAIN_WAIT_RUN="$root/capacity/run"
PUPPYBOT_RETURN_REUSE_TRAIN_OUT="$out/return-trained" bash "$driver" > "$out/return-trained.log" 2>&1
jq -e '.initialWeightsIdentical and .differentTrainingData and .optimizerStepsPerModel==98 and .addedFittingHistoriesSeen==1 and .teacherAssistedReturnHistories==2 and .validationSetsDiffer and .shuffleAndCheckpointSelectionLimitCausalInterpretation and .baseline.episodes==4 and .candidate.episodes==4 and (.automaticPromotion|not)' "$out/return-trained/comparison.json" > /dev/null
for fault in PUPPYBOT_TEST_OMIT_NEW PUPPYBOT_TEST_WRONG_TARGET;do
    if env "$fault=1" PUPPYBOT_RETURN_REUSE_TRAIN_OUT="$out/$fault-return" bash "$driver" > "$out/$fault-return.log" 2>&1;then echo "$fault was accepted." >&2;exit 1;fi
    [[ "$(< "$out/$fault-return/run.exit")" != 0 && ! -e "$out/$fault-return/comparison.json" ]]
done
echo 'Return reuse training checks new-history exposure and target provenance.'
