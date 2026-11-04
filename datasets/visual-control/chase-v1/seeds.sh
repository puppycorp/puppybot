#!/usr/bin/env bash
# Train one configuration with several seeds and score every model on the 32 test games.
# Usage: seeds.sh ROOT NAME COUNT TRAIN_FLAGS... (PUPPYBOT_EVAL_FLAGS adds evaluate.sh flags such as --fetch)
# Seed s (0..COUNT-1) trains with --seed 7+s into ROOT/NAME-sS; each evaluation overlaps the next training,
# except on HIP, where policy inference sharing the GPU with training stalls past the 45 s stream limit.
# Retrains of one configuration differ by about 0.6 bricks per minute, so compare seed means, not single runs.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
root="${1:?Output root required}"; name="${2:?Configuration name required}"; count="${3:?Seed count required}"; shift 3
read -r -a eval_flags <<< "${PUPPYBOT_EVAL_FLAGS:-}"
(( count >= 1 && count <= 16 )) || { echo 'Seed count must be 1..16.' >&2; exit 1; }
cd "$project"
mkdir -p "$root"
pids=(); status=0
for ((s=0; s<count; s++)); do
    out="$root/$name-s$s"
    nice -n 10 build/flex/control/control train --output "$out" --seed $((7 + s)) "$@" > "$out.log" 2>&1 || { echo "Training $name seed $s failed; see $out.log" >&2; exit 1; }
    PUPPYBOT_PROJECT="$project" bash datasets/visual-control/chase-v1/evaluate.sh "$root/eval" "$name-s$s" "$out" "${eval_flags[@]}" > "$out.eval.log" 2>&1 & pids+=("$!")
    [[ "$(cat "$out/backend.txt")" != hip ]] || { wait "${pids[-1]}" || status=1; unset 'pids[-1]'; }
done
for pid in "${pids[@]}"; do wait "$pid" || status=1; done
(( status == 0 )) || { echo "An evaluation of $name failed; see $root/$name-s*.eval.log" >&2; exit 1; }
jq -s --arg name "$name" 'def stats(f): (map(f)) as $v | ($v|add/length) as $m | {mean:$m,sd:(if ($v|length)>1 then ($v|map((.-$m)*(.-$m))|add/(length-1)|sqrt) else null end),runs:$v};
  {configuration:$name,seeds:length,reachesPerMinute:stats(.meanReachesPerMinute)}
  + if .[0].meanDeliveriesPerMinute == null then {} else {deliveriesPerMinute:stats(.meanDeliveriesPerMinute)} end' \
  $(for ((s=0; s<count; s++)); do printf '%s ' "$root/eval/score-$name-s$s.json"; done) > "$root/score-$name.json"
jq -c . "$root/score-$name.json"
