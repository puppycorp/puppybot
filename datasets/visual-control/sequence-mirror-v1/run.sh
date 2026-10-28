#!/usr/bin/env bash
set -euo pipefail
project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$project"
dataset="$project/datasets/visual-control/sequence-mirror-v1"
root="$project/build/flex/sim/sequence-mirror-v1"
models="$root/models"
[[ ! -e "$models" ]]
trap 'status=$?; printf "%s\n" "$status" > "$root/run.exit"' EXIT
bash "$dataset/train.sh" > "$root/train.log" 2>&1 &
training=$!
while [[ ! -f "$models/runtime.sha256" ]]; do
    if ! kill -0 "$training" 2>/dev/null; then wait "$training"; echo 'Training stopped before freezing its runtime'; exit 1; fi
    /usr/bin/sleep 2
done
mkdir "$models/evaluate-scripts"
cp "$dataset/"{evaluate,benchmark}.sh "$models/evaluate-scripts/"
/usr/bin/sha256sum "$models/evaluate-scripts/"*.sh > "$models/evaluate-scripts.sha256"
PUPPYBOT_PROJECT="$project" bash "$models/evaluate-scripts/evaluate.sh" > "$root/evaluate.log" 2>&1 &
evaluation=$!
status=0
if ! wait "$training"; then status=1; fi
if ! wait "$evaluation"; then status=1; fi
(( status==0 ))
