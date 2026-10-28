#!/usr/bin/env bash
# Incomplete-return training must sample the retained fitting history.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-wide-return-training.sh" "$out" > /dev/null
mock="$out/mock";root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1";old="$root/wide-return-admission-v1";baseline="$root/wide-return-training-v1";admission="$root/incomplete-return-admission-v1";runtime="$root/phase-large-tests-v1/runtime"
mkdir -p "$baseline" "$admission/expanded" "$admission/targets" "$admission/audit-fit" "$admission/audit-validation"
cp -a "$out/wide-return-trained-1/policy" "$baseline/policy";cp -a "$out/wide-return-trained-1/screen" "$baseline/screen";printf '0\n' > "$baseline/run.exit";printf '0\n' > "$admission/run.exit"
printf 'incomplete return data\n' > "$admission/expanded/data.bin";printf '{}\n' > "$admission/expanded/report.json";printf 'incomplete return targets\n' > "$admission/targets/targets.bin";printf '{}\n' > "$admission/targets/receipt.json";printf '{}\n' > "$admission/audit-fit/result.json";printf '{}\n' > "$admission/audit-validation/result.json"
old_sha="$(sha256sum "$old/expanded/data.bin" | cut -d' ' -f1)";data_sha="$(sha256sum "$admission/expanded/data.bin" | cut -d' ' -f1)"
jq -n --arg old "$old_sha" --arg data "$data_sha" '{passed:true,episodes:354,fittingHistories:240,validationHistories:114,addedReturnHistories:2,incompleteAddedEpisodes:1,studentReturnActionsReplayed:96,teacherAssisted:true,incompleteEpisodesClaimedSuccessful:false,autonomousWholeEpisodeSuccessClaimed:false,dataSHA256:$data,oldDataSHA256:$old,existingDataBytePreserved:true,existingTargetsBytePreserved:true,newHistoriesIndependentlyAudited:true,teacherLabelsTrainingOnly:true,actorInputsUnchanged:true,automaticPromotion:false}' > "$admission/coverage.json"
sed -i 's/0\.\.194,238/0..194,239/' "$runtime/build/flex/control/control"
driver="$project/datasets/visual-control/expanded-rooms-v1/train-incomplete-return.sh"
export PUPPYBOT_PROJECT="$mock" PUPPYBOT_INCOMPLETE_RETURN_TRAIN_WAIT_RUN="$root/capacity/run"
PUPPYBOT_INCOMPLETE_RETURN_TRAIN_OUT="$out/incomplete-trained" bash "$driver" > "$out/incomplete-trained.log" 2>&1
jq -e '.initialWeightsIdentical and .differentTrainingData and .optimizerStepsPerModel==98 and .addedFittingHistoriesSeen==1 and .teacherAssistedReturnHistories==2 and .incompleteTrainingHistories==1 and .validationSetsDiffer and .shuffleAndCheckpointSelectionLimitCausalInterpretation and .baseline.episodes==4 and .candidate.episodes==4 and (.automaticPromotion|not)' "$out/incomplete-trained/comparison.json" > /dev/null
for fault in PUPPYBOT_TEST_OMIT_NEW PUPPYBOT_TEST_WRONG_TARGET;do
    if env "$fault=1" PUPPYBOT_INCOMPLETE_RETURN_TRAIN_OUT="$out/$fault-incomplete" bash "$driver" > "$out/$fault-incomplete.log" 2>&1;then echo "$fault was accepted." >&2;exit 1;fi
    [[ "$(< "$out/$fault-incomplete/run.exit")" != 0 && ! -e "$out/$fault-incomplete/comparison.json" ]]
done
echo 'Incomplete-return training checks added-history exposure and target provenance.'
