#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/expanded-rooms-v1"
cohort="$root/return-cohort-v1"
out="$root/return-cohort-diagnostic-v1"
[[ ! -e "$out/run.exit" ]]
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
printf '%s\n' "$BASHPID" > "$out/run.pid"
while [[ ! -f "$cohort/run.exit" ]];do
    [[ -f "$cohort/run.pid" ]] && kill -0 "$(< "$cohort/run.pid")" || { echo 'Collection disappeared without a terminal status.' >&2;exit 1; }
    /usr/bin/sleep 10
done
[[ "$(< "$cohort/run.exit")" == 0 ]] || { echo 'Collection did not pass; no aggregate diagnostic.' >&2;exit 1; }
cd "$project"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
for worker in {0..5};do
    adapter="$out/input-$worker"
    mkdir "$adapter"
    /usr/bin/ln -s "$cohort/runs/$worker" "$adapter/runs"
    /usr/bin/ln -s "$cohort/packed-$worker" "$adapter/packed"
    /usr/bin/ln -s "$cohort/verified-$worker" "$adapter/verified"
    /usr/bin/ln -s "$cohort/worker-$worker.exit" "$adapter/run.exit"
    /usr/bin/bash "$out/worker.sh" "$adapter" "$out/worker-$worker" > "$out/worker-$worker.log" 2>&1
    /usr/bin/jq --argjson worker "$worker" --slurpfile catalog "$cohort/catalog/report.json" '{dataSHA256,rows:[.rows[] as $row|$row+{worker:$worker,layout:([$catalog[0].records[]|select(.worker==$worker and .episode==$row.episode)][0].layout)}]}' "$out/worker-$worker/result.json" > "$out/worker-$worker.json"
    /usr/bin/jq -e --argjson worker "$worker" '(.rows|length)==2 and all(.rows[];.worker==$worker and .fit==(.episode==0) and .layout!=null)' "$out/worker-$worker.json" > /dev/null
done
/usr/bin/jq -s '{audited:true,teacherUsesPrivilegedSimulatorStateOnlyForLabels:true,notAutonomousWholeEpisodePerformance:true,episodes:([.[].rows[]]|length),studentReturnActions:([.[].rows[].studentReturnActions]|add),oracleDiffers:([.[].rows[].oracleDiffers]|add),validBoxVisionFrames:([.[].rows[].validBoxVisionFrames]|add),studentReturnsAfterTeacherApproach:([.[].rows[]|select(.studentReturnedAfterTeacherApproach)]|length),fitting:([.[].rows[]|select(.fit)]),validation:([.[].rows[]|select(.fit|not)])}' "$out"/worker-{0,1,2,3,4,5}.json > "$out/result.json"
/usr/bin/jq -e '.audited and .episodes==12 and (.fitting|length)==6 and (.validation|length)==6' "$out/result.json" > /dev/null
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
echo 'Student return-window diagnostics aggregated from six independently audited workers.'
