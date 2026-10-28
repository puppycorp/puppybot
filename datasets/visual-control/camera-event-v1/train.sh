#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/camera-event-v1"
out="$root/models"
[[ ! -e "$out" ]]
trap 'status=$?; printf "%s\n" "$status" > "$root/train.exit"' EXIT
printf '%s\n' "$BASHPID" > "$root/train.pid"
while [[ ! -f "$project/build/flex/sim/transfer-v1/evaluate.exit" ]];do
    kill -0 189847 || { echo 'Transfer evaluator disappeared without terminal status';exit 1; }
    /usr/bin/sleep 5
done
[[ "$(< "$project/build/flex/sim/transfer-v1/evaluate.exit")" == 0 ]]
cd "$project"
data="$project/build/flex/sim/late-search-v1/artifacts-v2/data172/data.bin"
[[ "$(/usr/bin/sha256sum "$data" | /usr/bin/cut -d' ' -f1)" == 05032e0eb2a4a98a7f0146db66195792b2c22fe3bda3138039e9c721bc69b284 ]]
/usr/bin/sha256sum -c "$root/runtime.sha256" > "$root/runtime-checked.log"
/usr/bin/sha256sum -c "$root/recipes.sha256" > "$root/recipes-checked.log"
/usr/bin/jq -e '.passed and .parameters==324313' "$root/gradient-contracts/result.json" > /dev/null
mkdir "$out"
cp -a "$root/runtime" "$out/runtime"
cp -a build/flex/sim/forward-contact-v2/policy-contact142-20 "$out/initial-policy"
cp -a build/flex/sim/start-pose-v1/models/native-path "$out/native-path"
cp -a "$root/recipes" "$out/recipes"
cp "$root/publish" "$root/core-match" "$out/"
export PATH="$out/native-path"
cd "$out/runtime"
pids=()
for arm in plain cameraEvent;do
    (
        trap 'status=$?; printf "%s\n" "$status" > "$out/'"$arm"'.exit"' EXIT
        printf '%s\n' "$BASHPID" > "$out/$arm-parent.pid"
        extra=();if [[ "$arm" == cameraEvent ]];then extra+=(--event-aux);fi
        ./build/flex/control/control train --initial-policy "$out/initial-policy" --data "$data" --output "$out/$arm" --epochs 40 --batch 2 --learning-rate-micros 100 --seed 181 --checkpoint-every 10 "${extra[@]}" > "$out/$arm.log" 2>&1
    ) &
    pids+=("$!")
done
status=0
for pid in "${pids[@]}";do if ! wait "$pid";then status=1;fi;done
(( status==0 ))
for arm in plain cameraEvent;do "$out/core-match" "$out/initial-policy/weights.bin" "$out/$arm/initial.bin" "$out/initial-$arm.json";done
/usr/bin/jq -e '.passed and .extraTrainingParameters==0' "$out/initial-plain.json" > /dev/null
/usr/bin/jq -e '.passed and .extraTrainingParameters==129' "$out/initial-cameraEvent.json" > /dev/null
/usr/bin/cmp "$out/"{plain,cameraEvent}/first-order.bin
/usr/bin/cmp "$out/"{plain,cameraEvent}/final-order.bin
cd "$project"
/usr/bin/sha256sum -c "$root/recipes.sha256" > "$root/recipes-after-training.log"
/usr/bin/sha256sum -c "$root/runtime.sha256" > "$root/runtime-after-training.log"
echo 'Matched-order camera-event comparison trained; actual task performance still requires native evaluation.'
