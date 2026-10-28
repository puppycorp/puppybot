#!/usr/bin/env bash
# Independent student-control audit rejects unaccounted teacher actions.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
PUPPYBOT_PROJECT="$project" bash "$project/datasets/visual-control/expanded-rooms-v1/test-wide-student-rollouts.sh" "$out" > /dev/null
driver="$project/datasets/visual-control/expanded-rooms-v1/audit-wide-student-control.sh";collection="$out/student-rollouts"
bash "$driver" "$collection" "$out/control-audit" > "$out/control-audit.log" 2>&1
jq -e '.passed and .episodes==8 and .studentControlledActions==2400 and .teacherTakeoverAbsent and .independentPhysicsReplayNotPerformed' "$out/control-audit/summary.json" > /dev/null
jq '.studentActions=299' "$collection/runs/expert-0/supervision.json" > "$out/altered-supervision.json";cp "$out/altered-supervision.json" "$collection/runs/expert-0/supervision.json"
if bash "$driver" "$collection" "$out/bad-control" > "$out/bad-control.log" 2>&1;then echo 'Unaccounted teacher actions were accepted.' >&2;exit 1;fi
[[ "$(< "$out/bad-control/run.exit")" != 0 && ! -e "$out/bad-control/summary.json" ]]
echo 'Independent action audit rejects teacher takeover.'
