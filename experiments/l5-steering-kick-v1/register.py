#!/usr/bin/env python3
"""Disabled pre-run registration of the isolated steering selection plan.

Only saved metadata under the explicitly named historical roots is inventoried;
no held-out catalog is opened, and unrecorded pretrained ancestry is unknown.
"""
import hashlib
import importlib.util
import json
import math
import os
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
MANIFEST = P / 'l5-steering-kick-plan-v1.json'
# Explicit known training/selection roots only: do not traverse arbitrary old
# test sets, unlabelled holdouts, or unrelated simulator experiments.
HISTORY = tuple(P / name for name in (
    'kturn-L0', 'kturn-L1', 'kturn-L2', 'kturn-L3', 'kturn-L4', 'kturn-L5',
    'search-dagger', 'search-dagger-4workers', 'search-dagger-four-pilot',
    'search-dagger-l35-4workers', 'search-dagger-l35-pilot', 'search-dagger-l4-matched',
    'search-dagger-l4-matched-pilot', 'search-dagger-pilot',
    'search-dagger-heading', 'search-dagger-heading-pilot'))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


plan = load('steering_registration_plan', HERE / 'plan.py')
prepare = load('steering_registration_build', HERE / 'prepare.py')
base = prepare.base


def source_paths():
    levels = ROOT / 'datasets/visual-control/chase-v1/levels'
    return [HERE / x for x in ('plan.py', 'transform.py', 'probe.flex', 'prepare.py', 'build-supervisor.py', 'register.py', 'register-supervisor.py', 'runner.py', 'audit.py', 'monitor.py')] + [
        levels / x for x in ('package-matched-epoch8.py', 'run-route-factorial.py', 'route-coverage.py',
                             'prepare-route-factorial.py', 'audit-matched-training.py',
                             'heading-selection-metrics.py', 'search-loops-odometry.py', 'audit-heldout.py',
                             'qualify-selection.py', 'audit-selection.py')] + [
        ROOT / 'flex/tests/run-physical-hidden-trial.py', ROOT / 'flex/tests/run-physical-rescan-trial.py',
        ROOT / 'flex/tests/run-physical-hybrid-trial.py', ROOT / 'flex/tests/monitored-visual-v4-smoke.py',
        ROOT / 'flex/tests/supervise-heading-overlays.py',
        ROOT / 'experiments/sim-stop-supervisor/supervisor.py',
        ROOT / 'experiments/sim-stop-supervisor/proxy.py',
        Path(sys.executable).resolve(),
        ROOT / 'build/flex/control/simulator', ROOT / 'build/flex/sim/puppybot.bin', ROOT / 'puppybot.json',
        ROOT / 'flex/sim/cases/find-return-house.json', plan.BUILD / 'control', plan.BUILD / 'build.json',
        plan.MODEL / 'policy', plan.MODEL / 'weights.bin', plan.MODEL / 'receipt.json',
        plan.MODEL.parent / 'manifest.json'] + sorted((plan.MODEL / 'kernels').iterdir())


def runtime_chain():
    path = (ROOT / 'build/flex/rocm-runtime/libamdhip64.so').absolute(); seen = set(); result = {}
    while path.is_symlink():
        if path in seen or len(seen) >= 16: raise ValueError('runtime symlink cycle')
        seen.add(path); target = os.readlink(path); result[str(path)] = 'link:' + target
        path = Path(os.path.abspath(path.parent / target))
    if not path.is_file(): raise ValueError('runtime target missing')
    result[str(path)] = 'sha256:' + base.sha(path)
    return result


def historical_inventory(roots=HISTORY, excluded=(plan.OUTPUT, plan.BUILD), require_known=True):
    """Inventory result/report seed fields; skips held-out-labelled paths and symlinks."""
    candidates = {row['seed'] for row in plan.design()['conditions']}; files = []; skipped_links = []
    for root in roots:
        root = Path(root)
        if not root.is_dir() or root.is_symlink(): raise ValueError('historical root missing or symlinked')
        def walk_error(error):
            raise error
        for directory, dirs, names in os.walk(root, followlinks=False, onerror=walk_error):
            here = Path(directory)
            keep = []
            for name in dirs:
                child = here / name; lower = name.lower().replace('-', '').replace('_', '')
                if 'heldout' in lower or child in excluded: continue
                if child.is_symlink(): skipped_links.append(str(child)); continue
                keep.append(name)
            dirs[:] = keep
            for name in ('result.json', 'report.json'):
                if name not in names: continue
                file = here / name
                if file.is_symlink() or file.stat().st_size > 16 * 1024**2:
                    raise ValueError(f'unsafe historical metadata: {file}')
                data = file.read_bytes()
                try: report = json.loads(data)
                except (ValueError, UnicodeDecodeError) as error: raise ValueError(f'invalid historical metadata: {file}') from error
                if not isinstance(report, dict): raise ValueError(f'invalid historical object: {file}')
                seed = report.get('seed')
                if seed is not None:
                    if type(seed) is not int: raise ValueError(f'invalid historical seed: {file}')
                    count = report.get('episodes', 1)
                    if type(count) is not int or not 1 <= count <= 100000: raise ValueError(f'invalid historical range: {file}')
                    if any(seed <= candidate < seed + count for candidate in candidates):
                        raise ValueError(f'pilot seed overlaps recorded history: {file}')
                files.append((str(file), hashlib.sha256(data).hexdigest()))
    if not files: raise ValueError('empty historical metadata inventory')
    if require_known:
        required = list(P.glob('kturn-L[0-5]/shard-*/report.json'))
        for root in (P / 'search-dagger-4workers/dagger-L3', P / 'search-dagger-l35-4workers/dagger-L5',
                     P / 'search-dagger-l4-matched/dagger-L4'):
            required.extend(root.glob('shard-*/report.json'))
        if len(required) != 60 or len({str(path) for path in required}) != 60 or not {str(path) for path in required}.issubset({path for path, _ in files}):
            raise ValueError('known 60 source-shard inventory incomplete')
    fingerprint = hashlib.sha256()
    for path, digest in sorted(files): fingerprint.update((path + '\0' + digest + '\n').encode())
    return {'roots': [str(Path(root)) for root in roots], 'records': len(files),
            'sha256': fingerprint.hexdigest(), 'skippedSymlinkDirectories': sorted(skipped_links),
            'scope': 'result.json and report.json under named roots only; skips held-out-labelled paths and symlinked directories; does not establish unrecorded history or pretraining ancestry'}


