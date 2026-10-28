#!/usr/bin/env bash
# Student rollout admission preserves the old corpus and rejects changed labels.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-wide-student-rollouts.sh" "$out" > /dev/null
mock="$out/mock";base="$mock/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1";old="$root/coverage-scale-admission-v1";bin="$root/source/admission-cohort-v3/bin";runtime="$root/coverage-teacher-v2-runtime-v1/runtime"
ln -s "$out/student-rollouts" "$root/wide-student-rollouts-v1"
bash "$project/datasets/visual-control/expanded-rooms-v1/audit-wide-student-control.sh" "$out/student-rollouts" "$root/wide-student-control-audit-v1" > "$out/student-control-audit.log" 2>&1
mkdir -p "$old/expanded" "$old/targets" "$bin" "$base/return-labels-v1" "$root/empty-target-build-v2"
printf '0\n' > "$old/run.exit";printf 'old data\n' > "$old/expanded/data.bin";printf 'old targets\n' > "$old/targets/targets.bin";printf '{}\n' > "$old/targets/receipt.json"
sha="$(sha256sum "$old/expanded/data.bin" | cut -d' ' -f1)"
jq -n --arg sha "$sha" '{passed:true,episodes:348,fittingHistories:237,validationHistories:111,dataSHA256:$sha,existingDataBytePreserved:true,existingTargetsBytePreserved:true,newHistoriesIndependentlyAudited:true,teacherLabelsTrainingOnly:true,actorInputsUnchanged:true}' > "$old/coverage.json"
cat > "$base/return-labels-v1/survey" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "$4" == 8 ]];printf '{}\n' > "$3";printf 'candidates\n' > "$6"
EOF
cat > "$root/empty-target-build-v2/prepare" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
mkdir "$7";printf 'new targets\n' > "$7/targets.bin";jq -n --arg sha "$5" '{passed:true,sourceDataSHA256:$sha,allowEmptyCandidateSplits:true,projectionAndPixelsIndependentlyRechecked:true,actorInputsUnchanged:true}' > "$7/receipt.json"
EOF
cat > "$root/empty-target-build-v2/merge-targets" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
mkdir "$2";printf 'merged targets\n' > "$2/targets.bin"
EOF
cat > "$bin/merge-dense-many" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
mkdir "$1";printf 'merged data\n' > "$1/data.bin"
EOF
cat > "$bin/data-preserve-added" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '{"passed":true,"existingHistoriesPreserved":348,"expandedHistories":356,"expandedFittingHistories":241}\n' > "$3"
EOF
cp "$bin/data-preserve-added" "$bin/target-preserve-added"
cat > "$bin/preflight-expanded-targets" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '{"passed":true,"episodes":356,"fittingHistories":241,"validationHistories":115,"actorInputsUnchanged":true}\n' > "$3"
EOF
cat > "$runtime/build/flex/control/control" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == verify-data ]];shift;start="";count=""
while (( $# ));do case "$1" in --output) output="$2";shift 2;; --data) data="$2";shift 2;; --audit-start) start="$2";shift 2;; --audit-count) count="$2";shift 2;; *) shift;; esac;done
[[ "$count" == 4 && ( "$start" == 237 || "$start" == 352 ) ]];mkdir "$output";sha="$(sha256sum "$data" | cut -d' ' -f1)"
jq -n --arg sha "$sha" '{passed:true,datasetEpisodes:356,episodes:4,dataSHA256:$sha,studentPolicies256:4,studentRollinCommandsReplayed:1200,studentRollinMaxAbsError:0,denseOracleLabels:true,datasetInputsMatchActualRGBAndOwnFeedback:true,executedCommandsMatchRecordings:true,preActionAlignmentChecked:true,zeroPaddingChecked:true,taskEventHintAbsent:true,incompleteEpisodes:4,incompleteEpisodesClaimedSuccessful:false}' > "$output/result.json"
EOF
chmod +x "$base/return-labels-v1/survey" "$root/empty-target-build-v2/prepare" "$root/empty-target-build-v2/merge-targets" "$bin"/* "$runtime/build/flex/control/control"
# The mock needs an admission-mode control command; refresh the fixture manifest
# to represent a collection produced with that executable from the start.
while IFS= read -r entry;do sha256sum "${entry#*  }";done < "$out/student-rollouts/inputs.sha256" > "$out/student-inputs.sha256"
cp "$out/student-inputs.sha256" "$out/student-rollouts/inputs.sha256"
driver="$project/datasets/visual-control/expanded-rooms-v1/admit-wide-student-rollouts.sh"
export PUPPYBOT_PROJECT="$mock" PUPPYBOT_WIDE_STUDENT_ADMISSION_WAIT_RUN="$root/capacity/run"
PUPPYBOT_WIDE_STUDENT_ADMISSION_OUT="$out/student-admitted" bash "$driver" > "$out/student-admitted.log" 2>&1
jq -e '.passed and .episodes==356 and .fittingHistories==241 and .validationHistories==115 and .addedStudentHistories==8 and .studentRollinActionsReplayed==2400 and .incompleteAddedEpisodes==8 and .existingDataBytePreserved and .existingTargetsBytePreserved and .newHistoriesIndependentlyAudited and .actorInputsUnchanged and (.automaticPromotion|not)' "$out/student-admitted/coverage.json" > /dev/null
jq '.passed=false' "$out/student-rollouts/goal-audit-0/result.json" > "$out/bad-student-audit.json";cp "$out/bad-student-audit.json" "$out/student-rollouts/goal-audit-0/result.json"
if PUPPYBOT_WIDE_STUDENT_ADMISSION_OUT="$out/student-rejected" bash "$driver" > "$out/student-rejected.log" 2>&1;then echo 'Failed teacher-goal audit was accepted.' >&2;exit 1;fi
[[ "$(< "$out/student-rejected/run.exit")" != 0 && ! -e "$out/student-rejected/coverage.json" ]]
echo 'Student admission checks split preservation and rejects failed teacher audits.'
