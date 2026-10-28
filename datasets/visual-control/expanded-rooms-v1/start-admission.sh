#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/expanded-rooms-v1"
original="$root/cohort-v1"
retry="$root/cohort-retry-v1"
out="$root/admission-v1"
trap 'status=$?; printf "%s\n" "$status" > "$out/launcher.exit"' EXIT
printf '%s\n' "$BASHPID" > "$out/launcher.pid"
cd "$project"
while [[ ! -f "$retry/launcher.exit" ]];do
    [[ -f "$retry/launcher.pid" ]] && kill -0 "$(< "$retry/launcher.pid")" || { echo 'Retry launcher disappeared without a terminal status.';exit 1; }
    /usr/bin/sleep 10
done
[[ -f "$original/run.exit" ]]
if [[ "$(< "$original/run.exit")" != 0 ]];then
    [[ -f "$retry/run.exit" && "$(< "$retry/run.exit")" == 0 ]] || { echo 'Collection retry did not pass; no dataset admitted.';exit 1; }
fi
/usr/bin/sha256sum -c "$out/recipe.sha256" > "$out/launcher-recipe.log"
bash "$out/finalize.sh"
