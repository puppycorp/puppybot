#!/usr/bin/env python3
"""Check the navigation curriculum's observation boundary and native evidence."""
import argparse
import json
import math
from pathlib import Path
import subprocess
import sys

sys.path = [p for p in sys.path if Path(p).resolve() != Path(__file__).resolve().parent]
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'flex/exploration'))
from bootstrap import distances, module
from policy import sha256
from seek_native import audit, hide_brick, room_at
from seek_policy import SeekNetwork, proposals


def observation_boundary():
    mapper = module('find_return_mapper_checks', ROOT/'flex/vision/discovery.py')
    empty = np.zeros((200, 200), np.int32)
    for returning in (False, True):
        safe, known, blocked, goals = mapper.navigation(empty, empty, [0, 0, 0], [],
            dict(returning=returning, box=[.34, -.24]))
        assert not safe.any() and not known.any() and not blocked.any() and not goals
    free = empty.copy()
    free[85:116, 85:116] = 10
    occupied = empty.copy()
    occupied[96:99, 108:111] = 3
    pose = [0, 0, 0]
    baseline = mapper.navigation(free, occupied, pose, [])
    task = dict(returning=True, box=[.34, -.24])
    current = mapper.navigation(free, occupied, pose, [], task)
    for before, after in zip(baseline[:3], current[:3]):
        np.testing.assert_array_equal(before, after)
    routes = distances(current[0], pose)
    candidates = proposals([], current[0], routes, pose, task)
    assert candidates
    for _, goal, _ in candidates:
        col, row = np.floor((np.asarray(goal[:2])+10)/.1).astype(int)
        assert current[0][row, col]
        assert .36 <= math.dist(goal[:2], task['box']) <= .58
        error = math.atan2(task['box'][1]-goal[1], task['box'][0]-goal[0])-goal[2]
        assert abs(error) < 1e-12
    print('Find-return boundary passed: blackout stays unknown; box memory adds only observed-floor goals; safety masks unchanged')


def cli(binary):
    catalog = subprocess.run([str(binary), '--list-cases'], cwd=ROOT, capture_output=True, text=True, check=True)
    entries = json.loads(catalog.stdout)['cases']
    assert next(entry for entry in entries if entry['id'] == 'find-return-house')['controller'] == 'rgb-find-return'
    rejection = subprocess.run([str(binary), '--case', 'find-return-house', '--headless', '--steps', '1'],
        cwd=ROOT, capture_output=True, text=True)
    assert rejection.returncode == 2 and 'rendering' in rejection.stderr
    print('Find-return CLI passed: named task is available; camera task rejects headless execution')


def hidden_scene():
    generator = module('hidden_scene_checks', ROOT/'flex/scripts/generate-layout.py')
    layout = hide_brick(generator.generate(96001, 2), generator)
    assert len(layout['case']['objects']) == 1
    brick = layout['case']['objects'][0]['position']
    assert math.dist(brick[:2], layout['spawn'][:2]) >= 4.3
    assert room_at(layout, brick[:2]) != layout['startRoom']
    reached = generator.flood(generator.free_grid(layout['bounds'], layout['objects']), layout['bounds'], layout['spawn'])
    col, row = np.floor((np.asarray(brick[:2])-layout['bounds'][:2])/.1).astype(int)
    assert reached[row, col]
    assert layout['findReturnTask']['requiresLeavingStartRoom']
    assert layout['findReturnTask']['minimumExcursionM'] >= 1.5
    print('Hidden-scene preflight passed: one reachable brick in a different room, outside initial camera range')


def training(directory):
    manifest = json.loads((directory/'manifest.json').read_text())
    report = json.loads((directory/'report.json').read_text())
    split = manifest['splits']
    for a, b in (('train', 'validation'), ('train', 'test'), ('validation', 'test')):
        assert not set(split[a]) & set(split[b])
    assert sha256(directory/'checkpoint.npz') == report['checkpointSHA256']
    model = SeekNetwork.load(directory/'checkpoint.npz')
    assert sum(value.size for value in model.params.values()) == report['parameters'] == 4258
    assert model.params['w1'].shape[0] == 32
    for mode in ('heuristic', 'mlp'):
        assert [r['seed'] for r in report['heldoutGridEpisodes'][mode]] == split['test']
    print('Training evidence passed: disjoint scenes, retained checkpoint identity and paired complete grid episodes')


def comparison(directory, frozen):
    result = json.loads((directory/'summary.json').read_text())
    assert result['complete']
    expected = {(seed, mode) for seed in result['plan']['seeds'] for mode in result['plan']['policies']}
    assert {(row['seed'], row['policy']) for row in result['rows']} == expected
    assert sha256(frozen/'frozen-source-manifest.json') == result['plan']['frozenManifestSHA256']
    for path, digest in json.loads((frozen/'frozen-source-manifest.json').read_text()).items():
        assert sha256(Path(path)) == digest, path
    for row in result['rows']:
        _, checks = audit(Path(row['run']), frozen/'workspace')
        expected_pass = checks['taskSuccess'] and (not checks['explorationRequired'] or checks['explorationDemonstrated'])
        assert row['taskPassed'] == expected_pass
        if row['taskPassed']:
            assert row['exitCode'] == 0 and not row['timedOut']
        if row['policy'] == 'mlp':
            assert checks['modelHashes'] == [result['plan']['weightsSHA256']]
    print('Native comparison passed: complete paired matrix, unchanged frozen sources and independent RGB/motion/return audits')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path)
    parser.add_argument('--training', type=Path)
    parser.add_argument('--comparison', type=Path)
    parser.add_argument('--frozen', type=Path)
    args = parser.parse_args()
    observation_boundary()
    hidden_scene()
    if args.binary:
        cli(args.binary.resolve())
    if args.training:
        training(args.training.resolve())
    if args.comparison:
        assert args.frozen is not None
        comparison(args.comparison.resolve(), args.frozen.resolve())


if __name__ == '__main__':
    main()