def scene_rows():
    rows = []
    for row in plan.design()['conditions']:
        scene = Path(row['scene'])
        if scene.is_symlink() or not scene.is_dir() or {p.name for p in scene.iterdir()} != {'case.json','environment.bin','layout.json'}:
            raise ValueError('invalid training scene inventory')
        links = {}
        for name in ('case.json', 'environment.bin', 'layout.json'):
            path = scene / name
            if path.is_symlink():
                if name == 'case.json': raise ValueError('symlink scene case')
                target = os.readlink(path); resolved = Path(os.path.abspath(path.parent / target))
                canonical = scene.parent / name
                if resolved != canonical or canonical.is_symlink() or not canonical.is_file():
                    raise ValueError('unexpected scene symlink target')
                links[name] = target
            elif path.is_file(): links[name] = None
            else: raise ValueError('missing scene file')
        files = {name: base.sha(scene / name) for name in ('case.json','environment.bin','layout.json')}
        metadata = json.loads((scene / 'layout.json').read_text())
        if (metadata.get('layoutId') != row['layout'] or metadata.get('fit') is not True or
                metadata.get('reservedHeldOut') is True or type(metadata.get('startRoom')) is not int or
                metadata['startRoom'] != 0 or not isinstance(metadata.get('rooms'), list) or len(metadata['rooms']) != 2):
            raise ValueError('scene is not declared training fit')
        data = (scene / 'environment.bin').read_bytes()
        if len(data) < 256 or data[:8] != b'PBENV001': raise ValueError('invalid environment')
        count, vertices, repeated = struct.unpack_from('<qqq', data, 8)
        if (not 1 <= count <= 160 or vertices < 3 or vertices % 3 or vertices != repeated or
                len(data) != 256 + count * 128 + vertices * 72):
            raise ValueError('invalid environment dimensions')
        pose = struct.unpack_from('<3d', data, 96)
        if not all(math.isfinite(v) for v in pose): raise ValueError('nonfinite spawn')
        walls = [struct.unpack_from('<d', data, 256 + i * 128 + 48)[0] for i in range(count)
                 if data[256 + i * 128:256 + i * 128 + 48].startswith(b'Wall.partition')]
        if len(walls) != 2 or not all(math.isfinite(wall) and wall > pose[0] for wall in walls) or walls[0] != walls[1]:
            raise ValueError('invalid two-room partition')
        rooms = metadata['rooms']
        if (any(not isinstance(room, list) or len(room) != 4 or
                any(type(value) not in (int, float) or not math.isfinite(value) for value in room) or
                room[0] >= room[2] or room[1] >= room[3] for room in rooms) or
                not rooms[0][0] <= pose[0] <= rooms[0][2] or not rooms[0][1] <= pose[1] <= rooms[0][3] or
                abs(rooms[0][2] - walls[0]) > 1e-9 or abs(rooms[1][0] - walls[0]) > 1e-9):
            raise ValueError('invalid room bounds, spawn or shared partition')
        rows.append({**row, 'files': files, 'sceneLinks': links, 'spawn': list(pose)})
    return rows


def current(include_history=True):
    build = prepare.verify(plan.BUILD)
    models = plan.MODEL.parent.parent
    base.package.verify(models / 'control-s0', models / 'treatment-s0', plan.MODEL.parent)
    paths = source_paths()
    if len({str(x) for x in paths}) != len(paths) or any(not x.is_file() or x.is_symlink() for x in paths):
        raise ValueError('missing or symlinked registered input')
    identities = {str(path): base.sha(path) for path in paths}
    return {'schema': 'puppybot.l5-steering-kick-plan.v1', 'status': 'frozen_before_play',
            'design': plan.design(), 'build': build, 'files': identities, 'runtime': runtime_chain(),
            'scenes': scene_rows(), 'history': historical_inventory() if include_history else None,
            'scope': 'prior metadata inventoried only under named roots; source/model/runtime pins and local data are not OS attestation; training-family selection is not held-out or physical evidence'}


def verify():
    saved = json.loads(MANIFEST.read_text())
    if current() != saved: raise ValueError('registered steering inputs or prior metadata changed')
    return saved


def freeze():
    with base.acquire_lock(P / '.l4-matched.lock'):
        for path in (MANIFEST, plan.OUTPUT): base.require_new_output(path)
        base.require_capacity(P, 36 * 1024**3)
        frozen = current()
        if current() != frozen: raise ValueError('registration inputs changed')
        base.require_capacity(P, 36 * 1024**3)
        for path in (MANIFEST, plan.OUTPUT): base.require_new_output(path)
        with MANIFEST.open('x') as stream:
            json.dump(frozen, stream, sort_keys=True, indent=2, allow_nan=False); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        fd = os.open(MANIFEST.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)
        return frozen


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and bounded CPU registration.')
