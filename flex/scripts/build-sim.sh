#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
compiler="${FLEXSCRIPT_COMPILER:-$project_dir/build/flex/pup-compiler}"
if [[ -n "${FLEXSCRIPT_COMPILER:-}" && ! -x "$compiler" ]]; then
    echo 'FLEXSCRIPT_COMPILER must name an executable compiler.' >&2
    exit 1
fi
if [[ ! -x "$compiler" ]]; then
    compiler="$(command -v flexscript || true)"
fi
if [[ -z "$compiler" ]]; then
    compiler="$project_dir/../flexscript/build/flex"
fi
if [[ ! -x "$compiler" ]]; then
    echo 'Set FLEXSCRIPT_COMPILER to a verified Flexscript compiler.' >&2
    exit 1
fi
export FLEXSCRIPT_ROOT="${FLEXSCRIPT_ROOT:-$project_dir/../flexscript}"
mkdir -p "$project_dir/build/flex/sim"
python3 "$project_dir/flex/scripts/prepare-sim.py"
python3 - "$project_dir" "$FLEXSCRIPT_ROOT" <<'PY'
import hashlib
import json
from pathlib import Path
import sys

project, dependency = map(Path, sys.argv[1:])
dependency = dependency.resolve()
out = project/'build/flex/sim'
modules = [dependency/'libs/render.flex', dependency/'libs/physics/physics.flex']
files = set(modules)
pending = list(modules)
import re
while pending:
    p = pending.pop()
    for name in re.findall(r'(?:import|extend) "([^"]+)";', p.read_text()):
        child = (p.parent/name).resolve()
        if child not in files:
            files.add(child)
            pending.append(child)
# The controller pins its own IEEE binary64 implementation. Adapt the shared
# library imports to that implementation, just as prepare-gym.py does for DB.
# Keep all renderer/physics algorithms intact and leave the dependency untouched.
mirror = out/'library'
receipt = {}
for p in sorted(files):
    relative = p.relative_to(dependency)
    original = p.read_text()
    adapted = original
    if str(relative) == 'lib/f64.flex':
        adapted = 'import '+json.dumps(str(project/'flex/core/words.flex'))+';\n'
    elif str(relative) == 'lib/gpu.flex':
        for name in ('add', 'sub', 'mul', 'div', 'sqrt'):
            line = f'lowering f64_{name} "f64.{name}" "native-x86_64";\n'
            if adapted.count(line) != 1:
                raise SystemExit('Review changed shared GPU binary64 registrations.')
            adapted = adapted.replace(line, '')
    elif str(relative) == 'libs/physics/collision.flex':
        # Extra arm proxies add many kinematic pairs. The narrow phase already
        # excludes pairs with zero inverse mass on both bodies; skip those
        # calls earlier, preserving the order and results of physical contacts.
        call = '            ph_collide_pair(w,a,ph_shape(w,j),ph_scratch(w));'
        if adapted.count(call) != 1:
            raise SystemExit('Review changed shared physics pair traversal.')
        adapted = adapted.replace(call, '            if load64(ph_body(w,load64(a))+112) || load64(ph_body(w,load64(ph_shape(w,j)))+112) {\n'+call+'\n            }')
    target = mirror/relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(adapted)
    receipt[str(relative)] = dict(sourceSha256=hashlib.sha256(p.read_bytes()).hexdigest(), adaptedSha256=hashlib.sha256(adapted.encode()).hexdigest())
(out/'dependencies.flex').write_text(''.join('import '+json.dumps(str(mirror/p.relative_to(dependency)))+';\n' for p in modules))
(out/'dependencies.json').write_text(json.dumps(receipt, indent=2)+'\n')
PY
temporary="$project_dir/build/flex/puppybot-sim.tmp.$$"
trap 'rm -f "$temporary"' EXIT
"$compiler" "$project_dir/flex/sim/main.flex" -o "$temporary"
mv -f "$temporary" "$project_dir/build/flex/puppybot-sim"
echo "Built $project_dir/build/flex/puppybot-sim"
