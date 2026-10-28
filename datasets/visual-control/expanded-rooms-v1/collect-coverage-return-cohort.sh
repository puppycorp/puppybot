#!/usr/bin/env bash
# Teacher searches; the student controls a dense return window before recovery.
# Failed worker pairs retain their partial recordings and are never admitted.
set -euo pipefail
reject_known_hash() {
    local status=0
    rg -Fxq "$1" "$2" || status=$?
    if (( status==0 ));then echo "Duplicate scene file: $1" >&2;exit 1;fi
    if (( status!=1 ));then echo "Cannot check prior hashes: $2" >&2;exit "$status";fi
}
project="${PUPPYBOT_PROJECT:?Project root required}"
base="$project/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1"
pilot="$root/coverage-return-pilot-60-v1";corpus="$root/coverage-v2-teacher-admission-v1"
runtime="$root/coverage-return-tests-v1/runtime";policy="$root/return-cohort-reversal-training-v1/policy"
generator="$root/correction-v1/generate-diverse";auditor="$project/datasets/visual-control/expanded-rooms-v1/audit-coverage-teacher-v2.sh";audit_jq="$project/datasets/visual-control/expanded-rooms-v1/audit-coverage-teacher-v2.jq"
out="${PUPPYBOT_COVERAGE_RETURN_COHORT_OUT:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
for job in "$pilot/run" "$corpus/run";do
    while [[ ! -f "$job.exit" ]];do [[ -f "$job.pid" ]] && kill -0 "$(< "$job.pid")" || { echo "$job ended without a status." >&2;exit 1; };sleep 20;done
    [[ "$(< "$job.exit")" == 0 ]] || { echo "$job failed; return collection not started." >&2;exit 1; }
done
jq -e '.passed and .episodes==2 and .teacherSearchesFirst and .studentReturnActionsReplayed>=100 and .teacherAssistedCompleted==2 and .teacherGoalsReconstructed and .actorInputsCheckedByReplay and (.autonomousWholeEpisodeSuccessClaimed|not)' "$pilot/summary.json" > /dev/null
data="$corpus/expanded/data.bin";data_sha="$(sha256sum "$data" | cut -d' ' -f1)";policy_sha="$(sha256sum "$policy/weights.bin" | cut -d' ' -f1)"
jq -e --arg sha "$data_sha" '.passed and .episodes==308 and .dataSHA256==$sha and .newHistoriesIndependentlyAudited and .actorInputsUnchanged' "$corpus/coverage.json" > /dev/null
jq -e --arg sha "$policy_sha" '.weightsSHA256==$sha and .memoryWidth==256 and (.taskFeedback|not)' "$policy/receipt.json" > /dev/null
"$generator" "$out/fit" 67 69 fit > "$out/generate-fit.log"
"$generator" "$out/validation" 167 169 validation > "$out/generate-validation.log"
mkdir "$out/catalog"
for ((worker=0;worker<2;worker++));do fit=$((67+worker));val=$((167+worker));mkdir "$out/catalog/$worker";cp -a "$out/fit/$fit/4" "$out/catalog/$worker/0";cp -a "$out/validation/$val/4" "$out/catalog/$worker/1";done
for ((i=0;i<308;i++));do for file in case.json environment.bin;do sha256sum "$corpus/expanded/expert-$i/scene/$file" | tee -a "$out/prior-inputs.sha256" | cut -d' ' -f1;done;done > "$out/prior-hashes.txt"
for layout in 18 19 20 21 22 23;do parent=generalization-benchmark-v1;if (( layout<20 ));then parent=unseen-benchmark-v2;fi
    for scene in {0..15};do for file in case.json environment.bin;do sha256sum "$base/$parent/scenes/$layout/$scene/$file" | tee -a "$out/prior-inputs.sha256" | cut -d' ' -f1;done;done
done >> "$out/prior-hashes.txt"
for i in {0..7};do for file in case.json environment.bin;do sha256sum "$root/coverage-v2-student-cohort-v1/catalog/$i/$file" | tee -a "$out/prior-inputs.sha256" | cut -d' ' -f1;done;done >> "$out/prior-hashes.txt"
for worker in 0 1;do for role in 0 1;do
    scene="$out/catalog/$worker/$role";layout=$((67+worker));fit=true;if (( role ));then layout=$((167+worker));fit=false;fi
    jq -e --argjson layout "$layout" --argjson fit "$fit" '.layoutId==$layout and .fit==$fit and (.rooms|length)==(1+($layout%2))' "$scene/layout.json" > /dev/null
    for file in case.json environment.bin;do digest="$(sha256sum "$scene/$file" | cut -d' ' -f1)";reject_known_hash "$digest" "$out/prior-hashes.txt";printf '%s\n' "$digest" >> "$out/prior-hashes.txt";done
