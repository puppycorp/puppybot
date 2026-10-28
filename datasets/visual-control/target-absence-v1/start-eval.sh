#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?}"
root="$project/build/flex/sim/target-absence-v1"
[[ ! -e "$root/eval-launch.exit" ]]
trap 'status=$?; printf "%s\n" "$status" > "$root/eval-launch.exit"' EXIT
while [[ ! -x "$root/models/publish" || ! -f "$root/models/recipes/evaluate.sh" ]];do
    [[ ! -f "$root/train.exit" ]] || { echo 'Training ended before evaluator assets were ready';exit 1; }
    [[ -f "$root/train.pid" ]] && kill -0 "$(< "$root/train.pid")" || { echo 'Queued training handle missing';exit 1; }
    /usr/bin/sleep 5
done
bash "$root/models/recipes/evaluate.sh"
