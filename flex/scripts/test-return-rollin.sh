#!/usr/bin/env bash
set -euo pipefail

control="$1"
run="$(cd "$2" && pwd)"
data="$3"
mkdir "$4"
output="$(cd "$4" && pwd)"
source_digest="$(sha256sum "$run/expert-0/supervision.json")"
jq -e '.studentStartAction>=2 and .studentBeginsAfterConsumption==true and .studentActions>=1 and .denseOracleLabels==true' "$run/expert-0/supervision.json" >/dev/null
"$control" verify-data --run "$run" --data "$data" --output "$output/verified" \
    --audit-start 0 --audit-count 1 > "$output/verified.log" 2>&1
jq -e '.passed and .episodes==1 and .studentRollinCommandsReplayed>=1 and .studentRollinMaxAbsError==0' "$output/verified/result.json" >/dev/null

for variant in early late wrong-mode; do
    clone="$output/$variant"
    cp -al "$run" "$clone"
    expression='.studentStartAction-=1'
    message='return student window does not begin at the first consumed-brick frame'
    if [[ "$variant" == late ]]; then expression='.studentStartAction+=1'; fi
    if [[ "$variant" == wrong-mode ]]; then
        expression='.studentBeginsAfterConsumption=false'
        message='invalid student command window'
    fi
    # Replace the clone's metadata inode so the original hard link stays intact.
    jq "$expression" "$clone/expert-0/supervision.json" > "$clone/expert-0/supervision.changed.json"
    mv "$clone/expert-0/supervision.changed.json" "$clone/expert-0/supervision.json"
    if "$control" verify-data --run "$clone" --data "$data" --output "$output/rejected-$variant" \
        --audit-start 0 --audit-count 1 > "$output/$variant.log" 2>&1; then
        echo 'A forged student return window was accepted.' >&2
        exit 1
    fi
    if [[ "$(< "$output/$variant.log")" != *"$message"* || \
        -f "$output/rejected-$variant/result.json" ]]; then
        echo 'A forged student return window did not fail its boundary check.' >&2
        exit 1
    fi
done
[[ "$(sha256sum "$run/expert-0/supervision.json")" == "$source_digest" ]]
cat > "$output/result.json" <<'JSON'
{"passed":true,"runtime":"Flexscript","pythonRequired":false,"teacherWarmupAndStudentReturnReplayed":true,"earlyHandoffRejected":true,"lateHandoffRejected":true,"wrongModeRejected":true,"originalRecordingUnchanged":true}
JSON
echo 'Native return-window replay and handoff audit guards passed.'
