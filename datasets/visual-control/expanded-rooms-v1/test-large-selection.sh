#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
run="${1:?Completed 32-case benchmark required}"
policy="${2:?Scored large policy required}"
out="${3:?New output directory required}"
[[ ! -e "$out" ]]
mkdir "$out"
adapter="$project/datasets/visual-control/expanded-rooms-v1/prepare-large-selection.sh"
PUPPYBOT_PROJECT="$project" /usr/bin/bash "$adapter" "$run" "$policy" "$out/actual" actual
/usr/bin/jq -e '.reservedFinalStillRequired and (.retainedPolicyOverwritten|not)' "$out/actual/selection/selection.json" > /dev/null
for kind in failed-audit forged-score; do
    mkdir -p "$out/$kind/run"
    /usr/bin/cp "$run/score.json" "$out/$kind/run/score.json"
    printf '0\n' > "$out/$kind/run/run.exit"
    for index in {0..31}; do
        if [[ "$kind" == failed-audit && "$index" == 0 ]]; then continue; fi
        /usr/bin/ln -s "$(/usr/bin/realpath "$run/$index")" "$out/$kind/run/$index"
    done
done
mkdir -p "$out/failed-audit/run/0/verified"
/usr/bin/cp "$run/0/benchmark-row.json" "$run/0/summary.json" "$out/failed-audit/run/0/"
/usr/bin/ln -s "$(/usr/bin/realpath "$run/0/9960000")" "$out/failed-audit/run/0/9960000"
/usr/bin/jq '.passed=false' "$run/0/verified/result.json" > "$out/failed-audit/run/0/verified/result.json"
if PUPPYBOT_PROJECT="$project" /usr/bin/bash "$adapter" "$out/failed-audit/run" "$policy" "$out/failed-audit/rejected" bad-audit > "$out/failed-audit/log" 2>&1; then echo 'A failed replay audit was accepted.' >&2; exit 1; fi
[[ "$(< "$out/failed-audit/rejected/run.exit")" == 1 && ! -e "$out/failed-audit/rejected/selection/selection.json" ]]
/usr/bin/jq '.approaches+=1' "$out/forged-score/run/score.json" > "$out/forged-score/run/score.tmp"
/usr/bin/mv "$out/forged-score/run/score.tmp" "$out/forged-score/run/score.json"
if PUPPYBOT_PROJECT="$project" /usr/bin/bash "$adapter" "$out/forged-score/run" "$policy" "$out/forged-score/rejected" bad-score > "$out/forged-score/log" 2>&1; then echo 'A forged score was accepted.' >&2; exit 1; fi
[[ "$(< "$out/forged-score/rejected/run.exit")" == 1 && ! -e "$out/forged-score/rejected/selection/selection.json" ]]
echo 'Large-model qualification adapter accepted audited evidence and rejected altered results.'
