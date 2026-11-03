#!/usr/bin/env bash
# Normal-placement selection games (training layouts, PUPPYBOT_EVAL_SELECTION=1) for single students and ensembles
# already scored on the standard test, plus the handoff mix with all three dart seeds as members: does the
# selection ranking follow the test, and does a fourth policy help?
set -euo pipefail
cd /home/teppo/Work/my/puppybot
export PUPPYBOT_PROJECT=$PWD LD_LIBRARY_PATH=$PWD/build/flex/rocm-runtime
R=$PWD/build/flex/sim/levels-v1; H=$PWD/datasets/visual-control/chase-v1; P=$R/pitch82; Q=$P/select
export PUPPYBOT_EVAL_SELECTION=1
mkdir -p "$Q/eval"
score() {  # NAME MAIN PARTS [flags]
    local name=$1 main=$2 parts=$3; shift 3
    [[ -f "$Q/eval/score-$name.json" ]] || PUPPYBOT_CHASE_PARTS=$parts bash "$H/evaluate.sh" "$Q/eval" "$name" "$main" --fetch --camera-pitch 82 "$@" > "$Q/$name.eval.log" 2>&1
    echo "$name selection $(jq .meanDeliveriesPerMinute "$Q/eval/score-$name.json") test $(jq .meanDeliveriesPerMinute "$P/eval/score-$name.json" "$P/ensemble/eval/score-$name.json" 2>/dev/null | head -1)"
}
for s in dart-s0 dart-s1 dart-s2 edag-s2 edag2-s1; do score "$s" "$P/$s" 8; done
score dart "$P/dart-s2" 2 --ensemble "$P/dart-s0" --ensemble "$P/dart-s1"
score mix35 "$P/edag-s2" 2 --ensemble "$P/dart-s1" --ensemble "$P/dart-s2" --ensemble-until 35
score mix35e2 "$P/edag2-s1" 2 --ensemble "$P/dart-s1" --ensemble "$P/dart-s2" --ensemble-until 35
score mix35d3 "$P/edag-s2" 2 --ensemble "$P/dart-s0" --ensemble "$P/dart-s1" --ensemble "$P/dart-s2" --ensemble-until 35
echo "== done $(date +%T)"
