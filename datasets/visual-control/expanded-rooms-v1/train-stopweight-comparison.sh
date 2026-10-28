#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
out="$base/stopweight-experiment-v1"
baseline="$base/return-training-v1"
unseen="$base/unseen-benchmark-v2"
data="$base/return-admission-v1/merged-7/data.bin"
targets="$base/return-labels-v1/targets"
[[ ! -e "$out/run.exit" && ! -e "$out/model" ]]
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
for name in contact-training-v1 return-training-v1 highres-development-run-v2 highres-full-data-v2; do
    while [[ ! -f "$base/$name/run.exit" ]]; do
        [[ -f "$base/$name/run.pid" ]] && kill -0 "$(< "$base/$name/run.pid")" || { echo "$name ended without a terminal status" >&2; exit 1; }
        /usr/bin/sleep 10
    done
done
[[ "$(< "$baseline/run.exit")" == 0 ]] || { echo 'The baseline comparison did not complete.' >&2; exit 1; }
cd "$project"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
/usr/bin/sha256sum -c "$unseen/inputs.sha256" > "$out/benchmark-integrity-before.log"
export PATH="$unseen/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
cd "$out/runtime"
./build/flex/control/control train --initial-policy "$baseline/initial" --data "$data" --output "$out/model" --epochs 21 --batch 2 --learning-rate-micros 100 --seed 197 --checkpoint-every 1 --event-aux --target-heatmap "$targets" --heat-actor --heat-stop-gradient --stop-weight-one > "$out/train.log" 2>&1
/usr/bin/cmp "$baseline/initial/weights.bin" "$out/model/seed.bin"
/usr/bin/jq -e '.stopLossWeight==1 and .speedTransitionLossWeight==8 and .heatmapActorGradientDetached and .heatmapActorFeatures and .targetHeatmapAuxiliary and .cameraEventAuxiliary and (.taskFeedback|not) and .epochs==21' "$out/model/receipt.json" > /dev/null
/usr/bin/jq -s -e 'length==22 and .[-1].epoch==21 and .[-1].optimizerSteps==1911' "$out/model/curves.jsonl" > /dev/null
cd "$project"
/usr/bin/bash "$unseen/benchmark.sh" "$out/model" stop-weight-one-236
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
/usr/bin/sha256sum -c "$unseen/inputs.sha256" > "$out/benchmark-integrity-after.log"
/usr/bin/bash "$project/datasets/visual-control/expanded-rooms-v1/select-episode-candidate.sh" "$out/selection" "$unseen/score-return-continued-236.json" "$baseline/expanded" "$unseen/score-stop-weight-one-236.json" "$out/model" > "$out/selection.log" 2>&1
/usr/bin/jq -n --slurpfile baseline "$unseen/score-return-continued-236.json" --slurpfile candidate "$unseen/score-stop-weight-one-236.json" --slurpfile gate "$out/selection/selection.json" '{method:"same 236 histories, initialization, seed and 1911 optimizer steps; stop loss multiplier changed from 5 to 1",baseline:$baseline[0],candidate:$candidate[0],selection:$gate[0],validationLossesNotComparable:true,finalLayoutsStillRequired:true,retainedPolicyOverwritten:false}' > "$out/comparison.json"
echo 'Matched stop-weight comparison completed; no automatic promotion.'
