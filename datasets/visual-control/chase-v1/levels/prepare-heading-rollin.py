#!/usr/bin/env python3
"""Prepare matched L5 DAgger catalogs, without collecting or training.

Usage: prepare-heading-rollin.py pilot|full NEW_OUTPUT
Control and treatment share seed, layout, case, start position and validation
headings. Only fitting-game treatment headings vary. Training layouts only;
source-seed inventory cannot establish unrecorded pretrained ancestry.
"""
import fcntl
import importlib.util
import json
import shutil
import sys
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[4]
S = PROJECT / 'datasets/visual-control/chase-v1/levels'
P = PROJECT / 'build/flex/sim/levels-v2/pitch82'
FIT_YAWS = (.35, .42, .49)
BASE_SEED = 6600000
PILOT_SEED = 6700000


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec); spec.loader.exec_module(obj)
    return obj


factorial = load('factorial', S / 'prepare-route-factorial.py')
validation = load('validation', S / 'prepare-bias-validation.py')


def design(mode):
    if mode not in ('pilot', 'full'):
        raise ValueError('expected pilot or full')
    shards, episodes, fitting = (1, 2, 1) if mode == 'pilot' else (4, 32, 30)
    rows = []
    for shard in range(shards):
        for index in range(episodes):
            seed = (PILOT_SEED if mode == 'pilot' else BASE_SEED + shard * 1000) + index
            layout = 15 if mode == 'pilot' else (13, 15, 17)[((index // 3) + shard) % 3]
            variant = index if mode == 'pilot' else (shard * 8 + index // 3) % 16
            yaw = (.35 if index == 0 else .42) if mode == 'pilot' else (FIT_YAWS[index % 3] if index < fitting else .42)
            rows.append({'shard': shard, 'index': index, 'seed': seed, 'layout': layout, 'variant': variant,
                         'fitting': index < fitting, 'controlYaw': .42, 'treatmentYaw': yaw})
    return rows


def check_inventory(rows):
    reports = validation.inventory()
    for path in reports:
        record = json.loads(path.read_text()); first, count = record['seed'], record['episodes']
        if any(first <= row['seed'] < first + count for row in rows):
            raise ValueError(f'new roll-in seed overlaps recorded source: {path}')
    if len({row['seed'] for row in rows}) != len(rows):
        raise ValueError('duplicate rollout seed')
    if any(7800000 <= row['seed'] < 7800032 or row['seed'] in validation.SEEDS for row in rows):
        raise ValueError('new roll-in seed overlaps selection or fresh validation')
    return {str(path): factorial.sha(path.read_bytes()) for path in sorted(reports)}


def prepare(mode, output):
    if output.exists() or output.is_symlink():
        raise ValueError('output exists; retain and inspect')
    rows = design(mode); inventory = check_inventory(rows)
    output.mkdir(parents=False)
    for row in rows:
        original = factorial.SCENES / str(row['layout']) / str(row['variant'])
        info = json.loads((original / 'layout.json').read_text())
        if info.get('layoutId') != row['layout'] or info.get('fit') is not True or info.get('startRoom') != 0:
            raise ValueError('scene is not an intended training layout')
        env = (original / 'environment.bin').read_bytes()
        case = (original / 'case.json').read_bytes(); layout = (original / 'layout.json').read_bytes()
        row['sourceEnvironmentSHA256'] = factorial.sha(env); row['caseSHA256'] = factorial.sha(case)
        row['layoutSHA256'] = factorial.sha(layout)
        for arm in ('control', 'treatment'):
            target = output / f'{arm}-L5' / 'catalogs' / f'shard-{row["shard"]}' / str(row['index'])
            target.mkdir(parents=True)
            changed = factorial.environment(env, row[f'{arm}Yaw'])
            (target / 'environment.bin').write_bytes(changed)
            (target / 'case.json').write_bytes(case); (target / 'layout.json').write_bytes(layout)
            row[f'{arm}EnvironmentSHA256'] = factorial.sha(changed)
    manifest = {'status': 'diagnostic_inputs_only', 'mode': mode, 'rows': rows, 'sourceInventorySHA256': inventory,
                'scope': 'training layouts, fixed start position, common seeds and cases; source inventory does not prove pretrained ancestry'}
    (output / 'catalogs.json').write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n')
    verify(output, manifest)
    return manifest


def verify(output, manifest):
    expected = design(manifest['mode']); rows = manifest['rows']
    if len(rows) != len(expected) or check_inventory(expected) != manifest['sourceInventorySHA256']:
        raise ValueError('incomplete design or changed source inventory')
    if {p.name for p in output.iterdir()} != {'catalogs.json', 'control-L5', 'treatment-L5'}:
        raise ValueError('unexpected catalog root entries')
    shards = {row['shard'] for row in expected}
    for arm in ('control', 'treatment'):
        root = output / f'{arm}-L5'
        if {p.name for p in root.iterdir()} != {'catalogs'} or {p.name for p in (root / 'catalogs').iterdir()} != {f'shard-{i}' for i in shards}:
            raise ValueError('unexpected catalog shard')
        for shard in shards:
            wanted = {str(row['index']) for row in expected if row['shard'] == shard}
            if {p.name for p in (root / 'catalogs' / f'shard-{shard}').iterdir()} != wanted:
                raise ValueError('unexpected catalog index')
    for row, planned in zip(rows, expected):
        if any(row.get(k) != v for k, v in planned.items()):
            raise ValueError('catalog design differs')
        source = factorial.SCENES / str(row['layout']) / str(row['variant'])
        env = (source / 'environment.bin').read_bytes(); case = (source / 'case.json').read_bytes(); layout = (source / 'layout.json').read_bytes()
        if (row['sourceEnvironmentSHA256'] != factorial.sha(env) or row['caseSHA256'] != factorial.sha(case)
                or row['layoutSHA256'] != factorial.sha(layout)):
            raise ValueError('source scene changed')
        for arm in ('control', 'treatment'):
            path = output / f'{arm}-L5' / 'catalogs' / f'shard-{row["shard"]}' / str(row['index'])
            expected_env = factorial.environment(env, row[f'{arm}Yaw'])
            if ({p.name for p in path.iterdir()} != {'environment.bin', 'case.json', 'layout.json'}
                    or (path / 'environment.bin').read_bytes() != expected_env
                    or (path / 'case.json').read_bytes() != case or (path / 'layout.json').read_bytes() != layout
                    or row[f'{arm}EnvironmentSHA256'] != factorial.sha(expected_env)):
                raise ValueError('generated catalog changed')


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    mode, output = sys.argv[1], Path(sys.argv[2]).absolute()
    if mode not in ('pilot', 'full') or output != P / f'heading-rollin-{mode}-catalogs':
        raise ValueError('output must be the designated new pilot/full catalog directory')
    with (P / '.l4-matched.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if shutil.disk_usage(P).free < 40 * 1024**3:
            raise ValueError('at least 40 GiB free required before staging')
        result = prepare(mode, output)
    print(json.dumps({'status': result['status'], 'mode': mode, 'gamesPerArm': len(result['rows'])}))


if __name__ == '__main__': main()
