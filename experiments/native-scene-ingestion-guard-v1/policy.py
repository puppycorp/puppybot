#!/usr/bin/env python3
"""Prepare a pinned native scene policy from the two reservation manifests.

This is a prototype. A caller must retain/review all input and output digests;
no policy makes arbitrary pre-existing training data safe.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SPEC = importlib.util.spec_from_file_location('selection_role_guard', ROOT / 'experiments/selection-role-prototype-v1/guard.py')
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def prepare(selection, selection_sha, heldout, heldout_sha, catalog, episodes, validation, seed):
    if (type(episodes) is not int or type(validation) is not int or type(seed) is not int or
            not 2 <= episodes <= 128 or not 1 <= validation < episodes or
            not 0 <= seed <= 2147483647 - (episodes - 1)):
        raise ValueError('invalid guard split or seed')
    reference = guard.SceneGuard(selection, selection_sha, heldout, heldout_sha)
    reserved_seeds = {row['seed'] for row in reference.selection.values()} | {row['seed'] for row in reference.heldout.values()}
    if any(seed <= value < seed + episodes for value in reserved_seeds):
        raise ValueError('collection seed overlaps a reserved game')
    root = Path(catalog)
    if not root.is_dir() or {p.name for p in root.iterdir()} != {str(i) for i in range(episodes)}:
        raise ValueError('catalog must have exactly the numbered episodes')
    rows = []
    for index in range(episodes):
        role = 'fit' if index < episodes - validation else 'validation'
        files = reference.snapshot(root / str(index), role)
        rows.append({'index': index, 'seed': seed + index, 'role': role,
                     'caseSHA256': digest(files['case.json']),
                     'environmentSHA256': digest(files['environment.bin']),
                     'layoutSHA256': digest(files['layout.json'])})
    return {'schema': 'puppybot.native-scene-guard.v1', 'episodes': episodes,
            'validation': validation, 'seed': seed, 'rows': rows,
            'selectionManifestSHA256': selection_sha, 'heldoutManifestSHA256': heldout_sha,
            'denyCases': sorted(reference.selection_cases | reference.heldout_cases),
            'denyEnvironments': sorted(reference.selection_environments | reference.heldout_environments)}


def write_new(path, value):
    data = (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()
    with Path(path).open('xb') as out:
        out.write(data); out.flush(); os.fsync(out.fileno())
    return digest(data)