done;done
sha256sum "$generator" "$runtime/build/flex/control/control" "$runtime/build/flex/control/simulator" "$runtime/build/flex/sim/puppybot.bin" "$policy/weights.bin" "$policy/policy" "$policy/receipt.json" "$data" "$corpus/coverage.json" "$pilot/summary.json" "$auditor" "$audit_jq" "$out"/catalog/{0,1}/{0,1}/{case.json,environment.bin,layout.json} > "$out/inputs.sha256"
find "$runtime/build/flex/control/kernels" -type f -print0 | sort -z | xargs -0 sha256sum >> "$out/inputs.sha256"
sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1 PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
cd "$runtime"
for worker in 0 1;do
    work="$out/worker-$worker";mkdir "$work";seed=$((1995000+worker*1000));reason=''
    if ! ./build/flex/control/control correct --policy "$policy" --scene-catalog "$out/catalog/$worker" --output "$work/runs" --episodes 2 --validation 1 --rollin 60 --rollin-min 60 --horizon 354 --label-rollin --return-rollin --coverage-teacher --seed "$seed" --large-model > "$work/collect.log" 2>&1;then reason=collection_failed
    elif ! ./build/flex/control/control pack-data --data "$work/runs/data.bin" --output "$work/packed" > "$work/pack.log" 2>&1;then reason=pack_failed
    elif ! ./build/flex/control/control verify-data --run "$work/runs" --data "$work/packed/data.bin" --output "$work/verified" --large-model > "$work/verify.log" 2>&1;then reason=replay_failed
    elif ! jq -e '.passed and .episodes==2 and .studentPolicies256==2 and .studentRollinCommandsReplayed>=2 and .studentRollinMaxAbsError==0 and .denseOracleLabels and .taskEventHintAbsent' "$work/verified/result.json" > /dev/null;then reason=replay_receipt_invalid
    else
        for i in 0 1;do
            if ! jq -e '.searchTeacher=="coverage-camera-v2" and .studentBeginsAfterConsumption and .studentStartAction>=1 and .studentActions>=1 and .studentActions<=60 and .denseOracleLabels' "$work/runs/expert-$i/supervision.json" > /dev/null;then reason=window_invalid;break;fi
            if ! bash "$auditor" "$work/runs/expert-$i" "$work/goal-audit-$i" > "$work/goal-audit-$i.log" 2>&1;then reason=goal_audit_failed;break;fi
        done
    fi
    if [[ -n "$reason" ]];then jq -n --argjson worker "$worker" --arg reason "$reason" '{worker:$worker,passed:false,reason:$reason,partialArtifactsRetained:true}' > "$out/worker-$worker.json";continue;fi
    jq -n --argjson worker "$worker" --slurpfile audit "$work/verified/result.json" --slurpfile a "$work/runs/expert-0/supervision.json" --slurpfile b "$work/runs/expert-1/supervision.json" '{worker:$worker,passed:true,studentReturnActionsReplayed:$audit[0].studentRollinCommandsReplayed,studentReturnCompletions:([$a[0],$b[0]]|map(select(.studentCompletedBeforeHandoff))|length),teacherAssisted:true,automaticMerge:false}' > "$out/worker-$worker.json"
done
sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
sha256sum -c "$out/prior-inputs.sha256" > "$out/prior-integrity-after.log"
jq -s '{complete:true,workers:length,successfulWorkers:(map(select(.passed))|length),failedWorkers:(map(select(.passed|not))|length),studentReturnActionsReplayed:([.[]|select(.passed)|.studentReturnActionsReplayed]|add // 0),studentReturnCompletions:([.[]|select(.passed)|.studentReturnCompletions]|add // 0),teacherAssisted:true,autonomousWholeEpisodeSuccessClaimed:false,automaticMerge:false,rows:.}' "$out"/worker-{0,1}.json > "$out/summary.json"
echo 'Coverage return-cohort workers finished; successful pairs require separate admission.'
