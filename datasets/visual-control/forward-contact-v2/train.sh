#!/usr/bin/env bash
set -euo pipefail
project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
root="$project/build/flex/sim/forward-contact-v2"
out="$root/models"
dataset="$project/datasets/visual-control/forward-contact-v2"
base="$project/build/flex/sim/start-pose-v1/artifacts/data132/data.bin"
new="$root/artifacts/data142/data.bin"
[[ ! -e "$out" && "$(< "$root/artifacts/dataset.exit")" == 0 ]]
/usr/bin/jq -e '.passed and .episodes==142 and .fittingHistories==112 and .validationHistories==30 and .existingHistoriesRetained==132 and .newFittingForwardContactFrames>=200' "$root/artifacts/coverage.json" > /dev/null
[[ "$(/usr/bin/sha256sum "$base" | /usr/bin/cut -d' ' -f1)" == d709d3378a1241c34ec885e1cce131dfa9cc5984208032a031ed315a4ba70eff ]]
[[ "$(/usr/bin/sha256sum "$new" | /usr/bin/cut -d' ' -f1)" == 852a80123d19dc45e6ec78587c5ea19c30388d9381c7d634faebb22501f349f9 ]]
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/train.exit"' EXIT
cd "$project"
cp -a build/flex/sim/start-pose-v1/models/runtime "$out/runtime"
cp -a build/flex/sim/start-pose-v1/policy-pose20 "$out/initial-policy"
cp -a build/flex/sim/start-pose-v1/models/native-path "$out/native-path"
mkdir "$out/recipes"
cp "$dataset/"{train.sh,publish.flex,protocol.json,evaluate.sh} "$out/recipes/"
cp datasets/visual-control/sequence-mirror-v1/benchmark.sh "$out/recipes/benchmark.sh"
build/flex/control/compiler "$dataset/publish.flex" -o "$out/publish"
/usr/bin/find "$out/runtime" -type f -print0 | /usr/bin/sort -z | /usr/bin/xargs -0 /usr/bin/sha256sum > "$out/runtime.sha256"
/usr/bin/sha256sum "$out/recipes/"* > "$out/recipes.sha256"
export PATH="$out/native-path"
cd "$out/runtime"
pids=()
for arm in baseline132 contact142; do
    (
        trap 'status=$?; printf "%s\n" "$status" > "$out/'"$arm"'.exit"' EXIT
        printf '%s\n' "$BASHPID" > "$out/$arm-parent.pid"
        data="$base";if [[ "$arm" == contact142 ]];then data="$new";fi
        ./build/flex/control/control train --initial-policy "$out/initial-policy" --data "$data" --output "$out/$arm" \
            --epochs 20 --batch 2 --learning-rate-micros 100 --seed 131 --checkpoint-every 10 > "$out/$arm.log" 2>&1
    ) &
    pids+=("$!")
done
status=0
for pid in "${pids[@]}"; do if ! wait "$pid";then status=1;fi;done
(( status==0 ))
/usr/bin/cmp "$out/"{baseline132,contact142}/initial.bin
/usr/bin/cmp "$out/baseline132/initial.bin" "$out/initial-policy/weights.bin"
/usr/bin/sha256sum -c "$out/runtime.sha256" > "$out/runtime-after-training.log"
echo 'Both contact-data ablation models trained; autonomous whole-episode evaluation is separate.'
