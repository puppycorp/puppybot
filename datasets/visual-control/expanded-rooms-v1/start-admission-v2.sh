#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/expanded-rooms-v1"
out="$root/admission-v2"
trap 'status=$?; printf "%s\n" "$status" > "$out/launcher.exit"' EXIT
printf '%s\n' "$BASHPID" > "$out/launcher.pid"
cd "$project"
for job in "$root/timeout-retry-v1/run" "$root/fitting-repair-v1/run";do
    while [[ ! -f "$job.exit" ]];do
        [[ -f "$job.pid" ]] && kill -0 "$(< "$job.pid")" || { echo "Process exited without status: $job";exit 1; }
        /usr/bin/sleep 10
    done
    [[ "$(< "$job.exit")" == 0 ]] || { echo "Recovery failed; no dataset admitted: $job";exit 1; }
done
/usr/bin/sha256sum -c "$out/recipe.sha256" > "$out/launcher-recipe.log"
bash "$out/finalize.sh"
