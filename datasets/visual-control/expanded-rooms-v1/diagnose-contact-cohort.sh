#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/expanded-rooms-v1"
cohort="$root/contact-cohort-v1"
out="$root/contact-cohort-diagnostic-v1"
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
for worker in {0..3};do
    /usr/bin/bash "$out/worker.sh" "$cohort" "$worker" "$out/worker-$worker" > "$out/worker-$worker.log" 2>&1
    /usr/bin/jq -e --argjson worker "$worker" '.audited and .worker==$worker and (.rows|length)==4 and all(.rows[];.fit==(.episode<3))' "$out/worker-$worker/result.json" > /dev/null
done
/usr/bin/jq -s '{audited:true,teacherUsesPrivilegedSimulatorStateOnlyForLabels:true,notStudentTaskPerformance:true,episodes:([.[].rows[]]|length),studentActions:([.[].rows[].studentActions]|add),afterBlocked:([.[].rows[].afterBlocked]|add),studentRepeated:([.[].rows[].studentRepeated]|add),teacherDirectionReversed:([.[].rows[].teacherDirectionReversed]|add),studentStillBlocked:([.[].rows[].studentStillBlocked]|add),fitting:([.[].rows[]|select(.fit)]),validation:([.[].rows[]|select(.fit|not)])}' "$out"/worker-{0,1,2,3}/result.json > "$out/result.json"
/usr/bin/jq -e '.audited and .episodes==16 and (.fitting|length)==12 and (.validation|length)==4' "$out/result.json" > /dev/null
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
echo 'Contact-supervision counts aggregated from four independently audited workers.'
