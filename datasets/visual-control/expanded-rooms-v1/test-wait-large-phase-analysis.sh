#!/usr/bin/env bash
# Synthetic orchestration checks. No simulator or reserved scene is run.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="${1:?New output directory required}"
[[ ! -e "$out" ]]
mkdir -p "$out/policy" "$out/complete" "$out/failed" "$out/malformed"
printf 'synthetic weights\n' > "$out/policy/weights.bin"
printf 'synthetic binary\n' > "$out/policy/policy"
printf '{}\n' > "$out/policy/receipt.json"
printf 'synthetic probe\n' > "$out/probe"
sha="$(/usr/bin/sha256sum "$out/policy/weights.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -n --arg sha "$sha" '{episodes:32,completedRecordings:32,auditedEpisodes:32,rows:[range(0;32)|{caseIndex:.,recordingCompleted:true,auditPassed:true,policyWeightsSHA256:$sha,taskEventHint:false,suppliedMap:false}]}' > "$out/complete/score.json"
printf '0\n' > "$out/complete/run.exit"
printf '1\n' > "$out/failed/run.exit"
printf '0\n' > "$out/malformed/run.exit"
printf '{}\n' > "$out/malformed/score.json"
cat > "$out/analyzer" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
policy="$2"; result="$3"; shift 3
[[ $# == 32 ]]
for ((index=0;index<32;index++));do [[ "$1" == */"$index"/"$((9960000+index))" ]];shift;done
mkdir "$result"
sha="$(/usr/bin/sha256sum "$policy/weights.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -n --arg sha "$sha" '{weightsSHA256:$sha,episodes:32,rows:[range(0;32)|{replayExact:true}],synthetic:true}' > "$result/summary.json"
printf '0\n' > "$result/run.exit"
EOF
waiter="$project/datasets/visual-control/expanded-rooms-v1/wait-large-phase-analysis.sh"
/usr/bin/bash "$waiter" "$out/complete" "$out/policy" "$out/probe" "$out/analyzer" "$out/accepted" > "$out/accepted.log" 2>&1
/usr/bin/jq -e '.synthetic and .episodes==32' "$out/accepted/analysis/summary.json" > /dev/null
for kind in failed malformed;do
    if /usr/bin/bash "$waiter" "$out/$kind" "$out/policy" "$out/probe" "$out/analyzer" "$out/$kind-output" > "$out/$kind.log" 2>&1;then echo "$kind benchmark was accepted" >&2;exit 1;fi
    [[ "$(< "$out/$kind-output/run.exit")" == 1 && ! -e "$out/$kind-output/analysis" ]]
done
echo 'Synthetic phase analysis queue accepts complete evidence and rejects incomplete evidence.'
