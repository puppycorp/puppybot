#!/usr/bin/env python3
"""Adapt FlexDB's imports to Puppybot's pinned IEEE implementation at build time.

Flexscript has a global function namespace. Query comparisons need the same
f64_is_nan/lt/gt API already supplied by core/words.flex; importing another copy
would duplicate those definitions. All other database imports stay upstream.
"""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT.parent/'flexscript/libs/db'
OUT = ROOT/'build/flex'
OUT.mkdir(parents=True, exist_ok=True)

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
(OUT/'gym-dependencies.json').write_text(json.dumps(manifest, indent=2)+'\n')
