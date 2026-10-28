#!/usr/bin/env bash
# Failed or altered return pairs must remain partial and unadmitted.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-wide-student-rollouts.sh" "$out" > /dev/null
mock="$out/mock";root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1";catalog="$root/wide-return-catalog-v1";runtime="$root/coverage-return-tests-v1/runtime"
mkdir -p "$catalog/catalog" "$runtime/build/flex/control/kernels" "$runtime/build/flex/sim"
printf '0\n' > "$catalog/run.exit";printf '{"passed":true,"episodes":4,"fittingLayouts":2,"validationLayouts":2,"openLayouts":2,"twoRoomLayouts":2,"uniqueStartingPoses":4,"wideHeading":true,"geometryChecked":true,"exactFilesDisjointFrom350CorpusAndOtherScenes":true,"reservedFinalUntouched":true,"physicalSpawnNotYetChecked":true}\n' > "$catalog/summary.json"
for ((i=0;i<4;i++));do
    mkdir "$catalog/catalog/$i";for file in case.json environment.bin;do printf 'return %s %s\n' "$i" "$file" > "$catalog/catalog/$i/$file";done
    jq -n --argjson i "$i" '{startPose:[$i,0,2]}' > "$catalog/catalog/$i/layout.json"
done
sha256sum "$catalog/summary.json" > "$catalog/inputs.sha256";sha256sum "$catalog/catalog/0/case.json" > "$catalog/prior-inputs.sha256"
cp "$root/workspace/build/flex/control/simulator" "$runtime/build/flex/control/simulator";printf 'model\n' > "$runtime/build/flex/sim/puppybot.bin";printf 'kernel\n' > "$runtime/build/flex/control/kernels/test"
cat > "$runtime/build/flex/control/control" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
command="$1";shift;rollin="";minimum="";horizon="";episodes="";validation="";label=false;returning=false;teacher=false
while (( $# ));do case "$1" in --output) output="$2";shift 2;; --scene-catalog) catalog="$2";shift 2;; --policy) policy="$2";shift 2;; --data) data="$2";shift 2;; --rollin) rollin="$2";shift 2;; --rollin-min) minimum="$2";shift 2;; --horizon) horizon="$2";shift 2;; --episodes) episodes="$2";shift 2;; --validation) validation="$2";shift 2;; --label-rollin) label=true;shift;; --return-rollin) returning=true;shift;; --coverage-teacher) teacher=true;shift;; *) shift;; esac;done
mkdir "$output"
if [[ "$command" == correct ]];then
    [[ "$rollin" == 60 && "$minimum" == 60 && "$horizon" == 354 && "$episodes" == 2 && "$validation" == 1 && "$label" == true && "$returning" == true && "$teacher" == true ]]
    worker="$(basename "$(dirname "$output")")";if [[ "${PUPPYBOT_TEST_FAIL_SECOND:-0}" == 1 && "$worker" == worker-1 ]];then exit 1;fi
    sha="$(sha256sum "$policy/weights.bin" | cut -d' ' -f1)";printf 'raw\n' > "$output/data.bin"
    for ((i=0;i<2;i++));do
        run="$output/expert-$i";mkdir -p "$run/scene";cp "$catalog/$i/case.json" "$run/scene/case.json";cp "$catalog/$i/environment.bin" "$run/scene/environment.bin"
        jq '{pose:.startPose}' "$catalog/$i/layout.json" > "$run/initial.json"
        if [[ "${PUPPYBOT_TEST_BAD_RETURN_POSE:-0}" == 1 && "$worker" == worker-0 && "$i" == 0 ]];then jq '.pose[0]=99' "$run/initial.json" > "$run/initial.tmp";mv "$run/initial.tmp" "$run/initial.json";fi
        jq -n --arg sha "$sha" '{studentMemoryWidth:256,studentWeightsSHA256:$sha,studentBeginsAfterConsumption:true,studentStartAction:10,studentActions:60,studentCompletedBeforeHandoff:false,denseOracleLabels:true,searchTeacher:"coverage-camera-v2",teacherPlannerUsesPrivilegedGeometry:true,searchGoalsUseUnseenBrickPosition:false}' > "$run/supervision.json"
    done
elif [[ "$command" == pack-data ]];then printf 'packed\n' > "$output/data.bin"
elif [[ "$command" == verify-data ]];then
    sha="$(sha256sum "$data" | cut -d' ' -f1)"
    jq -n --arg sha "$sha" '{passed:true,episodes:2,datasetEpisodes:2,dataSHA256:$sha,studentPolicies256:2,studentRollinCommandsReplayed:120,studentRollinMaxAbsError:0,denseOracleLabels:true,datasetInputsMatchActualRGBAndOwnFeedback:true,executedCommandsMatchRecordings:true,taskEventHintAbsent:true}' > "$output/result.json"
else exit 2;fi
EOF
chmod +x "$runtime/build/flex/control/control"
driver="$project/datasets/visual-control/expanded-rooms-v1/collect-wide-return-cohort.sh"
export PUPPYBOT_PROJECT="$mock" PUPPYBOT_WIDE_RETURN_AUDIT="$out/audit/audit.sh" PUPPYBOT_WIDE_RETURN_WAIT_RUN="$root/capacity/run"
PUPPYBOT_WIDE_RETURN_OUT="$out/return-cohort" bash "$driver" > "$out/return-cohort.log" 2>&1
jq -e '.complete and .workers==2 and .successfulWorkers==2 and .failedWorkers==0 and .studentReturnActionsReplayed==240 and .studentReturnCompletions==0 and .teacherAssisted and (.autonomousWholeEpisodeSuccessClaimed|not) and (.automaticMerge|not)' "$out/return-cohort/summary.json" > /dev/null
PUPPYBOT_TEST_FAIL_SECOND=1 PUPPYBOT_WIDE_RETURN_OUT="$out/partial" bash "$driver" > "$out/partial.log" 2>&1
jq -e '.complete and .successfulWorkers==1 and .failedWorkers==1 and .studentReturnActionsReplayed==120 and .rows[1].reason=="collection_failed" and (.automaticMerge|not)' "$out/partial/summary.json" > /dev/null
PUPPYBOT_TEST_BAD_RETURN_POSE=1 PUPPYBOT_WIDE_RETURN_OUT="$out/bad-pose" bash "$driver" > "$out/bad-pose.log" 2>&1
jq -e '.complete and .successfulWorkers==1 and .failedWorkers==1 and .rows[0].reason=="pose_changed" and (.automaticMerge|not)' "$out/bad-pose/summary.json" > /dev/null
echo 'Wide return cohort retains failed pairs and rejects altered physical starts.'
