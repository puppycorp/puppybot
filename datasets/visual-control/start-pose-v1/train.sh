#!/usr/bin/env bash
set -euo pipefail
project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
root="$project/build/flex/sim/start-pose-v1"
out="$root/models"
data="$root/artifacts/data132/data.bin"
dataset="$project/datasets/visual-control/start-pose-v1"
[[ ! -e "$out" && "$(< "$root/artifacts/dataset.exit")" == 0 ]]
/usr/bin/jq -e '.passed and .episodes==132 and .fittingHistories==104 and .validationHistories==28 and .existingHistoriesRetained==96 and .newAuditedHistories==36' "$root/artifacts/coverage.json" > /dev/null
[[ "$(/usr/bin/sha256sum "$data" | /usr/bin/cut -d' ' -f1)" == d709d3378a1241c34ec885e1cce131dfa9cc5984208032a031ed315a4ba70eff ]]
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/train.exit"' EXIT
cd "$project"
cp -a build/flex/sim/sequence-mirror-v1/models/runtime "$out/runtime"
cp -a build/flex/sim/sequence-mirror-v1/models/initial-policy "$out/initial-policy"
cp -a build/flex/sim/sequence-mirror-v1/models/native-path "$out/native-path"
mkdir "$out/recipes"
cp "$dataset/"{train.sh,publish.flex,protocol.json,evaluate.sh} "$out/recipes/"
cp datasets/visual-control/sequence-mirror-v1/benchmark.sh "$out/recipes/benchmark.sh"
build/flex/control/compiler "$dataset/publish.flex" -o "$out/publish"
/usr/bin/find "$out/runtime" -type f -print0 | /usr/bin/sort -z | /usr/bin/xargs -0 /usr/bin/sha256sum > "$out/runtime.sha256"
/usr/bin/sha256sum "$out/recipes/"* > "$out/recipes.sha256"
export PATH="$out/native-path"
cd "$out/runtime"
./build/flex/control/control train --initial-policy "$out/initial-policy" --data "$data" --output "$out/pose" \
    --epochs 20 --batch 2 --learning-rate-micros 100 --seed 107 --checkpoint-every 10 > "$out/pose.log" 2>&1
/usr/bin/cmp "$out/pose/initial.bin" "$out/initial-policy/weights.bin"
/usr/bin/sha256sum -c "$out/runtime.sha256" > "$out/runtime-after-training.log"
echo 'Expanded physical-pose model completed20 epochs; native whole-episode evaluation is separate.'
