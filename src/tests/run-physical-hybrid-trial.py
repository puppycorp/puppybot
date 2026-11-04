#!/usr/bin/env python3
"""Run a supervised longer continuation of the visible-brick selection case.

Usage: python3 -I flex/tests/run-physical-hybrid-trial.py --check [--collector-ticks N]
       python3 -I flex/tests/run-physical-hybrid-trial.py [--collector-ticks N] NEW_OUTPUT_DIRECTORY

Run only with the GPU otherwise idle. Inputs must match the previous trial;
snapshots, logs, partial artifacts and a diagnostic trace audit are retained.
This is a simulator-only hybrid experiment, not a robot or delivery benchmark.
"""
import ctypes
import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
BASE = PROJECT / 'build/flex/sim/levels-v2/pitch82'
REFERENCE = BASE / 'physical-hybrid-visible-trial'
MODEL = BASE / 'more1-s0'
ENVIRONMENT = PROJECT / 'build/flex/sim/environments/apartment/apartment.bin'
ASSET = PROJECT / 'build/flex/sim/puppybot.bin'
SIMULATOR = Path('/tmp/puppybot-physical-bridge-sim')
CLIENT = Path('/tmp/puppybot-physical-client')
WORKER = PROJECT / 'flex/vision/discovery.py'
WALL_SECONDS = 300


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def source_hashes(root):
    return {str(path.relative_to(root)): sha(path)
            for path in sorted(root.rglob('*'))
            if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc'}


def check_candidate_build(simulator_hash, compiler):
    # Build only to /tmp: never replace the running experiment binary.
    with tempfile.TemporaryDirectory(prefix='puppy-candidate-build-') as directory:
        freshly_built = Path(directory) / 'simulator'
        subprocess.run([str(compiler), str(PROJECT / 'flex/sim/main.flex'),
                        '-o', str(freshly_built)], cwd=PROJECT, check=True, timeout=30)
        if sha(freshly_built) != simulator_hash:
            raise ValueError('candidate binary does not match the current simulator source')


def worker_snapshot(env):
    # Discovery runs python3 from PATH and imports these packages. Capture the
    # worker, interpreter, imported module files and mapped native libraries;
    # lazy-loaded libraries and scheduling remain outside this snapshot.
    launch = shutil.which('python3', path=env.get('PATH'))
    if not launch:
        raise ValueError('mapping worker python3 is not available on PATH')
    launch = Path(launch).absolute()
    executable = launch.resolve()
    probe = r'''import argparse,json,math,sys
from pathlib import Path
sys.path[0] = str(Path.cwd() / 'flex/vision')
import cv2,numpy
files = {str(Path(sys.executable).resolve())}
for module in list(sys.modules.values()):
    value = getattr(module, '__file__', None)
    if value:
        path = Path(value)
        if path.is_file(): files.add(str(path.resolve()))
for line in Path('/proc/self/maps').read_text().splitlines():
    fields = line.split(maxsplit=5)
    if len(fields) == 6 and fields[5].startswith('/'):
        path = Path(fields[5])
        if path.is_file(): files.add(str(path.resolve()))
print(json.dumps({'executable': str(Path(sys.executable).resolve()), 'python': sys.version,
                  'cv2': cv2.__version__, 'numpy': numpy.__version__, 'files': sorted(files)}))'''
    completed = subprocess.run([str(launch), '-c', probe], cwd=PROJECT, env=env,
                               capture_output=True, text=True, timeout=30, check=True)
    details = json.loads(completed.stdout)
    if Path(details['executable']) != executable:
        raise ValueError('mapping worker interpreter probe resolved differently')
    details['launchPath'] = str(launch)
    paths = {Path(value) for value in details.pop('files')}
    paths.update((executable, WORKER.resolve()))
    details['files'] = {str(path): sha(path) for path in sorted(paths)}
    details['scope'] = 'probe-time imported modules and mapped files; later lazy loads and scheduling are not pinned'
    return details


def verify_worker(snapshot):
    for name, digest in snapshot['files'].items():
        if sha(Path(name)) != digest:
            raise RuntimeError(f'mapping worker runtime input changed: {name}')


def children(parent):
    # Only follow the supervisor's own descendants, including children adopted
    # via PR_SET_CHILD_SUBREAPER. Never match or kill by command name.
    result = []
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            text = (entry / 'stat').read_text()
            fields = text[text.rfind(')') + 2:].split()
            if int(fields[1]) == parent:
                result.append((int(entry.name), fields[0]))
        except (FileNotFoundError, ProcessLookupError, PermissionError, IndexError, ValueError):
            continue
    return result


def cleanup_descendants():
    # Mapping workers can create their own process groups. Reparenting them to
    # this supervisor permits cleanup even after their original parent exits.
    found = False
    for sig, duration in ((signal.SIGTERM, 2), (signal.SIGKILL, 3)):
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            pending, visited = [os.getpid()], set()
            while pending:
                parent = pending.pop()
                for pid, state in children(parent):
                    if pid in visited:
                        continue
                    visited.add(pid)
                    pending.append(pid)
                    if state == 'Z':
                        continue
                    found = True
                    try:
                        # pidfds avoid sending a signal to a recycled PID.
                        fd = os.pidfd_open(pid)
                        try:
                            signal.pidfd_send_signal(fd, sig)
                        finally:
                            os.close(fd)
                    except ProcessLookupError:
                        pass
            while True:
                try:
                    pid, _ = os.waitpid(-1, os.WNOHANG)
                    if not pid:
                        break
                except ChildProcessError:
                    break
            if not children(os.getpid()):
                break
            time.sleep(.05)
    if children(os.getpid()):
        raise RuntimeError('could not reap every trial descendant')
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--collector-ticks', type=int, default=4000)
    parser.add_argument('--candidate-simulator', type=Path,
                        help='separately compiled opt-in candidate; compare to retained 29980-tick baseline')
    parser.add_argument('output', nargs='?')
    args = parser.parse_args()
    if args.collector_ticks < 20 or args.collector_ticks > 29980 or args.collector_ticks % 20:
        parser.error('collector ticks must be a multiple of 20 in 20..29980')
    if args.check == bool(args.output):
        parser.error('choose --check or one new output directory')
    poll_limit = args.collector_ticks // 20
    reference = json.loads((REFERENCE / 'run/inputs.json').read_text())
    simulator = args.candidate_simulator.resolve() if args.candidate_simulator else SIMULATOR
    expected = {
        'caseSHA256': REFERENCE / 'case.json',
        'environmentSHA256': ENVIRONMENT, 'weightsSHA256': MODEL / 'weights.bin',
        'policySHA256': MODEL / 'policy', 'receiptSHA256': MODEL / 'receipt.json',
        'robotAssetSHA256': ASSET,
    }
    for key, path in expected.items():
        if sha(path) != reference[key]:
            raise ValueError(f'{key} differs from the preceding visible-brick run')
    if not os.access(simulator, os.X_OK):
        raise ValueError(f'missing executable simulator: {simulator}')
    simulator_hash = sha(simulator)
    compiler = PROJECT / 'build/flex/control/compiler'
    compiler_hash = None
    if not args.candidate_simulator and simulator_hash != reference['simulatorSHA256']:
        raise ValueError('baseline simulator differs from the preceding visible-brick run')
    if args.candidate_simulator:
        if args.collector_ticks != 29980:
            raise ValueError('candidate comparison requires the same 29980-tick baseline limit')
        if simulator_hash == reference['simulatorSHA256']:
            raise ValueError('candidate simulator is identical to the baseline')
        compiler_hash = sha(compiler)
        check_candidate_build(simulator_hash, compiler)
    if not os.access(CLIENT, os.X_OK):
        raise ValueError(f'missing executable client: {CLIENT}')
    previous = BASE / 'physical-hybrid-visible-4000/supervisor-inputs.json'
    if args.collector_ticks >= 16000:
        if not previous.is_file() or sha(CLIENT) != json.loads(previous.read_text())['clientSHA256']:
            raise ValueError('longer runs require the same client as the 4,000-tick run')
    receipt = json.loads((MODEL / 'receipt.json').read_text())
    kernels = receipt.get('kernels')
    if not isinstance(kernels, dict) or len(kernels) < 5:
        raise ValueError('source policy kernel receipt is incomplete')
    for name, digest in kernels.items():
        if Path(name).name != name or sha(MODEL / 'kernels' / name) != digest:
            raise ValueError(f'source policy kernel mismatch: {name}')
    env = os.environ.copy()
    env.pop('DISPLAY', None)
    env.pop('WAYLAND_DISPLAY', None)
    env.update(SDL_VIDEODRIVER='offscreen', LD_LIBRARY_PATH=str(PROJECT / 'build/flex/rocm-runtime'),
               PUPPYBOT_PHYSICAL_NAV_LIMIT='30', PUPPYBOT_PHYSICAL_POLL_LIMIT=str(poll_limit))
    worker = worker_snapshot(env)
    prior_worker = BASE / 'physical-hybrid-visible-29980/worker-inputs.json'
    if args.candidate_simulator:
        if not prior_worker.is_file():
            raise ValueError('29980-tick baseline worker manifest is missing')
        old_worker = json.loads(prior_worker.read_text())
        for key in ('executable', 'launchPath', 'python', 'cv2', 'numpy', 'files'):
            if worker.get(key) != old_worker.get(key):
                raise ValueError(f'candidate worker/runtime differs from baseline: {key}')
    if args.check:
        print(json.dumps({'status': 'ready', 'clientSHA256': sha(CLIENT),
                          'simulatorSHA256': simulator_hash, 'compilerSHA256': compiler_hash,
                          'baselineSimulatorSHA256': reference['simulatorSHA256'],
                          'caseSHA256': reference['caseSHA256'],
                          'environmentSHA256': reference['environmentSHA256'],
                          'weightsSHA256': reference['weightsSHA256'],
                          'workerScriptSHA256': worker['files'][str(WORKER.resolve())],
                          'workerPython': worker['executable'], 'workerRuntimeFiles': len(worker['files']),
                          'collectorTickLimit': args.collector_ticks, 'wallSeconds': WALL_SECONDS,
                          'note': 'preflight only; no GPU process started'}, indent=2))
        return
    output = Path(args.output).resolve()

    output.mkdir(parents=False, exist_ok=False)
    inputs = output / 'inputs'
    inputs.mkdir()
    for source, name in ((simulator, 'simulator'), (CLIENT, 'client'),
                         (REFERENCE / 'case.json', 'case.json'), (ENVIRONMENT, 'environment.bin')):
        shutil.copy2(source, inputs / name)
        if sha(inputs / name) != sha(source):
            raise ValueError(f'copy changed: {source}')
    shutil.copytree(MODEL, inputs / 'model')
    for key, name in (('caseSHA256', 'case.json'),
                      ('environmentSHA256', 'environment.bin'), ('weightsSHA256', 'model/weights.bin'),
                      ('policySHA256', 'model/policy'), ('receiptSHA256', 'model/receipt.json')):
        if sha(inputs / name) != reference[key]:
            raise ValueError(f'snapshot differs from reference: {name}')
    if sha(inputs / 'simulator') != simulator_hash:
        raise ValueError('simulator snapshot changed')
    for name, digest in kernels.items():
        if sha(inputs / 'model/kernels' / name) != digest:
            raise ValueError(f'snapshotted kernel mismatch: {name}')
    if args.candidate_simulator:
        # Source archive is for review; the frozen executable is what runs.
        shutil.copytree(PROJECT / 'flex', inputs / 'flex-source',
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        sources = source_hashes(inputs / 'flex-source')
        if sources != source_hashes(PROJECT / 'flex'):
            raise ValueError('source changed while snapshotting')
        if sha(compiler) != compiler_hash:
            raise ValueError('compiler changed while snapshotting')
        check_candidate_build(simulator_hash, compiler)
        if sources != source_hashes(PROJECT / 'flex') or sha(compiler) != compiler_hash:
            raise ValueError('source or compiler changed during candidate rebuild')
        (output / 'source-inputs.json').write_text(json.dumps(sources, indent=2) + '\n')
    manifest = {'referenceInputs': reference, 'candidateSimulatorSHA256': sha(inputs / 'simulator'),
                'candidateMode': bool(args.candidate_simulator), 'compilerSHA256': compiler_hash,
                'clientSHA256': sha(inputs / 'client'),
                'navigationActionLimit': 30, 'collectorPollLimit': poll_limit,
                'collectorTickLimit': args.collector_ticks, 'wallSeconds': WALL_SECONDS,
                'robotAssetScope': 'current shared asset checked before and after; not snapshotted'}
    (output / 'supervisor-inputs.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (output / 'worker-inputs.json').write_text(json.dumps(worker, indent=2) + '\n')
    shutil.copy2(WORKER, inputs / 'discovery.py')
    if sha(inputs / 'discovery.py') != worker['files'][str(WORKER.resolve())]:
        raise ValueError('mapping worker copy differs from the preflight')

    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        raise OSError(ctypes.get_errno(), 'cannot supervise orphaned workers')
    command = [str(inputs / 'client'), str(inputs / 'simulator'), str(inputs / 'model'),
               str(inputs / 'case.json'), str(inputs / 'environment.bin'), str(output / 'run'),
               '--allow-zero-contact']
    def interrupted(signum, _frame):
        raise InterruptedError(f'supervisor received signal {signum}')
    signal.signal(signal.SIGTERM, interrupted)
    start = time.monotonic()
    status = {'clientExit': None, 'timedOut': False, 'remainingWorkersTerminated': False}
    with (output / 'client.log').open('w') as log:
        process = subprocess.Popen(command, cwd=PROJECT, env=env, stdout=log,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        status['processGroup'] = process.pid
        try:
            try:
                status['clientExit'] = process.wait(timeout=WALL_SECONDS)
            except subprocess.TimeoutExpired:
                status['timedOut'] = True
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
        finally:
            # p.wait() reaps the direct child when possible; cleanup catches
            # its adopted workers, including independent worker process groups.
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            status['remainingWorkersTerminated'] = cleanup_descendants()
            status['wallSeconds'] = round(time.monotonic() - start, 3)
            (output / 'supervisor-result.json').write_text(json.dumps(status, indent=2) + '\n')

    if status['timedOut'] or status['clientExit'] != 0 or status['remainingWorkersTerminated']:
        raise RuntimeError(f'trial did not complete cleanly; inspect {output}')
    if sha(ASSET) != reference['robotAssetSHA256']:
        raise RuntimeError('shared robot asset changed during the run')
    if args.candidate_simulator and source_hashes(inputs / 'flex-source') != sources:
        raise RuntimeError('archived source changed during the run')
    launch = shutil.which('python3', path=env.get('PATH'))
    if not launch or Path(launch).absolute() != Path(worker['launchPath']) or Path(launch).resolve() != Path(worker['executable']):
        raise RuntimeError('mapping worker python3 path changed during the run')
    verify_worker(worker)
    result = json.loads((output / 'run/result.json').read_text())
    run_inputs = json.loads((output / 'run/inputs.json').read_text())
    for key, expected_sha in reference.items():
        if key == 'simulatorSHA256' and args.candidate_simulator:
            expected_sha = manifest['candidateSimulatorSHA256']
        if key.endswith('SHA256') and run_inputs.get(key) != expected_sha:
            raise RuntimeError(f'run provenance mismatch: {key}')
    if result.get('traceSHA256') != sha(output / 'run/trace.jsonl'):
        raise RuntimeError('trace hash mismatch')
    audit_source = (inputs / 'flex-source' if args.candidate_simulator else PROJECT / 'flex')
    audit = subprocess.run([sys.executable, '-I', str(audit_source / 'exploration/manipulation_audit.py'),
                            str(inputs / 'case.json'), str(output / 'run/trace.jsonl')],
                           cwd=PROJECT, capture_output=True, text=True, timeout=60)
    (output / 'audit.log').write_text(audit.stderr)
    if audit.returncode:
        raise RuntimeError('trace audit failed; inspect retained audit.log')
    if args.candidate_simulator and source_hashes(inputs / 'flex-source') != sources:
        raise RuntimeError('archived source changed during the audit')
    report = json.loads(audit.stdout)
    if report['caseSHA256'] != reference['caseSHA256']:
        raise RuntimeError('audit case hash mismatch')
    (output / 'manipulation-audit.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'supervisor': status, 'result': result, 'audit': report}, indent=2))


if __name__ == '__main__':
    main()
