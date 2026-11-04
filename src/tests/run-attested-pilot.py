#!/usr/bin/env python3
"""Run one bounded original/instrumented pair on a training selection scene.

This is a diagnostic pilot, not held-out qualification or a hardware test.
It requires an otherwise idle GPU. Existing outputs are never replaced; failed
runs and partial outputs are retained for inspection.
"""
import fcntl
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LEVELS = ROOT / 'datasets/visual-control/chase-v1/levels'
PITCH = ROOT / 'build/flex/sim/levels-v2/pitch82'
EXPERIMENT = PITCH / 'search-dagger-l4-matched'
PACKAGE = EXPERIMENT / 'epoch8-pair'
MODEL = PACKAGE / 'control'
SOURCE_SCENE = ROOT / 'build/flex/sim/expanded-rooms-v1/scenes/15/1'
OUTPUT = EXPERIMENT / 'actor-attested-pilot'
ORIGINAL = ROOT / 'build/flex/control/control'
SIMULATOR = ROOT / 'build/flex/control/simulator'
SEED, HORIZON, WALL_SECONDS = 7800001, 300, 300


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


prepare = module('attested_build', ROOT / 'flex/tests/prepare-attested-control.py')
package = module('epoch8_package', LEVELS / 'package-matched-epoch8.py')
training = module('matched_training', LEVELS / 'audit-matched-training.py')
monitor = module('supervised_trial', ROOT / 'flex/tests/run-physical-hidden-trial.py')


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def require_space(path, minimum):
    if shutil.disk_usage(path).free < minimum:
        raise RuntimeError(f'insufficient free space at {path}')


def command(binary, catalog, output):
    return [str(binary), 'run', '--chase', '--scene-catalog', str(catalog), '--output', str(output),
            '--episodes', '1', '--horizon', str(HORIZON), '--seed', str(SEED), '--wheel-odometry',
            '--policy', str(MODEL), '--fetch', '--level', '5', '--camera-pitch', '82']


def pinned_files(instrumented, catalog):
    files = [ORIGINAL, instrumented, SIMULATOR, ROOT / 'build/flex/control/compiler',
             ROOT / 'build/flex/sim/puppybot.bin', ROOT / 'puppybot.json', ROOT / 'build/flex/rocm-runtime/libamdhip64.so',
             ROOT / 'flex/tests/run-attested-pilot.py', ROOT / 'flex/tests/prepare-attested-control.py',
             ROOT / 'flex/tests/audit-attested-argv.py', ROOT / 'flex/tests/audit-attested-pair.py',
             ROOT / 'flex/tests/run-physical-hidden-trial.py', ROOT / 'flex/tests/run-physical-rescan-trial.py',
             ROOT / 'flex/tests/run-physical-hybrid-trial.py', LEVELS / 'audit-actor-attestation.py',
             LEVELS / 'audit-selection.py', LEVELS / 'audit-matched-training.py', LEVELS / 'package-matched-epoch8.py',
             EXPERIMENT / 'training-inputs.sha256', EXPERIMENT / 'training-match.json', PACKAGE / 'manifest.json',
             instrumented.parent / 'build.json']
    files.extend(MODEL / name for name in ('weights.bin', 'policy', 'receipt.json', 'training-receipt.json'))
    built = json.loads((instrumented.parent / 'build.json').read_text())
    if (built.get('schema') != 'puppybot.attested-control-build.v1' or
            sha(instrumented) != built.get('binarySHA256') or
            sha(ROOT / 'build/flex/control/compiler') != built.get('compilerSHA256')):
        raise ValueError('isolated build binary or compiler differs from its receipt')
    archived = instrumented.parent / 'flex'
    for name, expected in built['sourceSHA256'].items():
        path = archived / name
        if sha(path) != expected:
            raise ValueError(f'isolated source snapshot changed: {path}')
        files.append(path)
    receipt = json.loads((MODEL / 'receipt.json').read_text())
    files.extend(MODEL / 'kernels' / name for name in sorted(receipt['kernels']))
    for scene in (SOURCE_SCENE, catalog / '0'):
        files.extend(scene / name for name in ('case.json', 'environment.bin', 'layout.json'))
    return {str(path): sha(path) for path in files}


