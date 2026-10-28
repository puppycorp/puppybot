#!/usr/bin/env bash
# Synthetic 32-episode collection must reject incorrect student provenance.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
mock="$out/mock";base="$mock/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1";catalog="$root/coverage-scale-catalog-v1";runtime="$root/coverage-teacher-v2-runtime-v1/runtime";policy="$root/student-only-training-v1/policy";pilot="$root/coverage-v2-teacher-cohort-v1"
mkdir -p "$catalog/catalog" "$runtime/build/flex/control/kernels" "$runtime/build/flex/sim" "$root/workspace/build/flex/control" "$policy" "$pilot" "$root/capacity" "$base/unseen-benchmark-v2/native-path" "$out/audit"
for ((i=0;i<32;i++));do mkdir "$catalog/catalog/$i";for f in case.json environment.bin;do printf '%s %s\n' "$i" "$f" > "$catalog/catalog/$i/$f";done;done
printf '0\n' > "$catalog/run.exit";printf '0\n' > "$pilot/run.exit";printf '0\n' > "$root/capacity/run.exit"
printf '{"passed":true,"episodes":32,"fittingLayouts":16,"validationLayouts":16,"openLayouts":16,"twoRoomLayouts":16,"uniqueStartingPoses":32,"geometryChecked":true,"exactCaseAndEnvironmentFilesDisjointFrom310And316CorporaAndDevelopment":true,"reservedFinalUntouched":true,"teacherEpisodesNotYetCollected":true}\n' > "$catalog/summary.json"
printf '{"passed":true,"episodes":8,"teacherAssistedCompleted":5,"teacherControlledAfterFirstAction":true,"teacherSearchGoalsReconstructed":true,"teacherLabelsTrainingOnly":true,"studentAutonomousSuccessClaimed":false}\n' > "$pilot/summary.json"
sha256sum "$catalog/summary.json" > "$catalog/inputs.sha256";sha256sum "$catalog/catalog/0/case.json" > "$catalog/prior-inputs.sha256"
printf 'simulator\n' > "$runtime/build/flex/control/simulator";cp "$runtime/build/flex/control/simulator" "$root/workspace/build/flex/control/simulator";printf 'model\n' > "$runtime/build/flex/sim/puppybot.bin";printf 'kernel\n' > "$runtime/build/flex/control/kernels/test"
printf 'weights\n' > "$policy/weights.bin";printf 'actor\n' > "$policy/policy";sha="$(sha256sum "$policy/weights.bin" | cut -d' ' -f1)"
jq -n --arg sha "$sha" '{weightsSHA256:$sha,memoryWidth:256,taskFeedback:false}' > "$policy/receipt.json"
cat > "$runtime/build/flex/control/control" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
command="$1";shift
while (( $# ));do case "$1" in --output) output="$2";shift 2;; --scene-catalog) catalog="$2";shift 2;; --policy) policy="$2";shift 2;; --data) data="$2";shift 2;; --audit-count) audit_count="$2";shift 2;; *) shift;; esac;done
mkdir "$output"
if [[ "$command" == correct ]];then
    sha="$(sha256sum "$policy/weights.bin" | cut -d' ' -f1)";printf 'raw\n' > "$output/data.bin";printf '{"teacherCompleted":8}\n' > "$output/report.json"
    for ((i=0;i<32;i++));do run="$output/expert-$i";mkdir -p "$run/scene";cp "$catalog/$i/case.json" "$run/scene/case.json";cp "$catalog/$i/environment.bin" "$run/scene/environment.bin"
        current="$sha";if [[ "${PUPPYBOT_TEST_BAD_POLICY:-0}" == 1 && "$i" == 0 ]];then current=wrong;fi
        jq -n --arg sha "$current" '{studentMemoryWidth:256,studentWeightsSHA256:$sha,studentBeginsAfterConsumption:false,studentStartAction:0,denseOracleLabels:true,allowIncomplete:true,scheduledRollinActions:1,studentActions:1,searchTeacher:"coverage-camera-v2",teacherPlannerUsesPrivilegedGeometry:true,searchGoalsUseUnseenBrickPosition:false,terminationReason:"horizon"}' > "$run/supervision.json"
    done
elif [[ "$command" == pack-data ]];then printf 'packed\n' > "$output/data.bin"
elif [[ "$command" == verify-data ]];then
    sha="$(sha256sum "$data" | cut -d' ' -f1)";count="${audit_count:-32}";total=32;incomplete=24;if [[ "$count" == 16 ]];then total=348;incomplete=12;fi
    jq -n --arg sha "$sha" --argjson count "$count" --argjson total "$total" --argjson incomplete "$incomplete" '{passed:true,episodes:$count,datasetEpisodes:$total,studentPolicies256:$count,studentRollinCommandsReplayed:$count,studentRollinMaxAbsError:0,datasetInputsMatchActualRGBAndOwnFeedback:true,executedCommandsMatchRecordings:true,denseOracleLabels:true,preActionAlignmentChecked:true,zeroPaddingChecked:true,taskEventHintAbsent:true,dataSHA256:$sha,incompleteEpisodes:$incomplete,incompleteEpisodesClaimedSuccessful:false}' > "$output/result.json"
else exit 2;fi
EOF
chmod +x "$runtime/build/flex/control/control"
cat > "$out/audit/audit.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
mkdir "$2";printf '{"passed":true,"brickPositionNotReadBySearchReconstruction":true,"oracleLabelsMatched":true,"actorInputsChecked":false}\n' > "$2/result.json";sha256sum "$2/result.json" > "$2/inputs.sha256"
EOF
printf 'audit jq\n' > "$out/audit/audit-coverage-teacher-v2.jq"
driver="$project/datasets/visual-control/expanded-rooms-v1/collect-coverage-scale.sh"
export PUPPYBOT_PROJECT="$mock" PUPPYBOT_SCALE_TEACHER_AUDIT="$out/audit/audit.sh" PUPPYBOT_SCALE_COLLECT_WAIT_RUN="$root/capacity/run"
PUPPYBOT_SCALE_COLLECT_OUT="$out/good" bash "$driver" > "$out/good.log" 2>&1
jq -e '.passed and .episodes==32 and .studentRollinActionsReplayed==32 and .teacherAssistedCompleted==8 and .incompleteEpisodes==24 and .teacherLabelsTrainingOnly and (.studentAutonomousSuccessClaimed|not) and (.automaticMerge|not)' "$out/good/summary.json" > /dev/null
if PUPPYBOT_TEST_BAD_POLICY=1 PUPPYBOT_SCALE_COLLECT_OUT="$out/bad" bash "$driver" > "$out/bad.log" 2>&1;then echo 'Incorrect student policy was accepted.' >&2;exit 1;fi
[[ "$(< "$out/bad/run.exit")" != 0 && ! -e "$out/bad/summary.json" ]]
echo 'Scaled teacher collection rejects incorrect student provenance.'
