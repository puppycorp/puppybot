#!/usr/bin/env python3
"""Adapt FlexDB's imports to Puppybot's pinned IEEE implementation at build time.

Flexscript has a global function namespace. Query comparisons need the same
f64_is_nan/lt/gt API already supplied by core/words.flex; importing another copy
would duplicate those definitions. All other database imports stay upstream.
"""
import hashlib
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
FLEXSCRIPT = Path(os.environ.get('FLEXSCRIPT_ROOT', ROOT.parent/'flexscript')).resolve()
DB = FLEXSCRIPT/'libs/db'
OUT = ROOT/'build/flex'
OUT.mkdir(parents=True, exist_ok=True)
codegen = FLEXSCRIPT/'libs/ml/pup/gpu.flex'
if not codegen.is_file():
    raise SystemExit('Flexscript dependency lacks libs/ml/pup/gpu.flex; use the GPU compiler branch.')

for name, source in [('device', FLEXSCRIPT/'lib/device.flex'),
                     ('parser', FLEXSCRIPT/'libs/ml/pup/parser.flex'),
                     ('kernel-ops', FLEXSCRIPT/'libs/ml/pup/gpu/kernels/ops-body.flex'),
                     ('kernel-pack', FLEXSCRIPT/'libs/ml/pup/gpu/kernels/pack.flex')]:
    (OUT/('pup-'+name+'.flex')).write_text('import '+json.dumps(str(source))+';\n')

# The model compiler and operation bodies are supplied by Flexscript.
(OUT/'pup-codegen.flex').write_text('import '+json.dumps(str(codegen))+';\n'+
    'fn puppybot_codegen(argc,argv) {cg_repository='+json.dumps(str(FLEXSCRIPT))+';'+
    'cg_operations='+json.dumps(str(ROOT/'flex/ml/kernels/ops.flex'))+';'+
    'cg_packer='+json.dumps(str(FLEXSCRIPT/'libs/ml/pup/gpu/kernels/pack.flex'))+';'+
    'cg_output_root='+json.dumps(str(OUT/'pup-kernels'))+';return cg_main(argc,argv); }\n')

query = (DB/'query.flex').read_text()
old = 'import "../../lib/f64.flex";'
if query.count(old) != 1:
    raise SystemExit('Review changed FlexDB query imports before building Gym.')
query = query.replace(old, 'import "../../flex/core/words.flex";')
(OUT/'gym-query.flex').write_text(query)


def imported(match):
    name = match.group(1)
    path = OUT/'gym-query.flex' if name == 'query.flex' else DB/name
    return 'import '+json.dumps(str(path.resolve()))+';'


source = (DB/'flexdb.flex').read_text()
(OUT/'gym-flexdb.flex').write_text(re.sub(r'import "([^"]+)";', imported, source))
manifest = {str(p.relative_to(DB)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(DB.glob('*.flex'))}
(OUT/'gym-dependencies.json').write_text(json.dumps(manifest, indent=2)+'\n')

# Embed the app's stylesheet beside Monolith's bundled browser adapter.
style = (ROOT/'flex/gym/ui.css').read_text()
(OUT/'gym-style.flex').write_text('fn gm_styles() { return '+json.dumps(style, ensure_ascii=False)+'; }\n')
camera = (ROOT/'flex/gym/camera.js').read_text()
(OUT/'gym-camera.flex').write_text('fn gm_camera_js() { return '+json.dumps(camera, ensure_ascii=False)+'; }\n')

# Keep Gym's native scene choices tied to the simulator's case catalog.
native_cases = json.loads((ROOT/'flex/sim/cases/catalog.json').read_text())['cases']
cases = [dict(id='arm-reach', name='Seeded joint targets', backend='servo-plant-v1',
              description='All four joints settle within 8 ticks for 25 steps.'),
         dict(id='joint-stall', name='Jammed yaw servo', backend='servo-plant-v1',
              description='Firmware reports stall and stops wheel outputs.')]
cases += [dict(id=c['id'], name=c['name'], backend='flexscript-kinematic-contact-v1',
               description=c['description']) for c in native_cases]
catalog = json.dumps(cases, separators=(',', ':'), ensure_ascii=False)
(OUT/'gym-sim-cases.flex').write_text(
    'fn gg_project_root() { return '+json.dumps(str(ROOT))+'; }\n'+
    'fn gg_case_catalog() { return '+json.dumps(catalog, ensure_ascii=False)+'; }\n'+
    'fn gg_native_case(name) { return '+
    ' || '.join('pl_equal(name, '+json.dumps(c['id'])+')' for c in native_cases)+'; }\n'+
    'fn gg_case_name(name) { '+''.join('if pl_equal(name, '+json.dumps(c['id'])+
        ') { return '+json.dumps(c['name'], ensure_ascii=False)+'; } ' for c in cases)+'return name; }\n')

# A scoped wrapper invokes the upstream Monolith compiler without spending its
# VM fuel lexing unrelated controller/codec/database modules. Rename only the
# entry hook so the wrapper can export transform_syntax itself.
mono = DB.parent/'monolith'
syntax = (mono/'syntax.flex').read_text()
entry = 'fn transform_syntax('
if syntax.count(entry) != 1:
    raise SystemExit('Review changed Monolith compiler hooks before building Gym.')
syntax = syntax.replace(entry, 'fn gym_monolith_transform(')
syntax = re.sub(r'import "([^"]+)";', lambda m: 'import '+json.dumps(str((mono/m[1]).resolve()))+';', syntax)
(OUT/'gym-monolith-syntax.flex').write_text(syntax)
manifest.update({'monolith/'+str(p.relative_to(mono)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted(mono.rglob('*')) if p.is_file()})
manifest['gym/views.flex'] = hashlib.sha256((ROOT/'flex/gym/views.flex').read_bytes()).hexdigest()
manifest['gym/ui.css'] = hashlib.sha256(style.encode()).hexdigest()
manifest['gym/camera.js'] = hashlib.sha256(camera.encode()).hexdigest()
manifest['sim/cases/catalog.json'] = hashlib.sha256((ROOT/'flex/sim/cases/catalog.json').read_bytes()).hexdigest()
(OUT/'gym-dependencies.json').write_text(json.dumps(manifest, indent=2)+'\n')
