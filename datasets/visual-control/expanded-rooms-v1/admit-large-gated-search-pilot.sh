#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
base="$project/build/flex/sim/expanded-rooms-v1"
root="$base/large-model-v1"
old="$root/return-cohort-admission-v3"
pilot="$root/gated-search-pilot-v1"
disjoint="$root/gated-search-disjoint-v1"
development="$root/corpus-development-audit-280-v2"
generalization="$root/generalization-overlap-280-v2"
phase="$root/gated-search-phase-analysis-v2"
bin="$root/source/admission-cohort-v3/bin"
runtime="$root/phase-large-tests-v1/runtime"
survey="$base/return-labels-v1/survey"
prepare="$base/return-labels-v1/prepare"
out="${PUPPYBOT_GATED_ADMISSION_OUT:?New output directory required}"
[[ ! -e "$out" ]]
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
for item in "$old" "$pilot" "$disjoint" "$development" "$generalization";do [[ "$(< "$item/run.exit")" == 0 ]];done
old_data="$old/expanded/data.bin"; added_data="$pilot/packed/data.bin"
old_sha="$(/usr/bin/sha256sum "$old_data" | /usr/bin/cut -d' ' -f1)"
added_sha="$(/usr/bin/sha256sum "$added_data" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$old_sha" '.passed and .episodes==280 and .fittingHistories==203 and .validationHistories==77 and .dataSHA256==$sha and .existingDataBytePreserved and .existingTargetsBytePreserved and .newHistoriesIndependentlyAudited and .teacherLabelsTrainingOnly and .actorInputsUnchanged' "$old/coverage.json" > /dev/null
/usr/bin/jq -e --arg sha "$added_sha" '.passed and .episodes==2 and .studentCommandsReplayed==240 and .dataSHA256==$sha and .teacherLabelsTrainingOnly and (.actorTaskEventHint|not) and (.studentAutonomousSuccessClaimed|not) and (.automaticMerge|not)' "$pilot/summary.json" > /dev/null
/usr/bin/jq -e --arg sha "$added_sha" '.passed and .episodes==2 and .dataSHA256==$sha and .studentRollinCommandsReplayed==240 and .studentRollinMaxAbsError==0 and .denseOracleLabels and .taskEventHintAbsent' "$pilot/verified/result.json" > /dev/null
/usr/bin/jq -e --arg old "$old_sha" --arg added "$added_sha" '.passed and .existingHistories==280 and .corpusDataSHA256==$old and .pilotDataSHA256==$added and .exactCasesAndEnvironmentsDisjointFromCorpusDevelopmentAndGeneralization and .similarGeometryNotExcluded and (.automaticMerge|not)' "$disjoint/result.json" > /dev/null
/usr/bin/jq -e --arg sha "$old_sha" '.passed and .corpusDataSHA256==$sha and .developmentCaseOverlap==0 and .developmentEnvironmentOverlap==0' "$development/result.json" > /dev/null
/usr/bin/jq -e --arg sha "$old_sha" '.passed and .trainingDataSHA256==$sha and .cases==16 and .exactCaseAndEnvironmentHashesDisjointFromTrainingAndDevelopment' "$generalization/result.json" > /dev/null
/usr/bin/jq -e '.episodes==2 and .studentFrames==240 and .searchFrames==240 and .teacherActionsExcluded and .replayExact' "$phase/summary.json" > /dev/null
/usr/bin/sha256sum "$bin"/* "$runtime/build/flex/control/control" "$runtime/build/flex/control/simulator" "$survey" "$prepare" "$old_data" "$old/targets/targets.bin" "$old/targets/receipt.json" "$old/coverage.json" "$added_data" "$pilot/summary.json" "$pilot/verified/result.json" "$disjoint/result.json" "$development/result.json" "$generalization/result.json" "$phase/summary.json" > "$out/inputs.sha256"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
mkdir "$out/labels"
"$survey" "$added_data" "$pilot/runs" "$out/labels/survey.json" 2 "$added_sha" "$out/labels/candidates.jsonl" > "$out/labels/survey.log" 2>&1
candidates="$(/usr/bin/sha256sum "$out/labels/candidates.jsonl" | /usr/bin/cut -d' ' -f1)"
"$prepare" "$added_data" "$pilot/runs" "$out/labels/candidates.jsonl" "$out/labels/survey.json" "$added_sha" "$candidates" "$out/labels/targets" > "$out/labels/prepare.log" 2>&1
"$bin/merge-dense-many" "$out/expanded" "$old_data" "$old/expanded" "$added_data" "$pilot/runs" > "$out/expanded.log"
"$bin/merge-targets-many" "$out/expanded" "$out/targets" "$old_data" "$old/targets" "$added_data" "$out/labels/targets" > "$out/targets.log"
"$bin/data-preserve-added" "$old_data" "$out/expanded/data.bin" "$out/data-preserved.json"
"$bin/target-preserve-added" "$old/targets/targets.bin" "$out/targets/targets.bin" "$out/targets-preserved.json"
"$bin/preflight-expanded-targets" "$out/expanded/data.bin" "$out/targets" "$out/preflight.json"
for report in "$out/data-preserved.json" "$out/targets-preserved.json";do /usr/bin/jq -e '.passed and .existingHistoriesPreserved==280 and .expandedHistories==282 and .expandedFittingHistories==204' "$report" > /dev/null;done
/usr/bin/jq -e '.passed and .episodes==282 and .fittingHistories==204 and .validationHistories==78 and .actorInputsUnchanged' "$out/preflight.json" > /dev/null
export PATH="$base/unseen-benchmark-v2/native-path:$PATH" XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$runtime"
./build/flex/control/control verify-data --run "$out/expanded" --data "$out/expanded/data.bin" --output "$out/audit-fit" --audit-start 203 --audit-count 1 > "$out/audit-fit.log" 2>&1
./build/flex/control/control verify-data --run "$out/expanded" --data "$out/expanded/data.bin" --output "$out/audit-validation" --audit-start 281 --audit-count 1 > "$out/audit-validation.log" 2>&1
for role in fit validation;do /usr/bin/jq -e '.passed and .episodes==1 and .studentPolicies256==1 and .studentRollinCommandsReplayed==120 and .studentRollinMaxAbsError==0 and .taskEventHintAbsent and .denseOracleLabels' "$out/audit-$role/result.json" > /dev/null;done
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
new_sha="$(/usr/bin/sha256sum "$out/expanded/data.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -n --arg old "$old_sha" --arg sha "$new_sha" '{passed:true,episodes:282,fittingHistories:204,validationHistories:78,addedSearchHistories:2,studentSearchActionsReplayed:240,oldDataSHA256:$old,dataSHA256:$sha,existingDataBytePreserved:true,existingTargetsBytePreserved:true,newHistoriesIndependentlyAudited:true,teacherLabelsTrainingOnly:true,actorInputsUnchanged:true,studentAutonomousSuccessClaimed:false,automaticPromotion:false}' > "$out/coverage.json"
echo 'Two independently audited student search histories were added without changing actor inputs.'
