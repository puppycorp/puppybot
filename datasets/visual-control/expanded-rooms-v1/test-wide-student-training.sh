#!/usr/bin/env bash
# Student training must expose new samples and retain the matching target data.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-coverage-scale-training.sh" "$out" > /dev/null
mock="$out/mock";root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1";old="$root/coverage-scale-admission-v1";baseline="$root/coverage-scale-training-v1";admission="$root/wide-student-admission-v1";runtime="$root/phase-large-tests-v1/runtime"
mkdir -p "$baseline" "$admission/expanded" "$admission/targets" "$admission/audit-fit" "$admission/audit-validation"
cp -a "$out/scaled/policy" "$baseline/policy";cp -a "$out/scaled/screen" "$baseline/screen";printf '0\n' > "$baseline/run.exit";printf '0\n' > "$admission/run.exit"
printf 'student data\n' > "$admission/expanded/data.bin";printf '{}\n' > "$admission/expanded/report.json";printf 'student targets\n' > "$admission/targets/targets.bin";printf '{}\n' > "$admission/targets/receipt.json";printf '{}\n' > "$admission/audit-fit/result.json";printf '{}\n' > "$admission/audit-validation/result.json"
old_sha="$(sha256sum "$old/expanded/data.bin" | cut -d' ' -f1)";data_sha="$(sha256sum "$admission/expanded/data.bin" | cut -d' ' -f1)"
jq -n --arg old "$old_sha" --arg data "$data_sha" '{passed:true,episodes:356,fittingHistories:241,validationHistories:115,addedStudentHistories:8,dataSHA256:$data,oldDataSHA256:$old,studentFound:0,studentReturns:0,existingDataBytePreserved:true,existingTargetsBytePreserved:true,newHistoriesIndependentlyAudited:true,teacherLabelsTrainingOnly:true,actorInputsUnchanged:true,automaticPromotion:false}' > "$admission/coverage.json"
sed -i 's/0\.\.194,221/0..194,237/' "$runtime/build/flex/control/control"
driver="$project/datasets/visual-control/expanded-rooms-v1/train-wide-student.sh"
export PUPPYBOT_PROJECT="$mock" PUPPYBOT_WIDE_STUDENT_TRAIN_WAIT_RUN="$root/capacity/run"
PUPPYBOT_WIDE_STUDENT_TRAIN_OUT="$out/student-trained" bash "$driver" > "$out/student-trained.log" 2>&1
jq -e '.initialWeightsIdentical and .differentTrainingData and .optimizerStepsPerModel==98 and .addedFittingHistoriesSeen==1 and .validationSetsDiffer and .shuffleAndCheckpointSelectionLimitCausalInterpretation and .baseline.episodes==4 and .candidate.episodes==4 and (.automaticPromotion|not)' "$out/student-trained/comparison.json" > /dev/null
for fault in PUPPYBOT_TEST_OMIT_NEW PUPPYBOT_TEST_WRONG_TARGET;do
    if env "$fault=1" PUPPYBOT_WIDE_STUDENT_TRAIN_OUT="$out/$fault-student" bash "$driver" > "$out/$fault-student.log" 2>&1;then echo "$fault was accepted." >&2;exit 1;fi
    [[ "$(< "$out/$fault-student/run.exit")" != 0 && ! -e "$out/$fault-student/comparison.json" ]]
done
echo 'Wide student training checks new-history exposure and target provenance.'
