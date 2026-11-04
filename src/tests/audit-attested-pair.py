#!/usr/bin/env python3
"""Audit a completed non-lean, one-game original/instrumented pilot pair.

Usage: audit-attested-pair.py PILOT_DIRECTORY
This checks recorded evidence, not runtime identity, independent camera
integrity, GPU execution, or repeatability beyond this particular pair.
"""
import base64
import hashlib
import importlib.util
import json
import math
import os
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_json(path):
    return json.loads(path.read_text(), parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite JSON number')))


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def floats(values, count):
    if not isinstance(values, list) or len(values) != count or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in values):
        raise ValueError('invalid action or feedback')
    return struct.pack(f'<{count}f', *values)


def check_manifest(root):
    manifest = load_json(root / 'inputs.json')
    if manifest.get('schema') != 'puppybot.actor-pilot.v1':
        raise ValueError('invalid pilot schema')
    seed, horizon = manifest.get('seed'), manifest.get('horizon')
    if type(seed) is not int or seed < 0 or type(horizon) is not int or not 1 <= horizon <= 512:
        raise ValueError('invalid seed or horizon')
    files = manifest.get('files')
    if not isinstance(files, dict) or not files:
        raise ValueError('missing pinned files')
    paths = {}
    for name in ('sceneCatalog', 'model', 'originalControl', 'instrumentedControl', 'cwd'):
        value = manifest.get(name)
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise ValueError('expected absolute manifest path: ' + name)
        paths[name] = Path(value)
    model, scene, cwd = paths['model'], paths['sceneCatalog'] / '0', paths['cwd']
    required = [paths['originalControl'], paths['instrumentedControl'], cwd / 'build/flex/control/simulator',
                scene / 'case.json', scene / 'environment.bin', scene / 'layout.json', cwd / 'build/flex/sim/puppybot.bin', cwd / 'puppybot.json',
                model / 'policy', model / 'weights.bin', model / 'receipt.json']
    kernels = load_json(model / 'receipt.json').get('kernels')
    if not isinstance(kernels, dict) or len(kernels) < 5 or any(not isinstance(name, str) or '/' in name or name in ('', '.', '..') for name in kernels):
        raise ValueError('invalid kernel receipt')
    required += [model / 'kernels' / name for name in kernels]
    for path in required:
        if str(path) not in files:
            raise ValueError('required file not pinned: ' + str(path))
    for path, expected in files.items():
        if not isinstance(path, str) or not Path(path).is_absolute() or not isinstance(expected, str) or len(expected) != 64 or any(c not in '0123456789abcdef' for c in expected) or sha(Path(path)) != expected:
            raise ValueError('pinned file changed or invalid: ' + str(path))
    return manifest, paths


