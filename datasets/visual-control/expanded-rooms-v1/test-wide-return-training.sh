#!/usr/bin/env bash
# Wide-return training must sample new fitting histories for either pair count.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-return-reuse-training.sh" "$out" > /dev/null
mock="$out/mock";root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1";old="$root/return-reuse-admission-v1";baseline="$root/return-reuse-training-v1";admission="$root/wide-return-admission-v1";runtime="$root/phase-large-tests-v1/runtime"
mkdir -p "$baseline" "$admission/expanded" "$admission/targets" "$admission/audit-fit" "$admission/audit-validation"
cp -a "$out/return-trained/policy" "$baseline/policy";cp -a "$out/return-trained/screen" "$baseline/screen";printf '0\n' > "$baseline/run.exit";printf '0\n' > "$admission/run.exit"
printf 'wide return data\n' > "$admission/expanded/data.bin";printf '{}\n' > "$admission/expanded/report.json";printf 'wide return targets\n' > "$admission/targets/targets.bin";printf '{}\n' > "$admission/targets/receipt.json";printf '{}\n' > "$admission/audit-fit/result.json";printf '{}\n' > "$admission/audit-validation/result.json"
old_sha="$(sha256sum "$old/expanded/data.bin" | cut -d' ' -f1)";data_sha="$(sha256sum "$admission/expanded/data.bin" | cut -d' ' -f1)"
sed -i 's/0\.\.194,237/0..194,238/' "$runtime/build/flex/control/control"
driver="$project/datasets/visual-control/expanded-rooms-v1/train-wide-return.sh"
export PUPPYBOT_PROJECT="$mock" PUPPYBOT_WIDE_RETURN_TRAIN_WAIT_RUN="$root/capacity/run"
for count in 1 2;do
    total=$((350+2*count));fit=$((238+count));validation=$((112+count));added=$((2*count))
    jq -n --arg old "$old_sha" --arg data "$data_sha" --argjson total "$total" --argjson fit "$fit" --argjson validation "$validation" --argjson added "$added" '{passed:true,episodes:$total,fittingHistories:$fit,validationHistories:$validation,addedReturnHistories:$added,studentReturnActionsReplayed:120,teacherAssisted:true,autonomousWholeEpisodeSuccessClaimed:false,dataSHA256:$data,oldDataSHA256:$old,existingDataBytePreserved:true,existingTargetsBytePreserved:true,newHistoriesIndependentlyAudited:true,teacherLabelsTrainingOnly:true,actorInputsUnchanged:true,automaticPromotion:false}' > "$admission/coverage.json"
    PUPPYBOT_WIDE_RETURN_TRAIN_OUT="$out/wide-return-trained-$count" bash "$driver" > "$out/wide-return-trained-$count.log" 2>&1
    jq -e --argjson added "$added" '.initialWeightsIdentical and .differentTrainingData and .optimizerStepsPerModel==98 and .addedFittingHistoriesSeen==1 and .teacherAssistedReturnHistories==$added and .validationSetsDiffer and .shuffleAndCheckpointSelectionLimitCausalInterpretation and .baseline.episodes==4 and .candidate.episodes==4 and (.automaticPromotion|not)' "$out/wide-return-trained-$count/comparison.json" > /dev/null
done
for fault in PUPPYBOT_TEST_OMIT_NEW PUPPYBOT_TEST_WRONG_TARGET;do
    if env "$fault=1" PUPPYBOT_WIDE_RETURN_TRAIN_OUT="$out/$fault-wide-return" bash "$driver" > "$out/$fault-wide-return.log" 2>&1;then echo "$fault was accepted." >&2;exit 1;fi
    [[ "$(< "$out/$fault-wide-return/run.exit")" != 0 && ! -e "$out/$fault-wide-return/comparison.json" ]]
done
echo 'Wide return training checks added-history exposure for both pair counts.'
