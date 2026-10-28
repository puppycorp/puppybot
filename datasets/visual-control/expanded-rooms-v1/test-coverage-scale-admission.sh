#!/usr/bin/env bash
# Synthetic admission checks split counts, preserved data and audit rejection.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-coverage-scale-collection.sh" "$out" > /dev/null
mock="$out/mock";base="$mock/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1";old="$root/coverage-v2-student-admission-v1";bin="$root/source/admission-cohort-v3/bin"
ln -s "$out/good" "$root/coverage-scale-collection-v1"
mkdir -p "$old/expanded" "$old/targets" "$bin" "$base/return-labels-v1" "$root/empty-target-build-v2"
printf '0\n' > "$old/run.exit";printf 'old data\n' > "$old/expanded/data.bin";printf 'old targets\n' > "$old/targets/targets.bin";printf '{}\n' > "$old/targets/receipt.json"
sha="$(sha256sum "$old/expanded/data.bin" | cut -d' ' -f1)"
jq -n --arg sha "$sha" '{passed:true,episodes:316,fittingHistories:221,validationHistories:95,dataSHA256:$sha,existingDataBytePreserved:true,existingTargetsBytePreserved:true,newHistoriesIndependentlyAudited:true,teacherLabelsTrainingOnly:true,actorInputsUnchanged:true}' > "$old/coverage.json"
cat > "$base/return-labels-v1/survey" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '{}\n' > "$3";printf 'candidates\n' > "$6"
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
printf '{"passed":true,"existingHistoriesPreserved":316,"expandedHistories":348,"expandedFittingHistories":237}\n' > "$3"
EOF
cp "$bin/data-preserve-added" "$bin/target-preserve-added"
cat > "$bin/preflight-expanded-targets" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '{"passed":true,"episodes":348,"fittingHistories":237,"validationHistories":111,"actorInputsUnchanged":true}\n' > "$3"
EOF
chmod +x "$base/return-labels-v1/survey" "$root/empty-target-build-v2/prepare" "$root/empty-target-build-v2/merge-targets" "$bin"/*
driver="$project/datasets/visual-control/expanded-rooms-v1/admit-coverage-scale.sh"
export PUPPYBOT_PROJECT="$mock" PUPPYBOT_SCALE_ADMISSION_WAIT_RUN="$root/capacity/run"
PUPPYBOT_SCALE_ADMISSION_OUT="$out/admitted" bash "$driver" > "$out/admitted.log" 2>&1
jq -e '.passed and .episodes==348 and .fittingHistories==237 and .validationHistories==111 and .addedTeacherHistories==32 and .studentRollinActionsReplayed==32 and .incompleteAddedEpisodes==24 and .teacherAssistedCompleted==8 and .existingDataBytePreserved and .existingTargetsBytePreserved and .newHistoriesIndependentlyAudited and .actorInputsUnchanged and (.automaticPromotion|not)' "$out/admitted/coverage.json" > /dev/null
jq '.passed=false' "$out/good/goal-audit-0/result.json" > "$out/bad-audit.json";cp "$out/bad-audit.json" "$out/good/goal-audit-0/result.json"
if PUPPYBOT_SCALE_ADMISSION_OUT="$out/rejected" bash "$driver" > "$out/rejected.log" 2>&1;then echo 'Failed teacher-goal audit was accepted.' >&2;exit 1;fi
[[ "$(< "$out/rejected/run.exit")" != 0 && ! -e "$out/rejected/coverage.json" ]]
echo 'Scaled admission checks preserved splits and rejects failed teacher audits.'
