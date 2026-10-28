#!/usr/bin/env bash
# Reused return data must preserve the corpus and reject duplicate scenes.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-wide-student-admission.sh" "$out" > /dev/null
mock="$out/mock";base="$mock/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1";cohort="$root/coverage-return-cohort-v1";worker="$cohort/worker-0";prior="$root/wide-student-catalog-v2";runtime="$root/coverage-return-tests-v1/runtime";bin="$root/source/admission-cohort-v3/bin";labels="$root/coverage-return-admission-v1/labels-0/targets"
mkdir -p "$worker/packed" "$worker/verified" "$labels" "$runtime/build/flex/control" "$root/coverage-scale-source-v1/audit-resources/datasets/visual-control/expanded-rooms-v1" "$mock/datasets/visual-control/expanded-rooms-v1"
printf '0\n' > "$cohort/run.exit";printf '0\n' > "$prior/run.exit"
printf '{"complete":true,"successfulWorkers":1,"teacherAssisted":true,"autonomousWholeEpisodeSuccessClaimed":false}\n' > "$cohort/summary.json"
printf '{"passed":true,"studentReturnActionsReplayed":120,"studentReturnCompletions":0,"teacherAssisted":true,"automaticMerge":false}\n' > "$cohort/worker-0.json"
printf 'return data\n' > "$worker/packed/data.bin";new_sha="$(sha256sum "$worker/packed/data.bin" | cut -d' ' -f1)"
jq -n --arg sha "$new_sha" '{passed:true,episodes:2,datasetEpisodes:2,dataSHA256:$sha,studentPolicies256:2,studentRollinCommandsReplayed:120,studentRollinMaxAbsError:0,denseOracleLabels:true,datasetInputsMatchActualRGBAndOwnFeedback:true,executedCommandsMatchRecordings:true,taskEventHintAbsent:true}' > "$worker/verified/result.json"
printf 'targets\n' > "$labels/targets.bin";jq -n --arg sha "$new_sha" '{passed:true,sourceDataSHA256:$sha,allowEmptyCandidateSplits:true,projectionAndPixelsIndependentlyRechecked:true,actorInputsUnchanged:true}' > "$labels/receipt.json"
printf 'original auditor\n' > "$mock/datasets/visual-control/expanded-rooms-v1/audit-coverage-teacher-v2.sh"
cp "$mock/datasets/visual-control/expanded-rooms-v1/audit-coverage-teacher-v2.sh" "$root/coverage-scale-source-v1/audit-resources/datasets/visual-control/expanded-rooms-v1/audit-coverage-teacher-v2.sh"
sha256sum "$mock/datasets/visual-control/expanded-rooms-v1/audit-coverage-teacher-v2.sh" > "$cohort/inputs.sha256"
sha256sum "$prior/catalog/0/case.json" > "$cohort/prior-inputs.sha256"
for i in 0 1;do
    run="$worker/runs/expert-$i";mkdir -p "$run/scene";for file in case.json environment.bin;do printf 'return %s %s\n' "$i" "$file" > "$run/scene/$file";done
    printf '{"studentBeginsAfterConsumption":true,"studentStartAction":2,"studentActions":60,"studentCompletedBeforeHandoff":false,"denseOracleLabels":true,"teacherPlannerUsesPrivilegedGeometry":true}\n' > "$run/supervision.json"
    bash "$out/audit/audit.sh" "$run" "$worker/goal-audit-$i"
done
cat > "$bin/data-preserve-added" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '{"passed":true,"existingHistoriesPreserved":348,"expandedHistories":350,"expandedFittingHistories":238}\n' > "$3"
EOF
cp "$bin/data-preserve-added" "$bin/target-preserve-added"
cat > "$bin/preflight-expanded-targets" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '{"passed":true,"episodes":350,"fittingHistories":238,"validationHistories":112,"actorInputsUnchanged":true}\n' > "$3"
EOF
cat > "$runtime/build/flex/control/control" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == verify-data ]];shift;start="";count=""
while (( $# ));do case "$1" in --output) output="$2";shift 2;; --data) data="$2";shift 2;; --audit-start) start="$2";shift 2;; --audit-count) count="$2";shift 2;; *) shift;; esac;done
[[ "$count" == 1 && ( "$start" == 237 || "$start" == 349 ) ]];mkdir "$output";sha="$(sha256sum "$data" | cut -d' ' -f1)"
jq -n --arg sha "$sha" '{passed:true,datasetEpisodes:350,episodes:1,dataSHA256:$sha,studentPolicies256:1,studentRollinCommandsReplayed:60,studentRollinMaxAbsError:0,denseOracleLabels:true,datasetInputsMatchActualRGBAndOwnFeedback:true,executedCommandsMatchRecordings:true,taskEventHintAbsent:true}' > "$output/result.json"
EOF
printf 'simulator\n' > "$runtime/build/flex/control/simulator";chmod +x "$runtime/build/flex/control/control" "$bin"/*
driver="$project/datasets/visual-control/expanded-rooms-v1/admit-return-reuse.sh"
export PUPPYBOT_PROJECT="$mock" PUPPYBOT_RETURN_REUSE_AUDIT="$out/audit/audit.sh" PUPPYBOT_RETURN_REUSE_WAIT_RUN="$root/capacity/run"
PUPPYBOT_RETURN_REUSE_OUT="$out/reused" bash "$driver" > "$out/reused.log" 2>&1
jq -e '.passed and .episodes==350 and .fittingHistories==238 and .validationHistories==112 and .addedReturnHistories==2 and .studentReturnActionsReplayed==120 and .teacherAssisted and (.autonomousWholeEpisodeSuccessClaimed|not) and (.automaticPromotion|not)' "$out/reused/coverage.json" > /dev/null
cp "$prior/catalog/0/case.json" "$worker/runs/expert-0/scene/case.json"
if PUPPYBOT_RETURN_REUSE_OUT="$out/reused-duplicate" bash "$driver" > "$out/reused-duplicate.log" 2>&1;then echo 'Duplicate return scene was accepted.' >&2;exit 1;fi
[[ "$(< "$out/reused-duplicate/run.exit")" != 0 && ! -e "$out/reused-duplicate/coverage.json" ]]
echo 'Return reuse checks preserved splits and rejects duplicate scenes.'
