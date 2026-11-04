#!/usr/bin/env bash
# Paired selection on training layouts, not held-out qualification.
# Run only after runs/35-l4-matched.sh train; one GPU task at a time.
set -euo pipefail
if [[ ${1:-} != --clean ]]; then
    exec env -i PATH=/usr/bin:/bin HOME="$HOME" bash "$0" --clean "$@"
fi
shift
level=${1:?Expected selection level 4 or 5}
[[ $# == 1 && $level =~ ^(4|5)$ ]] || exit 1
cd /home/teppo/Work/my/puppybot
export PUPPYBOT_PROJECT=$PWD LD_LIBRARY_PATH=$PWD/build/flex/rocm-runtime
H=$PWD/datasets/visual-control/chase-v1; S=$H/levels; P=$PWD/build/flex/sim/levels-v2/pitch82
M=$P/search-dagger-l35-4workers; O=$P/search-dagger-l4-matched; out=$O/selection-L$level
exec 9>> "$P/.l4-matched.lock"
flock -n 9 || { echo 'Another matched experiment stage is running' >&2; exit 1; }
sha256sum -c "$O/training-inputs.sha256" > /dev/null
jq -e '.status == "passed" and .games == 1024 and .unchangedGames == 896 and .replacedGames == 128' "$O/matched-audit.json" > /dev/null
[[ -f "$O/training-match.json" ]] || { echo 'Missing successful training comparison' >&2; exit 1; }
matched=$(python3 -I "$S/audit-matched-training.py" "$M/student-s0" "$O/control-s0" "$O/treatment-s0")
jq -e '.status == "passed"' "$O/training-match.json" > /dev/null
[[ $matched == "$(cat "$O/training-match.json")" ]] || { echo 'Training comparison differs' >&2; exit 1; }
initial=$(sha256sum "$M/student-s0/weights.bin" | cut -d' ' -f1)
for arm in control treatment; do
    model=$O/$arm-s0; data=$M/data; [[ $arm != treatment ]] || data=$O/data
    data_sha=$(sha256sum "$data/data.bin" | cut -d' ' -f1); map_sha=$(sha256sum "$data/map.bin" | cut -d' ' -f1)
    jq -e --arg d "$data_sha" --arg m "$map_sha" --arg i "$initial" \
        '.dataSHA256 == $d and .memoryMapTargetsSHA256 == $m and .initialWeightsSHA256 == $i and .seed == 6500000 and .epochs == 8 and .batch == 2 and .checkpointEveryEpochs == 8 and .sequenceMirrorAugmentation == true and .carryCue == true and .speedTransitionLossWeight == 1' "$model/receipt.json" > /dev/null
    [[ $(sha256sum "$model/weights.bin" | cut -d' ' -f1) == $(jq -r .weightsSHA256 "$model/receipt.json") ]] || exit 1
done
[[ ! -e "$out" ]] || { echo 'Selection output exists; preserve and inspect it' >&2; exit 1; }
mkdir "$out"
files=(build/flex/control/control build/flex/control/simulator build/flex/rocm-runtime/libamdhip64.so "$H/evaluate.sh" "$S/audit-selection.py" "$S/audit-matched-training.py" "$S/l5cross.py" "$S/l5-first-room.py" "$S/selection-pair-l4-matched.sh" "$O/training-inputs.sha256" "$O/training-match.json")
for arm in control treatment; do
    model=$O/$arm-s0; files+=("$model/receipt.json" "$model/weights.bin" "$model/policy")
    count=${#files[@]}
    while IFS= read -r -d '' file; do files+=("$file"); done < <(find "$model/kernels" -type f -print0 | sort -z)
    (( ${#files[@]} > count )) || exit 1
done
for ((g=0; g<32; g++)); do
    scene=$PWD/build/flex/sim/expanded-rooms-v1/scenes/$((13+2*(g%3)))/$((g%16))
    files+=("$scene/case.json" "$scene/environment.bin" "$scene/layout.json")
done
sha256sum "${files[@]}" > "$out/inputs.sha256"
sha256sum -c "$out/inputs.sha256" > /dev/null
for arm in control treatment; do
    PUPPYBOT_EVAL_SELECTION=1 PUPPYBOT_EVAL_SELECTION_SEED=7800000 PUPPYBOT_EVAL_TWO_ROOM=1 \
    PUPPYBOT_CHASE_PARTS=4 PUPPYBOT_CHASE_HORIZON=300 PUPPYBOT_CHASE_FULL=0 \
        bash "$H/evaluate.sh" "$out" "$arm-s0" "$O/$arm-s0" --fetch --level "$level" --camera-pitch 82 > "$out/$arm-s0.log" 2>&1
    python3 -I - "$S/audit-selection.py" "$out/$arm-s0" "$O/$arm-s0" "$level" <<'PY'
import importlib.util, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location('audit_selection', sys.argv[1])
audit = importlib.util.module_from_spec(spec); spec.loader.exec_module(audit)
root, model, level = Path(sys.argv[2]), Path(sys.argv[3]), int(sys.argv[4])
audit.check_score(root, audit.summary(audit.load(root, model, level)))
PY
    sha256sum -c "$out/inputs.sha256" > /dev/null
done
python3 -I "$S/audit-selection.py" "$level" "$out/control-s0" "$O/control-s0" "$out/treatment-s0" "$O/treatment-s0" > "$out/pair.audit.json"
sha256sum -c "$out/inputs.sha256" > /dev/null
cat "$out/pair.audit.json"
for arm in control treatment; do
    if [[ $level == 4 ]]; then
        python3 -I "$S/l5cross.py" "$out"/$arm-s0/*/780* > "$out/$arm-s0.crossing.txt"
        cat "$out/$arm-s0.crossing.txt"
    else
        python3 -I "$S/l5-first-room.py" "$out/$arm-s0" > "$out/$arm-s0.first-room.json"
        cat "$out/$arm-s0.first-room.json"
    fi
done
sha256sum -c "$out/inputs.sha256" > /dev/null
