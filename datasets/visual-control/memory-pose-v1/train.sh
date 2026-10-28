#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/memory-pose-v1"
out="$root/models"
[[ ! -e "$out" ]]
trap 'status=$?; printf "%s\n" "$status" > "$root/train.exit"' EXIT
printf '%s\n' "$BASHPID" > "$root/train.pid"
[[ "$(< "$project/build/flex/sim/camera-event-v1/train.exit")" == 0 && "$(< "$project/build/flex/sim/odometry-aux-v1/accepted.exit")" == 0 && "$(< "$project/build/flex/sim/odometry-aux-v1/build-and-compat.exit")" == 0 ]]
cd "$project"
data="$project/build/flex/sim/late-search-v1/artifacts-v2/data172/data.bin"
[[ "$(/usr/bin/sha256sum "$data" | /usr/bin/cut -d' ' -f1)" == 05032e0eb2a4a98a7f0146db66195792b2c22fe3bda3138039e9c721bc69b284 ]]
/usr/bin/sha256sum -c "$root/runtime.sha256" > "$root/runtime-checked.log"
/usr/bin/sha256sum -c "$root/recipes.sha256" > "$root/recipes-checked.log"
/usr/bin/jq -e '.passed and .parameters==324313' "$root/gradient-contracts/result.json" > /dev/null
/usr/bin/jq -e '.passed and .parameters==324829' "$root/pose-event-gradient-contracts/result.json" > /dev/null
/usr/bin/jq -e '.passed and .complete172CorpusAndTargetsAccepted' "$root/preflight.json" > /dev/null
[[ "$(/usr/bin/sha256sum "$project/build/flex/sim/odometry-aux-v1/accepted/targets.bin" | /usr/bin/cut -d' ' -f1)" == ab0bc0582ad9d743593891b13db7b3478b8b6f32037c39a6e8059e17e69606d7 ]]
mkdir "$out"
cp -a "$root/runtime" "$out/runtime"
cp -a build/flex/sim/forward-contact-v2/policy-contact142-20 "$out/initial-policy"
cp -a build/flex/sim/start-pose-v1/models/native-path "$out/native-path"
cp -a "$root/recipes" "$out/recipes"
cp "$root/publish" "$root/core-match" "$out/"
export PATH="$out/native-path"
cd "$out/runtime"
pids=()
for arm in eventOnly eventPose;do
    (
        trap 'status=$?; printf "%s\n" "$status" > "$out/'"$arm"'.exit"' EXIT
        printf '%s\n' "$BASHPID" > "$out/$arm-parent.pid"
        extra=(--event-aux);if [[ "$arm" == eventPose ]];then extra+=(--memory-pose "$project/build/flex/sim/odometry-aux-v1/accepted");fi
        ./build/flex/control/control train --initial-policy "$out/initial-policy" --data "$data" --output "$out/$arm" --epochs 40 --batch 2 --learning-rate-micros 100 --seed 197 --checkpoint-every 1 "${extra[@]}" > "$out/$arm.log" 2>&1
    ) &
    pids+=("$!")
done
status=0
for pid in "${pids[@]}";do if ! wait "$pid";then status=1;fi;done
(( status==0 ))
"$out/core-match" "$out/initial-policy/weights.bin" "$out/eventOnly/initial.bin" "$out/initial-eventOnly.json"
"$out/core-match" "$out/eventOnly/initial.bin" "$out/eventPose/initial.bin" "$out/initial-eventPose.json"
/usr/bin/jq -e '.passed and .extraTrainingParameters==129' "$out/initial-eventOnly.json" > /dev/null
/usr/bin/jq -e '.passed and .originalParameters==324313 and .extraTrainingParameters==516' "$out/initial-eventPose.json" > /dev/null
/usr/bin/cmp "$out/"{eventOnly,eventPose}/first-order.bin
/usr/bin/cmp "$out/"{eventOnly,eventPose}/final-order.bin
cd "$project"
/usr/bin/sha256sum -c "$root/recipes.sha256" > "$root/recipes-after-training.log"
/usr/bin/sha256sum -c "$root/runtime.sha256" > "$root/runtime-after-training.log"
echo 'Matched-order memory-pose comparison trained; actual task performance still requires native evaluation.'
