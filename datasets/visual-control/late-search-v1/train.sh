#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/late-search-v1"
out="$root/models"
dataset="${PUPPYBOT_RECIPES:-$project/datasets/visual-control/late-search-v1}"
base="$project/build/flex/sim/forward-contact-v2/artifacts/data142/data.bin"
artifacts="${PUPPYBOT_ARTIFACTS:-$root/artifacts}"
new="$artifacts/data172/data.bin"
[[ ! -e "$out" && "$(< "$artifacts/dataset.exit")" == 0 ]]
/usr/bin/jq -e '.passed and .episodes==172 and .fittingHistories==136 and .validationHistories==36 and .existingHistoriesRetained==142 and .newAuditedHistories==30' "$artifacts/coverage.json" > /dev/null
[[ "$(/usr/bin/sha256sum "$base" | /usr/bin/cut -d' ' -f1)" == 852a80123d19dc45e6ec78587c5ea19c30388d9381c7d634faebb22501f349f9 ]]
[[ "$(/usr/bin/sha256sum "$new" | /usr/bin/cut -d' ' -f1)" == "$(/usr/bin/jq -r '.dataSHA256' "$artifacts/coverage.json")" ]]
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/train.exit"' EXIT
printf '%s\n' "$BASHPID" > "$root/train.pid"
cd "$project"
cp -a "$root/training-runtime" "$out/runtime"
cp -a build/flex/sim/forward-contact-v2/policy-contact142-20 "$out/initial-policy"
cp -a build/flex/sim/start-pose-v1/models/native-path "$out/native-path"
mkdir "$out/recipes"
cp "$dataset/"{train.sh,publish.flex,protocol.json,evaluate.sh,benchmark.sh} "$out/recipes/"
cp "$root/publish" "$out/publish"
/usr/bin/find "$out/runtime" -type f -print0 | /usr/bin/sort -z | /usr/bin/xargs -0 /usr/bin/sha256sum > "$out/runtime.sha256"
/usr/bin/sha256sum "$out/recipes/"* "$out/publish" > "$out/recipes.sha256"
export PATH="$out/native-path"
cd "$out/runtime"
pids=()
for arm in baseline142 late172; do
    (
        trap 'status=$?; printf "%s\n" "$status" > "$out/'"$arm"'.exit"' EXIT
        printf '%s\n' "$BASHPID" > "$out/$arm-parent.pid"
        data="$base";if [[ "$arm" == late172 ]];then data="$new";fi
        ./build/flex/control/control train --initial-policy "$out/initial-policy" --data "$data" --output "$out/$arm" \
            --epochs 20 --batch 2 --learning-rate-micros 100 --seed 149 --checkpoint-every 10 > "$out/$arm.log" 2>&1
    ) &
    pids+=("$!")
done
status=0
for pid in "${pids[@]}"; do if ! wait "$pid";then status=1;fi;done
(( status==0 ))
/usr/bin/cmp "$out/"{baseline142,late172}/initial.bin
/usr/bin/cmp "$out/baseline142/initial.bin" "$out/initial-policy/weights.bin"
/usr/bin/sha256sum -c "$out/runtime.sha256" > "$out/runtime-after-training.log"
/usr/bin/sha256sum -c "$out/recipes.sha256" > "$out/recipes-after-training.log"
echo 'Both later-search comparison arms trained; autonomous task evaluation is separate.'
