#!/usr/bin/env python3
"""Stage a fail-closed holdout ingestion check; not yet wired into control.

Usage: preflight-training-scenes.py RESERVED_MANIFEST SCENE_OR_CATALOG ...

Every scene must contain case.json, environment.bin and layout.json. Catalogs
must contain only numbered scene directories or symlinks. This check cannot
protect direct control invocations until integrated into every ingestion path,
and its reserved-manifest hash must itself be pinned by the caller.
"""
import hashlib
import json
import re
import sys
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(manifest, inputs):
    data = json.loads(manifest.read_text())
    if (data.get('status') != 'reserved_not_evaluated' or data.get('task') != 'virtual-fetch'
            or data.get('gamesPerLevel') != 32 or len(data.get('rows', [])) != 160):
        raise ValueError('invalid reserved manifest')
    cases, environments = set(), set()
    for row in data['rows']:
        level, index = row.get('level'), row.get('index')
        if type(level) is not int or type(index) is not int or level not in range(1, 6) or index not in range(32):
            raise ValueError('invalid reserved game index')
        layout = 226 + index if level < 4 else 227 + 2 * index
        if row.get('seed') != 1700000000 + level * 100 + index or row.get('layoutId') != layout or row.get('scene') != f'generated/{layout}/{index % 16}':
            raise ValueError('invalid reserved scene mapping')
        case, env = row['caseSHA256'], row['environmentSHA256']
        if not re.fullmatch('[0-9a-f]{64}', case) or not re.fullmatch('[0-9a-f]{64}', env):
            raise ValueError('invalid reserved scene hash')
        cases.add(case)
        environments.add(env)
    if len({(row['level'], row['index']) for row in data['rows']}) != 160:
        raise ValueError('duplicate reserved game index')
    checked = []
    for path in inputs:
        if not path.is_dir():
            raise ValueError(f'missing scene or catalog: {path}')
        if (path / 'layout.json').exists():
            scenes = [path]
        else:
            entries = list(path.iterdir())
            if not entries or any(not entry.is_dir() or not re.fullmatch('0|[1-9][0-9]*', entry.name) for entry in entries):
                raise ValueError(f'invalid or empty scene catalog: {path}')
            scenes = entries
        for scene in scenes:
            metadata = json.loads((scene / 'layout.json').read_text())
            if not isinstance(metadata, dict) or metadata.get('reservedHeldOut', False) is not False:
                raise ValueError(f'reserved or malformed scene role: {scene}')
            if digest(scene / 'case.json') in cases or digest(scene / 'environment.bin') in environments:
                raise ValueError(f'exact reserved scene file in training input: {scene}')
            checked.append(str(scene.resolve()))
    if not checked:
        raise ValueError('no scenes checked')
    return {'status': 'passed', 'scenes': len(checked), 'reservedManifestSHA256': digest(manifest),
            'scope': 'explicit inputs only; native control ingestion and semantic similarity are not checked'}


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    print(json.dumps(verify(Path(sys.argv[1]), [Path(p) for p in sys.argv[2:]]), sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        raise SystemExit(f'Invalid training scenes: {error}')
