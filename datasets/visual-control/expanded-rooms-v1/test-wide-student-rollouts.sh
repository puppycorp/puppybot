#!/usr/bin/env bash
# Full student collection must reject wrong poses and teacher-controlled actions.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-coverage-scale-collection.sh" "$out" > /dev/null
mock="$out/mock";base="$mock/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1";catalog="$root/wide-student-catalog-v2";training="$root/coverage-scale-training-v1";evaluation="$root/coverage-scale-diverse-comparison-v1";runtime="$root/coverage-teacher-v2-runtime-v1/runtime"
mkdir -p "$catalog/catalog" "$training/policy" "$evaluation/candidate"
cp "$root/student-only-training-v1/policy/"* "$training/policy/"
sha="$(sha256sum "$training/policy/weights.bin" | cut -d' ' -f1)"
printf '0\n' > "$catalog/run.exit";printf '0\n' > "$training/run.exit";printf '0\n' > "$evaluation/run.exit"
printf '{"passed":true,"episodes":8,"fittingLayouts":4,"validationLayouts":4,"openLayouts":4,"twoRoomLayouts":4,"uniqueStartingPoses":8,"wideHeading":true,"geometryChecked":true,"exactFilesDisjointFrom348CorpusAndDevelopment":true,"reservedFinalUntouched":true,"physicalSpawnNotYetChecked":true}\n' > "$catalog/summary.json"
jq -n --arg sha "$sha" '{passed:true,episodes:8,auditedEpisodes:8,policyWeightsSHA256:$sha,rows:[range(0;8)|{auditPassed:true,suppliedMap:false,taskEventHint:false}]}' > "$evaluation/candidate/score.json"
for ((i=0;i<8;i++));do
    mkdir "$catalog/catalog/$i";for file in case.json environment.bin;do printf 'wide student %s %s\n' "$i" "$file" > "$catalog/catalog/$i/$file";done
    jq -n --argjson i "$i" '{startPose:[$i,0,2]}' > "$catalog/catalog/$i/layout.json"
done
sha256sum "$catalog/summary.json" > "$catalog/inputs.sha256";sha256sum "$catalog/catalog/0/case.json" > "$catalog/prior-inputs.sha256"
cat > "$runtime/build/flex/control/control" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
command="$1";shift;rollin="";minimum="";horizon="";episodes="";validation="";label=false;allow=false;teacher=false;large=false
while (( $# ));do case "$1" in --output) output="$2";shift 2;; --scene-catalog) catalog="$2";shift 2;; --policy) policy="$2";shift 2;; --data) data="$2";shift 2;; --rollin) rollin="$2";shift 2;; --rollin-min) minimum="$2";shift 2;; --horizon) horizon="$2";shift 2;; --episodes) episodes="$2";shift 2;; --validation) validation="$2";shift 2;; --label-rollin) label=true;shift;; --allow-incomplete) allow=true;shift;; --coverage-teacher) teacher=true;shift;; --large-model) large=true;shift;; *) shift;; esac;done
mkdir "$output"
if [[ "$command" == correct ]];then
    [[ "$rollin" == 300 && "$minimum" == 300 && "$horizon" == 300 && "$episodes" == 8 && "$validation" == 4 && "$label" == true && "$allow" == true && "$teacher" == true && "$large" == true ]]
    sha="$(sha256sum "$policy/weights.bin" | cut -d' ' -f1)";printf 'raw\n' > "$output/data.bin";printf '{"studentRollinActions":2400}\n' > "$output/report.json"
    for ((i=0;i<8;i++));do
        run="$output/expert-$i";mkdir -p "$run/scene";cp "$catalog/$i/case.json" "$run/scene/case.json";cp "$catalog/$i/environment.bin" "$run/scene/environment.bin"
        pose="$i";if [[ "${PUPPYBOT_TEST_BAD_POSE:-0}" == 1 && "$i" == 0 ]];then pose=99;fi
        jq -n --argjson pose "$pose" '{pose:[$pose,0,2]}' > "$run/initial.json"
        actions=300;if [[ "${PUPPYBOT_TEST_BAD_ACTIONS:-0}" == 1 && "$i" == 0 ]];then actions=301;fi
        if [[ "${PUPPYBOT_TEST_TEACHER_TAKEOVER:-0}" == 1 && "$i" == 0 ]];then actions=299;fi
        jq -n --arg sha "$sha" --argjson actions "$actions" '{studentMemoryWidth:256,studentWeightsSHA256:$sha,studentBeginsAfterConsumption:false,studentStartAction:0,denseOracleLabels:true,allowIncomplete:true,scheduledRollinActions:300,studentActions:$actions,searchTeacher:"coverage-camera-v2",teacherPlannerUsesPrivilegedGeometry:true,searchGoalsUseUnseenBrickPosition:false,terminationReason:"horizon"}' > "$run/supervision.json"
        printf '{"found":false,"success":false,"steps":300,"pathM":1,"leftStartRoom":false}\n' > "$run/result.json"
        for ((step=0;step<300;step++));do printf '{}\n';done > "$run/decisions.jsonl"
    done
elif [[ "$command" == pack-data ]];then printf 'packed\n' > "$output/data.bin"
elif [[ "$command" == verify-data ]];then
    sha="$(sha256sum "$data" | cut -d' ' -f1)"
    jq -n --arg sha "$sha" '{passed:true,episodes:8,datasetEpisodes:8,studentPolicies256:8,studentRollinCommandsReplayed:2400,studentRollinMaxAbsError:0,datasetInputsMatchActualRGBAndOwnFeedback:true,executedCommandsMatchRecordings:true,denseOracleLabels:true,preActionAlignmentChecked:true,zeroPaddingChecked:true,taskEventHintAbsent:true,dataSHA256:$sha,incompleteEpisodes:8,incompleteEpisodesClaimedSuccessful:false}' > "$output/result.json"
else exit 2;fi
EOF
chmod +x "$runtime/build/flex/control/control"
driver="$project/datasets/visual-control/expanded-rooms-v1/collect-wide-student-rollouts.sh"
export PUPPYBOT_PROJECT="$mock" PUPPYBOT_WIDE_STUDENT_AUDIT="$out/audit/audit.sh" PUPPYBOT_WIDE_STUDENT_WAIT_RUN="$root/capacity/run"
PUPPYBOT_WIDE_STUDENT_COLLECT_OUT="$out/student-rollouts" bash "$driver" > "$out/student-rollouts.log" 2>&1
jq -e '.passed and .episodes==8 and .studentRollinActionsReplayed==2400 and .studentFound==0 and .studentReturns==0 and .incompleteEpisodes==8 and .fullyStudentControlled and .initialPhysicalPosesChecked and (.automaticMerge|not)' "$out/student-rollouts/summary.json" > /dev/null
for flag in PUPPYBOT_TEST_BAD_POSE PUPPYBOT_TEST_BAD_ACTIONS PUPPYBOT_TEST_TEACHER_TAKEOVER;do
    if env "$flag=1" PUPPYBOT_WIDE_STUDENT_COLLECT_OUT="$out/$flag" bash "$driver" > "$out/$flag.log" 2>&1;then echo "$flag was accepted." >&2;exit 1;fi
    [[ "$(< "$out/$flag/run.exit")" != 0 && ! -e "$out/$flag/summary.json" ]]
done
echo 'Wide student collection rejects altered poses, invalid counts and teacher takeover.'