def verify_pins(pins):
    if any(sha(Path(path)) != expected for path, expected in pins.items()):
        raise ValueError('a pinned pilot input changed')


def main():
    os.chdir(ROOT)
    with (PITCH / '.l4-matched.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if OUTPUT.exists() or OUTPUT.is_symlink():
            raise ValueError(f'output already exists; preserve it: {OUTPUT}')
        require_space(PITCH, 12 * 1024**3)
        package.verify(EXPERIMENT / 'control-s0', EXPERIMENT / 'treatment-s0', PACKAGE)
        check = training.audit(PITCH / 'search-dagger-l35-4workers/student-s0',
                               EXPERIMENT / 'control-s0', EXPERIMENT / 'treatment-s0')
        if check != json.loads((EXPERIMENT / 'training-match.json').read_text()):
            raise ValueError('training comparison changed')
        subprocess.run(['/usr/bin/sha256sum', '-c', str(EXPERIMENT / 'training-inputs.sha256')],
                       check=True, stdout=subprocess.DEVNULL)
        layout = json.loads((SOURCE_SCENE / 'layout.json').read_text())
        if layout.get('fit') is not True or layout.get('layoutId') != 15 or layout.get('startRoom') != 0:
            raise ValueError('pilot scene is not a training selection layout')
        OUTPUT.mkdir()
        catalog = OUTPUT / 'catalog'; scene = catalog / '0'; scene.mkdir(parents=True)
        for name in ('case.json', 'environment.bin', 'layout.json'):
            shutil.copyfile(SOURCE_SCENE / name, scene / name)
            if sha(SOURCE_SCENE / name) != sha(scene / name):
                raise ValueError('scene changed while snapshotting')
        build = OUTPUT / 'build'; prepare.prepare(build)
        instrumented = build / 'control-attested'
        pins = pinned_files(instrumented, catalog)
        manifest = {'schema': 'puppybot.actor-pilot.v1', 'seed': SEED, 'horizon': HORIZON,
                    'files': pins, 'sceneCatalog': str(catalog), 'model': str(MODEL),
                    'originalControl': str(ORIGINAL), 'instrumentedControl': str(instrumented), 'cwd': str(ROOT),
                    'scope': 'single paired training-layout simulator diagnostic; actor cue uses simulator task state; OS-loaded runtime and hardware are not independently attested'}
        (OUTPUT / 'inputs.json').write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n')
        env = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'PUPPYBOT_PROJECT': str(ROOT),
               'LD_LIBRARY_PATH': str(ROOT / 'build/flex/rocm-runtime'), 'SDL_VIDEODRIVER': 'offscreen'}
        for name, binary in (('original', ORIGINAL), ('instrumented', instrumented)):
            require_space(PITCH, 8 * 1024**3)
            verify_pins(pins)
            parent = OUTPUT / name; parent.mkdir(); supervisor = parent / 'monitor'; supervisor.mkdir()
            argv = command(binary, catalog, parent / 'run')
            (parent / 'command.json').write_text(json.dumps(argv, indent=2) + '\n')
            status = monitor.supervise(argv, supervisor, env, WALL_SECONDS)
            if status['signal'] is not None or status['timedOut'] or status['clientExit'] != 0 or status['remainingWorkersTerminated']:
                raise RuntimeError(f'{name} failed or required cleanup; inspect {parent}')
            verify_pins(pins)
        package.verify(EXPERIMENT / 'control-s0', EXPERIMENT / 'treatment-s0', PACKAGE)
        auditor = ROOT / 'flex/tests/audit-attested-pair.py'
        completed = subprocess.run(['/usr/bin/python3', '-I', str(auditor), str(OUTPUT)],
                                   cwd=ROOT, check=True, text=True, capture_output=True, timeout=120)
        (OUTPUT / 'audit.json').write_text(completed.stdout)
        print(completed.stdout, end='')


if __name__ == '__main__':
    main()
