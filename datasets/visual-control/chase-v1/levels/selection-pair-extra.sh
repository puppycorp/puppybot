#!/usr/bin/env bash
# Complete the ordinary-fetch or level-2 selection evidence omitted by the
# L3/L5 pair runner. These are training-layout games, not held-out tests.
# Usage: selection-pair-extra.sh standard|2 SEED_INDEX
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
[[ $# == 2 && ( $1 == standard || $1 == 2 ) && $2 =~ ^[0-2]$ ]] || { echo 'Expected standard|2 and index 0|1|2' >&2; exit 1; }
level=0; label=standard; [[ $1 != 2 ]] || { level=2; label=L2; }
index=$2; cd "$project"
export LD_LIBRARY_PATH="$project/build/flex/rocm-runtime"
H=$project/datasets/visual-control/chase-v1; S=$H/levels
P=$project/build/flex/sim/levels-v2/pitch82; B=$P/search-dagger-4workers; O=$P/search-dagger-l35-4workers
out=$O/selection-$label; baseline=$B/student-s$index; student=$O/student-s$index
manifest=$out/pair-s$index.inputs.sha256; audit=$out/pair-s$index.audit.json
mkdir -p "$out"
for path in "$O/source-audit.json" "$O/training-inputs.sha256" "$baseline/receipt.json" "$student/receipt.json"; do
    [[ -f "$path" ]] || { echo "Required input missing: $path" >&2; exit 1; }
done
jq -e '.status == "passed" and .games == 1024 and .gamesBySourceLevel == {"teacher-L0":96,"teacher-L1":96,"teacher-L2":96,"teacher-L3":96,"teacher-L4":256,"teacher-L5":128,"student-L3":128,"student-L5":128}' "$O/source-audit.json" > /dev/null
sha256sum -c "$O/training-inputs.sha256" > /dev/null
data_sha=$(sha256sum "$O/data/data.bin" | cut -d' ' -f1); map_sha=$(sha256sum "$O/data/map.bin" | cut -d' ' -f1)
baseline_sha=$(sha256sum "$baseline/weights.bin" | cut -d' ' -f1)
jq -e --arg data "$data_sha" --arg map "$map_sha" --arg initial "$baseline_sha" '.dataSHA256 == $data and .memoryMapTargetsSHA256 == $map and .initialWeightsSHA256 == $initial' "$student/receipt.json" > /dev/null || { echo 'Student training receipt mismatch' >&2; exit 1; }
if [[ ! -f "$manifest" ]]; then
    for name in baseline-s$index student-s$index; do
        [[ ! -e "$out/$name" && ! -e "$out/score-$name.json" ]] || { echo "Refusing to create provenance after evaluation began: $name" >&2; exit 1; }
    done
    files=(build/flex/control/control build/flex/control/simulator build/flex/rocm-runtime/libamdhip64.so
           "$H/evaluate.sh" "$S/audit-selection.py" "$S/selection-pair-extra.sh" "$O/source-audit.json" "$O/training-inputs.sha256")
    for model in "$baseline" "$student"; do
        files+=("$model/receipt.json" "$model/policy" "$model/weights.bin")
        [[ -d "$model/kernels" ]] || { echo "Missing model kernels: $model" >&2; exit 1; }
        before=${#files[@]}
        while IFS= read -r -d '' file; do files+=("$file"); done < <(find "$model/kernels" -type f -print0 | sort -z)
        (( ${#files[@]} > before )) || { echo "Empty model kernels: $model" >&2; exit 1; }
    done
    for ((g=0;g<32;g++)); do
        scene="$project/build/flex/sim/expanded-rooms-v1/scenes/$((12+g%6))/$((g%16))"
        files+=("$scene/case.json" "$scene/environment.bin" "$scene/layout.json")
    done
    temp=$(mktemp "$out/pair-s$index.inputs.tmp.XXXXXX"); trap 'rm -f "$temp"' EXIT
    sha256sum "${files[@]}" > "$temp"; sha256sum -c "$temp" > /dev/null; ln "$temp" "$manifest"
fi
sha256sum -c "$manifest" > /dev/null
for kind in baseline student; do
    name=$kind-s$index; model=$student; [[ $kind != baseline ]] || model=$baseline
    if [[ ! -f "$out/score-$name.json" ]]; then
        [[ ! -e "$out/$name" ]] || { echo "Incomplete player output retained: $out/$name" >&2; exit 1; }
        flags=(--fetch --camera-pitch 82); (( level == 0 )) || flags+=(--level "$level")
        PUPPYBOT_EVAL_SELECTION=1 PUPPYBOT_EVAL_SELECTION_SEED=7800000 PUPPYBOT_EVAL_TWO_ROOM=0 \
            PUPPYBOT_CHASE_HORIZON=300 PUPPYBOT_CHASE_FULL=0 PUPPYBOT_CHASE_PARTS=4 \
            bash "$H/evaluate.sh" "$out" "$name" "$model" "${flags[@]}" > "$out/$name.log" 2>&1
    fi
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
python3 -I - "$S/audit-selection.py" "$out" "$baseline" "$student" "$index" "$level" > "$audit.tmp" <<'PY'
import importlib.util, json, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location('audit_selection', sys.argv[1])
audit = importlib.util.module_from_spec(spec); spec.loader.exec_module(audit)
root, baseline, student, index, level = Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]), sys.argv[5], int(sys.argv[6])
a = audit.load(root / f'baseline-s{index}', baseline, level)
b = audit.load(root / f'student-s{index}', student, level)
for seed in a:
    if a[seed][2:] != b[seed][2:] or a[seed][0].get('levelPlacement') != b[seed][0].get('levelPlacement'):
        raise ValueError(f'unmatched selection game: {seed}')
left, right = audit.summary(a), audit.summary(b)
audit.check_score(root / f'baseline-s{index}', left)
audit.check_score(root / f'student-s{index}', right)
print(json.dumps({'status': 'paired selection audit passed', 'level': level, 'seeds': [7800000, 7800031],
                  'baseline': left, 'student': right,
                  'scope': 'training layouts; simulator identity and pretrained ancestry require separate proof'}, sort_keys=True))
PY
sha256sum -c "$manifest" > /dev/null
mv "$audit.tmp" "$audit"
cat "$audit"
