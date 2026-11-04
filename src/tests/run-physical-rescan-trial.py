#!/usr/bin/env python3
"""Supervise one rendered simulator-only guarded-rescan no-target trial.

Usage: python3 -I flex/tests/run-physical-rescan-trial.py --check
       python3 -I flex/tests/run-physical-rescan-trial.py NEW_OUTPUT_DIRECTORY

Requires an idle GPU for the actual run. This uses a selection case with the
brick placed behind the starting robot, one policy action, two stopped RGB
rechecks and a bounded external watchdog. It does not test physical motors.
"""
import argparse
import ctypes
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
BASE = PROJECT / 'build/flex/sim/levels-v2/pitch82'
REFERENCE = BASE / 'physical-hybrid-visible-trial'
ENVIRONMENT = PROJECT / 'build/flex/sim/environments/apartment/apartment.bin'
ASSET = PROJECT / 'build/flex/sim/puppybot.bin'
MODEL = BASE / 'more1-s0'
COMPILER = PROJECT / 'build/flex/control/compiler'
SUPERVISOR_PATH = PROJECT / 'flex/tests/run-physical-hybrid-trial.py'
WALL_SECONDS = 120

spec = importlib.util.spec_from_file_location('hybrid_supervisor', SUPERVISOR_PATH)
supervisor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(supervisor)
sha = supervisor.sha


def prepare_case():
    case = json.loads((REFERENCE / 'case.json').read_text())
    if len(case['objects']) != 1:
        raise ValueError('expected the one-brick selection case')
    case['id'] = 'physical-guarded-rescan-behind'
    case['objects'][0]['position'] = [-1.5, 0.15, 0.013]
    return json.dumps(case, indent=2) + '\n'


def verify_model(path):
    receipt = json.loads((path / 'receipt.json').read_text())
    for key, name in (('weightsSHA256', 'weights.bin'), ('binarySHA256', 'policy')):
        if sha(path / name) != receipt[key]:
            raise ValueError(f'model receipt mismatch: {name}')
    kernels = receipt.get('kernels')
    if not isinstance(kernels, dict) or len(kernels) < 5:
        raise ValueError('model kernel receipt is incomplete')
    for name, expected in kernels.items():
        if Path(name).name != name or sha(path / 'kernels' / name) != expected:
            raise ValueError(f'model kernel mismatch: {name}')


