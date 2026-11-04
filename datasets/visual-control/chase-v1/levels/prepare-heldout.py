#!/usr/bin/env python3
"""Reserve a prospective virtual-fetch holdout without running any policy.

Usage: prepare-heldout.py GENERATOR NEW_OUTPUT PRIOR_ROOT [PRIOR_ROOT ...]

The supplied prior roots must include every relevant fitting, validation and
selection game known to the caller. Exact disjointness is checked only against
the records found under those roots; it does not prove complete model ancestry,
semantic scene independence, or real grasp/release behavior. Scene generation
is intentionally separate from candidate selection and evaluation.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[4]
SOURCE = PROJECT / 'datasets/visual-control/expanded-rooms-v1/generate-diverse.flex'
TEMPLATE = PROJECT / 'flex/sim/cases/find-return-house.json'
BASE_SEED = 1700000000


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def prior_inventory(roots):
    seeds, cases, environments, rows = set(), set(), set(), []
    for root in roots:
        if not root.is_dir():
            raise ValueError(f'missing prior root: {root}')
        game_count = shard_count = 0
        fingerprint = hashlib.sha256()
        for file in sorted(root.rglob('result.json')):
            result = json.loads(file.read_text())
            seed = result.get('seed')
            scene = file.parent / 'scene'
            if not isinstance(seed, int) or isinstance(seed, bool):
                continue
            seeds.add(seed)
            if not (scene / 'case.json').is_file() or not (scene / 'environment.bin').is_file():
                raise ValueError(f'seeded prior game lacks scene files: {file}')
            case_sha = digest(scene / 'case.json')
            env_sha = digest(scene / 'environment.bin')
            cases.add(case_sha)
            environments.add(env_sha)
            fingerprint.update(f'{file.relative_to(root)}\0{digest(file)}\0{case_sha}\0{env_sha}\n'.encode())
            game_count += 1
        for file in sorted(root.rglob('report.json')):
            report = json.loads(file.read_text())
            seed, episodes = report.get('seed'), report.get('episodes')
            if isinstance(seed, int) and not isinstance(seed, bool) and isinstance(episodes, int) and not isinstance(episodes, bool) and 0 < episodes <= 100000:
                if report.get('complete') is not True:
                    raise ValueError(f'incomplete prior shard: {file}')
                for index in range(episodes):
                    result = file.parent / f'expert-{index}' / 'result.json'
                    if not result.is_file() or json.loads(result.read_text()).get('seed') != seed + index:
                        raise ValueError(f'missing or mismatched prior shard game: {result}')
                seeds.update(range(seed, seed + episodes))
                fingerprint.update(f'{file.relative_to(root)}\0{digest(file)}\n'.encode())
                shard_count += 1
        if not game_count and not shard_count:
            raise ValueError(f'no prior games or shards found in {root}')
        rows.append({'root': str(root.resolve()), 'games': game_count, 'shards': shard_count, 'inventorySHA256': fingerprint.hexdigest()})
    return seeds, cases, environments, rows


def main():
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    generator, output = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    roots = [Path(arg).resolve() for arg in sys.argv[3:]]
    if not generator.is_file() or output.exists():
        raise ValueError('generator must exist and output must not exist')
    if any(root == output or root in output.parents for root in roots):
        raise ValueError('output must be outside every prior root')
    seeds, cases, environments, inventory = prior_inventory(roots)
    heldout_seeds = {BASE_SEED + level * 100 + i for level in range(1, 6) for i in range(32)}
    if seeds & heldout_seeds:
        raise ValueError('held-out seed overlaps supplied prior game or shard records')
    output.mkdir(parents=True)
    hashes = {'generator': digest(generator), 'generatorSource': digest(SOURCE), 'caseTemplate': digest(TEMPLATE), 'reservationTool': digest(Path(__file__))}
    subprocess.run([str(generator), str(output / 'generated'), '226', '290', 'held-out'], cwd=PROJECT, check=True)
    rows = []
    for level in range(1, 6):
        for i in range(32):
            layout = 226 + i if level < 4 else 227 + 2 * i
            scene = output / 'generated' / str(layout) / str(i % 16)
            metadata = json.loads((scene / 'layout.json').read_text())
            if metadata.get('layoutId') != layout or metadata.get('fit') is not False or metadata.get('reservedHeldOut') is not True:
                raise ValueError(f'invalid reserved layout: {scene}')
            if len(metadata['rooms']) != (1 + layout % 2) or (level >= 4 and len(metadata['rooms']) != 2):
                raise ValueError(f'invalid room count: {scene}')
            case_sha, env_sha = digest(scene / 'case.json'), digest(scene / 'environment.bin')
            if case_sha in cases or env_sha in environments:
                raise ValueError(f'exact scene file overlap with supplied prior roots: {scene}')
            rows.append({'level': level, 'index': i, 'seed': BASE_SEED + level * 100 + i,
                         'scene': str(scene.relative_to(output)), 'layoutId': layout,
                         'caseSHA256': case_sha, 'environmentSHA256': env_sha,
                         'layoutSHA256': digest(scene / 'layout.json'), 'startPose': metadata['startPose']})
    if len({row['seed'] for row in rows}) != 160:
        raise ValueError('duplicate held-out game seeds')
    for level in range(1, 6):
        group = [row for row in rows if row['level'] == level]
        if len({row['environmentSHA256'] for row in group}) != 32 or len({tuple(row['startPose']) for row in group}) != 32:
            raise ValueError(f'level {level} lacks 32 distinct environment files and recorded start poses')
    result = {'status': 'reserved_not_evaluated', 'task': 'virtual-fetch', 'actionsPerGame': 300,
              'actionSeconds': 0.2, 'levels': [1, 2, 3, 4, 5], 'gamesPerLevel': 32,
              'teacher': 'explore-teacher', 'cameraPitchDegrees': 82,
              'inputsSHA256': hashes, 'priorRoots': inventory,
              'independenceScope': 'exact seed and scene-file disjointness only against supplied prior records; model ancestry and similar geometry not proven',
              'generatorScope': 'binary and source hashes recorded separately; their correspondence is not established by this tool',
              'physicalScope': 'virtual pickup and visual docking; physical grasp and release not established',
              'rows': rows}
    if hashes != {'generator': digest(generator), 'generatorSource': digest(SOURCE), 'caseTemplate': digest(TEMPLATE), 'reservationTool': digest(Path(__file__))}:
        raise ValueError('generator inputs changed during reservation')
    if prior_inventory(roots)[3] != inventory:
        raise ValueError('prior records changed during reservation')
    (output / 'manifest.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': result['status'], 'games': len(rows), 'output': str(output), 'priorRoots': inventory}))


if __name__ == '__main__':
    main()
