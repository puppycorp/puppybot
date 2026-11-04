#!/usr/bin/env python3
"""Prepare fresh-seed training-layout scenes for the bounded-bias diagnostic.

These are not held-out scenes. The new seeds are checked against recorded
source-shard seed ranges, but historical pretrained ancestry is not proven.
"""
import fcntl
import importlib.util
import json
import sys
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[4]
S = PROJECT / 'datasets/visual-control/chase-v1/levels'
P = PROJECT / 'build/flex/sim/levels-v2/pitch82'
O = P / 'search-dagger-l4-matched'
OUTPUT = O / 'bounded-bias-validation-scenes'
SEEDS = (7810101, 7810104, 7810107)
spec = importlib.util.spec_from_file_location('factorial', S / 'prepare-route-factorial.py')
factorial = importlib.util.module_from_spec(spec); spec.loader.exec_module(factorial)


def inventory():
    files = list(P.glob('kturn-L[0-5]/shard-*/report.json'))
    for root in (P / 'search-dagger-4workers/dagger-L3', P / 'search-dagger-l35-4workers/dagger-L5', O / 'dagger-L4'):
        files.extend(root.glob('shard-*/report.json'))
    if len(files) != 60 or len({p.resolve() for p in files}) != 60:
        raise ValueError(f'expected 60 recorded source shards, found {len(files)}')
    for path in files:
        report = json.loads(path.read_text())
        seed, episodes = report['seed'], report['episodes']
        if type(seed) is not int or type(episodes) is not int or episodes < 1:
            raise ValueError(f'invalid source range: {path}')
        if any(seed <= candidate < seed + episodes for candidate in SEEDS):
            raise ValueError(f'validation seed overlaps source: {path}')
    return files


def main():
    if len(sys.argv) != 1:
        raise SystemExit(__doc__)
    with (P / '.l4-matched.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        files = inventory()
        factorial.SEEDS = SEEDS
        manifest = factorial.prepare(factorial.SCENES, OUTPUT)
        (OUTPUT / 'inventory.json').write_text(json.dumps({'seeds': SEEDS, 'shards': {str(p): factorial.sha(p.read_bytes()) for p in sorted(files)},
                    'scope': 'recorded source ranges only, not unrecorded pretraining ancestry'}, indent=2) + '\n')
        print(json.dumps({'status': 'diagnostic_inputs_only', 'conditions': len(manifest['conditions']), 'seeds': SEEDS}))


if __name__ == '__main__':
    main()