def build_snapshot(inputs):
    # Copy source first and compile only the copy. Verify the worktree did not
    # change during the copy; no current build artifact is replaced.
    source_hashes = supervisor.source_hashes(PROJECT / 'flex')
    shutil.copytree(PROJECT / 'flex', inputs / 'flex-source',
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    if source_hashes != supervisor.source_hashes(inputs / 'flex-source') or source_hashes != supervisor.source_hashes(PROJECT / 'flex'):
        raise ValueError('source changed while snapshotting')
    library = PROJECT / 'build/flex/sim/library'
    library_hashes = supervisor.source_hashes(library)
    build_sim = inputs / 'build/flex/sim'; build_sim.mkdir(parents=True)
    shutil.copytree(library, build_sim / 'library')
    if library_hashes != supervisor.source_hashes(build_sim / 'library') or library_hashes != supervisor.source_hashes(library):
        raise ValueError('simulator dependency library changed while snapshotting')
    # The generated f64 adapter also imports the worktree's core words by an
    # absolute path. Redirect only that import to the identical archived copy;
    # otherwise the compiler sees two copies of the same lowering registry.
    adapter = build_sim / 'library/lib/f64.flex'
    original_import = f'import "{PROJECT / "flex/core/words.flex"}";'
    content = adapter.read_text()
    if content.count(original_import) != 1:
        raise ValueError('unexpected generated f64 dependency import')
    adapter.write_text(content.replace(original_import, f'import "{inputs / "flex-source/core/words.flex"}";'))
    archived_library_hashes = supervisor.source_hashes(build_sim / 'library')
    # The simulator's normal generated import file uses absolute worktree
    # paths. Point this archived build at its own frozen dependency copy.
    (build_sim / 'dependencies.flex').write_text(
        f'import "{build_sim / "library/libs/render.flex"}";\n'
        f'import "{build_sim / "library/libs/physics/physics.flex"}";\n')
    compiler_hash = sha(COMPILER)
    for source, target in (('sim/main.flex', 'simulator'), ('control/physical-client.flex', 'client')):
        subprocess.run([str(COMPILER), str(inputs / 'flex-source' / source), '-o', str(inputs / target)],
                       cwd=PROJECT, check=True, timeout=60)
    if (sha(COMPILER) != compiler_hash or source_hashes != supervisor.source_hashes(inputs / 'flex-source')
            or archived_library_hashes != supervisor.source_hashes(build_sim / 'library')
            or library_hashes != supervisor.source_hashes(library)):
        raise ValueError('compiler or archived source/dependencies changed while building')
    return source_hashes, archived_library_hashes, compiler_hash


def verify_observations(result, journal):
    if not (result['policyActions'] == 1 and result['stoppedRescanEnabled'] and
            result['stoppedRescanAttempts'] == 2 and not result['stoppedRescanHandoff'] and
            result['stoppedRescanStopReason'] == 2 and result['stopCommandAcknowledged'] and
            not result['handoff'] and result['outcome'] == 'unverified'):
        raise ValueError('expected bounded no-target stop did not occur')
    if len(journal) != 6 or [r['ack'] for r in journal] != [0, 1, 2, 1, 2, 7]:
        raise ValueError('unexpected simulator acknowledgment sequence')
    if [r['sequence'] for r in journal] != list(range(1, 7)):
        raise ValueError('replayed or missing response sequence')
    if [journal[i + 1]['totalSteps'] - journal[i]['totalSteps'] for i in range(5)] != [10, 2, 1, 2, 0]:
        raise ValueError('unexpected simulator-tick progression')
    for row in journal[:5]:
        if (row['owner'] != 0 or not row['imageValid'] or row['rgbDetections'] != 0 or
                row['cameraFrame'] != row['totalSteps'] or not row['cameraDriving'] or not row['cameraStill'] or
                row['jointTicks'] != journal[0]['jointTicks']):
            raise ValueError('target seen or navigation camera/arm was stale')
    if any(r['driveCommand'] != [0, 0, 90] for r in journal[2:]):
        raise ValueError('recheck or final stop did not acknowledge zero drive')
    if journal[-1]['owner'] != 2 or journal[-1]['imageValid']:
        raise ValueError('final stop ownership/status invalid')


def run_trial(output):
    output.mkdir(parents=False, exist_ok=False)
    inputs = output / 'inputs'; inputs.mkdir()
    case_text = prepare_case(); (inputs / 'case.json').write_text(case_text)
    shutil.copy2(ENVIRONMENT, inputs / 'environment.bin')
    verify_model(MODEL); shutil.copytree(MODEL, inputs / 'model'); verify_model(inputs / 'model')
    sources, libraries, compiler_hash = build_snapshot(inputs)
    env = os.environ.copy(); env.pop('DISPLAY', None); env.pop('WAYLAND_DISPLAY', None)
    env.update(SDL_VIDEODRIVER='offscreen', LD_LIBRARY_PATH=str(PROJECT / 'build/flex/rocm-runtime'),
               PUPPYBOT_PHYSICAL_NAV_LIMIT='1', PUPPYBOT_PHYSICAL_POLL_LIMIT='1',
               PUPPYBOT_PHYSICAL_GUARDED_RESCAN='1')
    worker = supervisor.worker_snapshot(env)
    manifest = {'caseSHA256': sha(inputs / 'case.json'), 'environmentSHA256': sha(inputs / 'environment.bin'),
                'simulatorSHA256': sha(inputs / 'simulator'), 'clientSHA256': sha(inputs / 'client'),
                'modelSHA256': sha(inputs / 'model/weights.bin'), 'policySHA256': sha(inputs / 'model/policy'),
                'receiptSHA256': sha(inputs / 'model/receipt.json'), 'assetSHA256': sha(ASSET),
                'compilerSHA256': compiler_hash, 'navigationActionLimit': 1, 'collectorPollLimit': 1,
                'guardedRescan': True, 'wallSeconds': WALL_SECONDS,
                'scope': 'selection scene; shared asset and worker inputs verified before/after, not all host runtime'}
    (output / 'inputs.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (output / 'source-inputs.json').write_text(json.dumps(sources, indent=2) + '\n')
    (output / 'library-inputs.json').write_text(json.dumps(libraries, indent=2) + '\n')
    (output / 'worker-inputs.json').write_text(json.dumps(worker, indent=2) + '\n')
    if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), 'cannot supervise orphaned workers')
    def interrupted(signum, _frame):
        raise InterruptedError(f'supervisor received signal {signum}')
    signal.signal(signal.SIGTERM, interrupted)
    command = [str(inputs / 'client'), str(inputs / 'simulator'), str(inputs / 'model'),
               str(inputs / 'case.json'), str(inputs / 'environment.bin'), str(output / 'run'), '--allow-zero-contact']
    status = {'clientExit': None, 'timedOut': False, 'remainingWorkersTerminated': False}
    start = time.monotonic()
    with (output / 'client.log').open('w') as log:
        process = subprocess.Popen(command, cwd=PROJECT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        status['processGroup'] = process.pid
        try:
            try:
                status['clientExit'] = process.wait(timeout=WALL_SECONDS)
            except subprocess.TimeoutExpired:
                status['timedOut'] = True
                try: os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError: pass
                try: process.wait(timeout=2)
                except subprocess.TimeoutExpired: pass
        finally:
            if process.poll() is None:
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                process.wait()
            status['remainingWorkersTerminated'] = supervisor.cleanup_descendants()
            status['wallSeconds'] = round(time.monotonic() - start, 3)
            (output / 'supervisor-result.json').write_text(json.dumps(status, indent=2) + '\n')
    if status['timedOut'] or status['clientExit'] != 0 or status['remainingWorkersTerminated']:
        raise RuntimeError(f'trial failed or required cleanup; inspect {output}')
    if (sha(ASSET) != manifest['assetSHA256'] or supervisor.source_hashes(inputs / 'flex-source') != sources
            or supervisor.source_hashes(inputs / 'build/flex/sim/library') != libraries):
        raise RuntimeError('shared asset or archived source changed')
    supervisor.verify_worker(worker)
    result = json.loads((output / 'run/result.json').read_text())
    observed_inputs = json.loads((output / 'run/inputs.json').read_text())
    for key in ('caseSHA256', 'environmentSHA256', 'simulatorSHA256', 'policySHA256', 'receiptSHA256'):
        if observed_inputs[key] != manifest[key]:
            raise RuntimeError(f'client input mismatch: {key}')
    if observed_inputs['weightsSHA256'] != manifest['modelSHA256'] or not observed_inputs['stoppedRescanEnabled']:
        raise RuntimeError('model or opt-in mismatch')
    if result['traceSHA256'] != sha(output / 'run/trace.jsonl'):
        raise RuntimeError('trace checksum mismatch')
    journal = [json.loads(line) for line in (output / 'run/physical-agent.jsonl').read_text().splitlines()]
    verify_observations(result, journal)
    report = {'status': 'passed', 'result': result, 'acknowledgments': [r['ack'] for r in journal],
              'scope': 'one rendered simulator selection case; no physical motor stop or search recovery proven'}
    (output / 'audit.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true'); parser.add_argument('output', nargs='?')
    args = parser.parse_args()
    if args.check == bool(args.output):
        parser.error('choose --check or one new output directory')
    verify_model(MODEL)
    if args.check:
        with tempfile.TemporaryDirectory(prefix='puppy-rescan-build-') as tmp:
            inputs = Path(tmp); sources, libraries, compiler_hash = build_snapshot(inputs)
            print(json.dumps({'status': 'ready', 'simulatorSHA256': sha(inputs / 'simulator'),
                'clientSHA256': sha(inputs / 'client'), 'compilerSHA256': compiler_hash,
                'sourceFiles': len(sources), 'libraryFiles': len(libraries), 'wallSeconds': WALL_SECONDS,
                'note': 'preflight only; no GPU run started'}, indent=2))
        return
    run_trial(Path(args.output).resolve())


if __name__ == '__main__':
    main()
