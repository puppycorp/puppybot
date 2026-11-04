#!/usr/bin/env bash
set -euo pipefail
project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$project"
output="${1:?New output directory required}"
mkdir "$output"
output="$(cd "$output" && pwd)"
build/flex/control/pose-fixtures "$output/fixture"
for arm in plain regularized repeat; do
    extra=(); if [[ "$arm" != plain ]]; then extra+=(--reversal-penalty-milli 1000); fi
    build/flex/control/control train --data "$output/fixture/data.bin" --output "$output/$arm" --epochs 1 --batch 1 --learning-rate-micros 100 --seed 7 --from-scratch --categorical "${extra[@]}" > "$output/$arm.log" 2>&1
done
cmp "$output/plain/initial.bin" "$output/regularized/initial.bin"
for file in initial.bin first-gradients.bin first-after.bin last.bin weights.bin; do cmp "$output/regularized/$file" "$output/repeat/$file"; done
if cmp -s "$output/plain/first-gradients.bin" "$output/regularized/first-gradients.bin"; then echo 'Reversal loss did not change gradients.' >&2; exit 1; fi
jq -n --slurpfile plain "$output/plain/curves.jsonl" --slurpfile regularized "$output/regularized/curves.jsonl" '$regularized[0].trainingLoss==$plain[0].trainingLoss and $regularized[0].validationLoss==$plain[0].validationLoss and $regularized[1].trainingLoss>$plain[1].trainingLoss and $regularized[-1].optimizerSteps==1' | jq -e . > /dev/null
jq -e '.reversalPenaltyMilli==1000 and (.taskFeedback|not)' "$output/regularized/receipt.json" > /dev/null
jq -e 'has("reversalPenaltyMilli")|not' "$output/plain/receipt.json" > /dev/null
if build/flex/control/control train --data "$output/fixture/data.bin" --output "$output/continuous" --epochs 1 --batch 1 --from-scratch --reversal-penalty-milli 1000 > "$output/continuous.log" 2>&1; then echo 'Continuous action model accepted reversal loss.' >&2; exit 1; fi
rg -Fq 'reversal penalty requires categorical actions' "$output/continuous/training.log"
echo 'Reversal training is deterministic, affects gradients and rejects continuous actions.'
