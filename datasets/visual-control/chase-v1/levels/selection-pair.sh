#!/usr/bin/env bash
# Evaluate one baseline/student pair on training-layout selection games and
# audit it before comparing. Run one pair at a time; no other GPU jobs.
# Usage: selection-pair.sh LEVEL SEED_INDEX (levels 1,3,4,5; index 0,1,2)
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
level="${1:?Level required}"; index="${2:?Student index required}"
[[ "$level" =~ ^(1|3|4|5)$ && "$index" =~ ^[0-2]$ && $# == 2 ]] || { echo 'Expected LEVEL in 1,3,4,5 and SEED_INDEX in 0,1,2' >&2; exit 1; }
cd "$project"
H=$project/datasets/visual-control/chase-v1; S=$H/levels
P=$project/build/flex/sim/levels-v2/pitch82; O=$P/search-dagger-4workers
out=$O/selection-L$level; baseline=$P/more1-s$index; student=$O/student-s$index
manifest=$out/pair-s$index.inputs.sha256; audit=$out/pair-s$index.audit.json
mkdir -p "$out"
for path in "$O/source-audit.json" "$O/training-inputs.sha256" "$baseline/receipt.json" "$student/receipt.json"; do
    [[ -f "$path" ]] || { echo "Required input missing: $path" >&2; exit 1; }
done
jq -e '.status == "passed" and .games == 1024 and .teacherShards == 48 and .studentShards == 4' "$O/source-audit.json" > /dev/null
sha256sum -c "$O/training-inputs.sha256" > /dev/null
data_sha=$(sha256sum "$O/data/data.bin" | cut -d' ' -f1)
map_sha=$(sha256sum "$O/data/map.bin" | cut -d' ' -f1)
baseline_sha=$(sha256sum "$baseline/weights.bin" | cut -d' ' -f1)
jq -e --arg data "$data_sha" --arg map "$map_sha" --arg initial "$baseline_sha" \
    '.dataSHA256 == $data and .memoryMapTargetsSHA256 == $map and .initialWeightsSHA256 == $initial' "$student/receipt.json" > /dev/null || {
    echo "Student receipt does not match the audited training data and baseline model: $student" >&2; exit 1;
}
if [[ ! -f "$manifest" ]]; then
    for name in baseline-s$index student-s$index; do
        [[ ! -e "$out/$name" && ! -e "$out/score-$name.json" ]] || { echo "Refusing to create provenance after evaluation began: $name" >&2; exit 1; }
    done
    files=(build/flex/control/control build/flex/control/simulator build/flex/rocm-runtime/libamdhip64.so
           "$H/evaluate.sh" "$S/audit-selection.py" "$S/selection-pair.sh" "$O/source-audit.json" "$O/training-inputs.sha256")
    for model in "$baseline" "$student"; do
        files+=("$model/receipt.json" "$model/policy" "$model/weights.bin")
        [[ -d "$model/kernels" ]] || { echo "Missing model kernels: $model" >&2; exit 1; }
        before=${#files[@]}
        while IFS= read -r -d '' file; do files+=("$file"); done < <(find "$model/kernels" -type f -print0 | sort -z)
        (( ${#files[@]} > before )) || { echo "Empty model kernels: $model" >&2; exit 1; }
    done
    for ((g=0; g<32; g++)); do
        layout=$((12 + g % 6)); (( level < 4 )) || layout=$((13 + 2 * (g % 3)))
        scene="$project/build/flex/sim/expanded-rooms-v1/scenes/$layout/$((g % 16))"
        files+=("$scene/case.json" "$scene/environment.bin" "$scene/layout.json")
    done
    temp=$(mktemp "$out/pair-s$index.inputs.tmp.XXXXXX")
    trap 'rm -f "$temp"' EXIT
    sha256sum "${files[@]}" > "$temp"
    sha256sum -c "$temp" > /dev/null
    ln "$temp" "$manifest"
fi
sha256sum -c "$manifest" > /dev/null
for kind in baseline student; do
    name=$kind-s$index; model=$student; [[ $kind != baseline ]] || model=$baseline
    if [[ ! -f "$out/score-$name.json" ]]; then
        [[ ! -e "$out/$name" ]] || { echo "Incomplete player output retained: $out/$name" >&2; exit 1; }
        two=0; (( level < 4 )) || two=1
        PUPPYBOT_EVAL_SELECTION=1 PUPPYBOT_EVAL_SELECTION_SEED=7800000 PUPPYBOT_EVAL_TWO_ROOM=$two PUPPYBOT_CHASE_PARTS=4 \
            bash "$H/evaluate.sh" "$out" "$name" "$model" --fetch --level "$level" --camera-pitch 82 > "$out/$name.log" 2>&1
    fi
    # Reject incomplete, timed-out or stale output before starting the next player.
    python3 -I - "$S/audit-selection.py" "$out/$name" "$model" "$level" <<'PY'
import importlib.util, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location('audit_selection', sys.argv[1])
audit = importlib.util.module_from_spec(spec); spec.loader.exec_module(audit)
root, model, level = Path(sys.argv[2]), Path(sys.argv[3]), int(sys.argv[4])
audit.check_score(root, audit.summary(audit.load(root, model, level)))
PY
    sha256sum -c "$manifest" > /dev/null
done
python3 -I "$S/audit-selection.py" "$level" "$out/baseline-s$index" "$baseline" "$out/student-s$index" "$student" > "$audit.tmp"
sha256sum -c "$manifest" > /dev/null
mv "$audit.tmp" "$audit"
cat "$audit"
if (( level == 4 )); then
    for kind in baseline student; do
        echo -n "$kind-s$index "
        python3 -I "$S/l5cross.py" "$out"/$kind-s$index/*/780*
    done
fi