def check_arm(root, arm, manifest, paths):
    base = root / arm
    run = base / 'run'
    game = run / str(manifest['seed'])
    status = load_json(base / 'monitor/supervisor-result.json')
    if status.get('clientExit') != 0 or status.get('timedOut') is not False or status.get('signal') is not None or status.get('remainingWorkersTerminated') is not False or type(status.get('processGroup')) is not int or status['processGroup'] <= 0:
        raise ValueError(arm + ' supervisor did not finish cleanly')
    command = load_json(base / 'command.json')
    if not isinstance(command, list) or any(not isinstance(x, str) for x in command):
        raise ValueError('invalid command')
    control = paths['originalControl' if arm == 'original' else 'instrumentedControl']
    expected = [str(control), 'run', '--chase', '--fetch', '--policy', str(paths['model']), '--scene-catalog', str(paths['sceneCatalog']), '--output', str(run), '--episodes', '1', '--horizon', str(manifest['horizon']), '--seed', str(manifest['seed']), '--level', '5', '--wheel-odometry', '--camera-pitch', '82']
    # Options are interpreted as a set of paired flags; ordering itself is
    # preserved separately when matching the native instrumented argv.
    if len(command) != len(expected) or command[:2] != expected[:2]:
        raise ValueError(arm + ' command shape differs from pilot')
    def options(items):
        result = {}; i = 0
        while i < len(items):
            key = items[i]
            if not key.startswith('--') or key in result:
                raise ValueError('invalid or duplicate pilot option')
            if key in ('--chase', '--fetch', '--wheel-odometry'):
                result[key] = None; i += 1
            else:
                if i + 1 >= len(items):
                    raise ValueError('missing pilot option value')
                result[key] = items[i + 1]; i += 2
        return result
    if options(command[2:]) != options(expected[2:]):
        raise ValueError(arm + ' command differs from pilot')
    summary = load_json(run / 'summary.json'); result = load_json(game / 'result.json')
    if summary.get('complete') is not True or summary.get('episodes') != 1 or result.get('seed') != manifest['seed'] or result.get('steps') != manifest['horizon']:
        raise ValueError(arm + ' run incomplete')
    for name in ('policy', 'weights.bin', 'receipt.json'):
        if sha(run / 'policy' / name) != sha(paths['model'] / name):
            raise ValueError(arm + ' policy snapshot differs')
    for name in load_json(paths['model'] / 'receipt.json')['kernels']:
        if sha(run / 'policy/kernels' / name) != sha(paths['model'] / 'kernels' / name):
            raise ValueError(arm + ' kernel snapshot differs')
    for name in ('case.json', 'environment.bin'):
        if sha(game / 'scene' / name) != sha(paths['sceneCatalog'] / '0' / name):
            raise ValueError(arm + ' scene snapshot differs')
    with (game / 'chase.jsonl').open() as stream:
        placements = [json.loads(line, parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite JSON number'))) for line in stream]
    if not placements or placements[0].get('event') != 'start' or placements[0].get('step') != 0:
        raise ValueError(arm + ' missing initial target placement')
    for event in placements:
        if type(event.get('step')) is not int or not 0 <= event['step'] <= manifest['horizon'] or event.get('event') not in ('start', 'delivery'):
            raise ValueError(arm + ' invalid placement event')
        for key, count in (('brick', 2), ('robot', 3)):
            values = event.get(key)
            if not isinstance(values, list) or len(values) != count or any(type(x) not in (int, float) or not math.isfinite(x) for x in values):
                raise ValueError(arm + ' invalid placement coordinates')
    initial = load_json(game / 'initial.json')
    with (game / 'decisions.jsonl').open() as stream:
        rows = [json.loads(line, parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite JSON number'))) for line in stream]
    if len(rows) != manifest['horizon']:
        raise ValueError(arm + ' incomplete decisions')
    frames = [initial.get('totalSteps')] + [row['state']['totalSteps'] for row in rows]
    if any(type(x) is not int or x < 0 for x in frames) or any(b != a + 10 for a, b in zip(frames, frames[1:])):
        raise ValueError(arm + ' invalid observation frames')
    for row in rows:
        floats(row.get('action'), 2); floats(row.get('proprio'), 7)
    return {'game': game, 'run': run, 'command': command, 'rows': rows, 'frames': frames, 'result': result, 'placements': placements}


def audit(root):
    root = Path(root).absolute()
    manifest, paths = check_manifest(root)
    original = check_arm(root, 'original', manifest, paths)
    instrumented = check_arm(root, 'instrumented', manifest, paths)
    actor = load_module('actor_audit', ROOT / 'datasets/visual-control/chase-v1/levels/audit-actor-attestation.py')
    argv = load_module('argv_audit', ROOT / 'flex/tests/audit-attested-argv.py')
    checked_actor = actor.audit(instrumented['game'] / 'actor-attestation.bin', instrumented['game'])
    checked_argv = argv.audit(instrumented['run'] / 'argv.bin')
    records = checked_argv['records']
    if len(records) != 3 or [x['kind'] for x in records] != ['control', 'child_exec_intent', 'child_exec_intent']:
        raise ValueError('unexpected instrumented argv records')
    args = [[os.fsdecode(base64.b64decode(x, validate=True)) for x in row['argvBase64']] for row in records]
    run = instrumented['run']; game = instrumented['game']; model = paths['model']
    policy_argv = [str(run / 'policy/policy'), str(run / 'policy/weights.bin'), sha(model / 'weights.bin'), str(run / 'policy/kernels'), '3']
    simulator_argv = [str(paths['cwd']) + '/./build/flex/control/simulator', '--hidden', '--case-file', str(game / 'scene/case.json'), '--environment', str(game / 'scene/environment.bin'), '--steps', '1000000', '--bind', '127.0.0.1:0', '--agent-fd', '3', '--observer-distance-mm', '2500', '--tcp-view', '--no-visual-odometry', '--camera-pitch', '82', '--video', str(game / 'mission.mp4'), '--video-fps', '5', '--record', str(game / 'trace.jsonl'), '--capture', str(game / 'outcome.png'), '--search-output', str(game / 'sensor')]
    if args != [instrumented['command'], policy_argv, simulator_argv]:
        raise ValueError('instrumented argv differs from intended launch')
    differences = []
    if original['frames'] != instrumented['frames']:
        differences.append('frame ticks differ')
    if original['placements'] != instrumented['placements']:
        differences.append('target placement events differ')
    if original['result'] != instrumented['result']:
        differences.append('game result differs')
    for i, (a, b) in enumerate(zip(original['rows'], instrumented['rows'])):
        for key, n in (('action', 2), ('proprio', 7)):
            if floats(a[key], n) != floats(b[key], n):
                differences.append(f'{key} differs at action {i}')
    for i, (a, b) in enumerate(zip(original['frames'], instrumented['frames'])):
        for ext in ('rgb', 'feedback'):
            left = original['game'] / f'actor-{a}.{ext}'; right = instrumented['game'] / f'actor-{b}.{ext}'
            expected_size = checked_actor['imageBytes'] if ext == 'rgb' else 28
            lbytes, rbytes = left.read_bytes(), right.read_bytes()
            if len(lbytes) != expected_size or len(rbytes) != expected_size:
                raise ValueError('invalid saved observation size')
            if lbytes != rbytes:
                differences.append(f'actor {ext} differs at observation {i}')
    # Verify each instrumented pre-action image against the original saved image.
    with (instrumented['game'] / 'actor-attestation.bin').open('rb') as stream:
        stream.seek(56)
        size = checked_actor['imageBytes']; width = checked_actor['memoryWidth']
        stride_rest = (size + 7 + width) * 4 + (2 + width) * 4 + 8
        for i, frame in enumerate(original['frames'][:-1]):
            header = stream.read(24); image = stream.read(size); stream.seek(stride_rest, 1)
            if len(header) != 24 or len(image) != size:
                raise ValueError('truncated actor journal')
            # Initial saved image predates target placement at the same tick.
            if i > 0 and image != (original['game'] / f'actor-{frame}.rgb').read_bytes():
                differences.append(f'journal image differs from original at action {i}')
    return {'status': 'compared', 'parity': False if differences else None, 'comparedSignalsMatch': not differences, 'differences': differences,
            'actions': manifest['horizon'], 'firstActorImageCompared': False, 'actorAudit': checked_actor, 'argvAudit': checked_argv,
            'scope': 'one recorded pair only; original first policy image is unavailable after target placement; provenance pins and monitor reports do not authenticate loaded binaries, GPU execution, camera frames, or physical robot behavior'}


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    print(json.dumps(audit(Path(sys.argv[1])), sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, OverflowError, struct.error, json.JSONDecodeError) as error:
        raise SystemExit(f'Invalid pilot pair: {error}')
