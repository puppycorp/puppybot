#!/usr/bin/env bash
# Only independently checked complete return pairs may enter the corpus.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]];mkdir "$out"
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-return-reuse-admission.sh" "$out/old-fixture" > /dev/null
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-wide-return-cohort.sh" "$out/new-fixture" > /dev/null
mock="$out/old-fixture/mock";base="$mock/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1";bin="$root/source/admission-cohort-v3/bin";runtime="$root/coverage-return-tests-v1/runtime"
ln -s "$out/old-fixture/reused" "$root/return-reuse-admission-v1"
ln -s "$out/new-fixture/return-cohort" "$root/wide-return-cohort-v1"
ln -s "$out/new-fixture/mock/build/flex/sim/expanded-rooms-v1/large-model-v1/wide-return-catalog-v1" "$root/wide-return-catalog-v1"
printf '{}\n' > "$out/old-fixture/reused/targets/receipt.json"
cat > "$base/return-labels-v1/survey" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "$4" == 2 ]];printf '{}\n' > "$3";printf 'candidates\n' > "$6"
EOF
chmod +x "$base/return-labels-v1/survey"
cat > "$bin/data-preserve-added" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${PUPPYBOT_TEST_ONE_WORKER:-0}" == 1 ]];then printf '{"passed":true,"existingHistoriesPreserved":350,"expandedHistories":352,"expandedFittingHistories":239}\n' > "$3";else printf '{"passed":true,"existingHistoriesPreserved":350,"expandedHistories":354,"expandedFittingHistories":240}\n' > "$3";fi
EOF
cp "$bin/data-preserve-added" "$bin/target-preserve-added"
cat > "$bin/preflight-expanded-targets" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${PUPPYBOT_TEST_ONE_WORKER:-0}" == 1 ]];then printf '{"passed":true,"episodes":352,"fittingHistories":239,"validationHistories":113,"actorInputsUnchanged":true}\n' > "$3";else printf '{"passed":true,"episodes":354,"fittingHistories":240,"validationHistories":114,"actorInputsUnchanged":true}\n' > "$3";fi
EOF
cat > "$runtime/build/flex/control/control" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == verify-data ]];shift;start="";count=""
while (( $# ));do case "$1" in --output) output="$2";shift 2;; --data) data="$2";shift 2;; --audit-start) start="$2";shift 2;; --audit-count) count="$2";shift 2;; *) shift;; esac;done
total=354;actions=120
if [[ "${PUPPYBOT_TEST_ONE_WORKER:-0}" == 1 ]];then [[ "$count" == 1 && ( "$start" == 238 || "$start" == 351 ) ]];total=352;actions=60;else [[ "$count" == 2 && ( "$start" == 238 || "$start" == 352 ) ]];fi
mkdir "$output";sha="$(sha256sum "$data" | cut -d' ' -f1)"
jq -n --arg sha "$sha" --argjson total "$total" --argjson count "$count" --argjson actions "$actions" '{passed:true,datasetEpisodes:$total,episodes:$count,dataSHA256:$sha,studentPolicies256:$count,studentRollinCommandsReplayed:$actions,studentRollinMaxAbsError:0,denseOracleLabels:true,taskEventHintAbsent:true}' > "$output/result.json"
EOF
chmod +x "$bin"/* "$runtime/build/flex/control/control"
driver="$project/datasets/visual-control/expanded-rooms-v1/admit-wide-return-cohort.sh"
export PUPPYBOT_PROJECT="$mock"
PUPPYBOT_WIDE_RETURN_ADMISSION_OUT="$out/admitted" bash "$driver" > "$out/admitted.log" 2>&1
jq -e '.passed and .episodes==354 and .fittingHistories==240 and .validationHistories==114 and .addedReturnHistories==4 and .studentReturnActionsReplayed==240 and .teacherAssisted and (.autonomousWholeEpisodeSuccessClaimed|not) and (.automaticPromotion|not)' "$out/admitted/coverage.json" > /dev/null
ln -sfn "$out/new-fixture/partial" "$root/wide-return-cohort-v1"
PUPPYBOT_TEST_ONE_WORKER=1 PUPPYBOT_WIDE_RETURN_ADMISSION_OUT="$out/admitted-one" bash "$driver" > "$out/admitted-one.log" 2>&1
jq -e '.passed and .episodes==352 and .fittingHistories==239 and .validationHistories==113 and .addedReturnHistories==2 and .studentReturnActionsReplayed==120 and .teacherAssisted and (.automaticPromotion|not)' "$out/admitted-one/coverage.json" > /dev/null
ln -sfn "$out/new-fixture/return-cohort" "$root/wide-return-cohort-v1"
jq '.successfulWorkers=0' "$out/new-fixture/return-cohort/summary.json" > "$out/no-workers.json";cp "$out/no-workers.json" "$out/new-fixture/return-cohort/summary.json"
if PUPPYBOT_WIDE_RETURN_ADMISSION_OUT="$out/rejected" bash "$driver" > "$out/rejected.log" 2>&1;then echo 'Empty return cohort was admitted.' >&2;exit 1;fi
[[ "$(< "$out/rejected/run.exit")" != 0 && ! -e "$out/rejected/coverage.json" ]]
echo 'Wide return admission checks preserved splits and rejects empty cohorts.'
