#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/expanded-rooms-v1"
source="$root/timeout-retry-v1"
out="$root/timeout-individual-audit-v1"
[[ "$(< "$source/run.exit")" == 1 ]]
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
printf '%s\n' "$BASHPID" > "$out/run.pid"
cd "$project"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
export PATH="$out/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
export PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000
sha="$(/usr/bin/sha256sum "$source/packed-0/data.bin" | /usr/bin/cut -d' ' -f1)"
cd "$out/runtime"
for episode in {0..4};do
    status=0
    ./build/flex/control/control verify-data --run "$source/runs/0" --data "$source/packed-0/data.bin" --output "$out/audit-$episode" --audit-start "$episode" --audit-count 1 > "$out/audit-$episode.log" 2>&1 || status=$?
    if (( status==0 ));then
        /usr/bin/jq -e --arg sha "$sha" --argjson episode "$episode" '.passed and .episodes==1 and .datasetEpisodes==5 and .firstEpisode==$episode and .dataSHA256==$sha and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .denseOracleLabels and .taskEventHintAbsent' "$out/audit-$episode/result.json" > /dev/null
    fi
    printf '%s\n' "$status" > "$out/audit-$episode.exit"
done
cd "$project"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
echo 'Independent per-history audits finished; failure statuses are preserved individually.'
