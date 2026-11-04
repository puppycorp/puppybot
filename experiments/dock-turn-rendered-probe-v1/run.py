#!/usr/bin/env python3
"""Two-arm 10-tick dropout pilot, usable only under the dedicated outer monitor."""
import fcntl
import contextlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
LOCK = P / '.l4-matched.lock'
ARMS = ('control-10', 'candidate-10')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


builder = load('turn_rendered_build', HERE / 'build.py')
auditor = load('turn_rendered_audit', HERE / 'audit.py')
base = load('turn_existing_runner', ROOT / 'experiments/physical-search-fallback-trial-v1/run.py')
hidden = base.hidden
sha = builder.sha


def env_for():
    return {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'SDL_VIDEODRIVER': 'offscreen',
            'LD_LIBRARY_PATH': str(ROOT / 'build/flex/rocm-runtime'),
            'PUPPYBOT_PHYSICAL_NAV_LIMIT': '30', 'PUPPYBOT_PHYSICAL_POLL_LIMIT': '1499'}


def command_for(root, manifest, name):
    if name not in ARMS:
        raise ValueError('unexpected pilot arm')
    return [manifest['client'], str(Path(manifest['build']) / name / 'simulator'), manifest['model'],
            manifest['case'], manifest['environment'], str(Path(root) / name / 'run'), '--allow-zero-contact']


def required(root, build):
    root, build = Path(root), Path(build)
    paths = [HERE / 'run.py', HERE / 'audit.py', HERE / 'monitor.py', HERE / 'guardian.py', HERE / 'build.py', HERE / 'transform.py',
             ROOT / 'experiments/dock-turn-reacquire-current-v1/baseline-case.flex',
             ROOT / 'experiments/dock-turn-reacquire-current-v1/transform.py',
             ROOT / 'experiments/dock-turn-reacquire-v1/transform.py',
             ROOT / 'experiments/physical-search-fallback-trial-v1/run.py',
             ROOT / 'experiments/physical-search-fallback-monitor-v1/monitor.py',
             ROOT / 'experiments/sim-stop-supervisor/supervisor.py',
             ROOT / 'experiments/sim-stop-supervisor/proxy.py',
             ROOT / 'flex/tests/run-physical-hidden-trial.py', ROOT / 'flex/tests/run-physical-rescan-trial.py',
             ROOT / 'flex/tests/run-physical-hybrid-trial.py', ROOT / 'flex/tests/monitored-visual-v4-smoke.py',
             ROOT / 'flex/exploration/manipulation_audit.py', ROOT / 'flex/tests/sim-cases.py',
             ROOT / 'flex/tests/sim.py', Path(sys.executable).resolve(), ROOT / 'puppybot.json',
             *builder.INPUTS.values(), root / 'worker-inputs.json', root / 'inputs/case.json',
             root / 'inputs/environment.bin']
    for folder in (build, root / 'inputs/model', ROOT / 'build/flex/rocm-runtime'):
        paths.extend(p for p in folder.rglob('*') if p.is_file() and p.suffix != '.pyc' and '__pycache__' not in p.parts)
    return sorted(set(paths))


def pins(root, build):
    return {str(path): sha(path) for path in required(root, build)}


def require_guardian():
    try:
        pid = int(os.environ['PUPPY_TURN_GUARD_PID']); fd = int(os.environ['PUPPY_TURN_GUARD_FD'])
        if pid <= 1 or fd < 0:
            raise ValueError('invalid guardian identity')
        guardian_lock = os.stat(f'/proc/{pid}/fd/{fd}'); own_lock = os.stat(LOCK)
        if (guardian_lock.st_dev, guardian_lock.st_ino) != (own_lock.st_dev, own_lock.st_ino):
            raise ValueError('guardian lock identity differs')
        with LOCK.open('a') as probe:
            try:
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            fcntl.flock(probe, fcntl.LOCK_UN)
            raise ValueError('guardian lock is not held')
    except (KeyError, OSError, ValueError) as error:
        raise RuntimeError('live lock-holding guardian required') from error


@contextlib.contextmanager
def guarded():
    require_guardian()
    try: yield
    finally: require_guardian()


def check_manifest(root, manifest):
    require_guardian()
    root = Path(root).absolute(); build = Path(manifest['build'])
    if (not build.is_absolute() or manifest.get('case') != str(root / 'inputs/case.json') or
            manifest.get('environment') != str(root / 'inputs/environment.bin') or
            manifest.get('model') != str(root / 'inputs/model') or
            manifest.get('client') != str(builder.INPUTS['client']) or
            manifest.get('arms') != list(ARMS) or manifest.get('wallSecondsPerArm') != 300 or
            manifest.get('navigationLimit') != 30 or manifest.get('collectorPollLimit') != 1499):
        raise ValueError('pilot paths or limits differ')
    builder.verify(build)
    if pins(root, build) != manifest['files']:
        raise ValueError('pilot inputs changed')
    for key, target in (('case', root / 'inputs/case.json'), ('environment', root / 'inputs/environment.bin'),
                        ('model', root / 'inputs/model/weights.bin'), ('policy', root / 'inputs/model/policy'),
                        ('receipt', root / 'inputs/model/receipt.json')):
        if sha(target) != sha(builder.INPUTS[key]):
            raise ValueError('reference snapshot differs: ' + key)
    hidden.rescan.verify_model(root / 'inputs/model')
    worker = json.loads((root / 'worker-inputs.json').read_text())
    hidden.supervisor.verify_worker(worker)
    launch = shutil.which('python3', path=env_for()['PATH'])
    if not launch or Path(launch).absolute() != Path(worker['launchPath']) or Path(launch).resolve() != Path(worker['executable']):
        raise ValueError('worker interpreter differs')


def check_invocation(root, manifest, name):
    arm = Path(root) / name
    if (json.loads((arm / 'command.json').read_text()) != command_for(root, manifest, name) or
            json.loads((arm / 'environment.json').read_text()) != env_for()):
        raise ValueError('arm invocation differs')


def check_run_inputs(arm, manifest, name):
    observed = json.loads((arm / 'run/inputs.json').read_text())
    expected = json.loads(builder.INPUTS['supervisor'].read_text())['referenceInputs']
    expected = dict(expected, simulatorSHA256=sha(Path(manifest['build']) / name / 'simulator'))
    if observed != expected:
        raise ValueError('recorded simulator input identity differs')


def launch(output, build, case, environment, model):
    if os.environ.get('PUPPYBOT_SEARCH_TRIAL_REVIEWED_WORKER') != '1':
        raise RuntimeError('dedicated resource monitor required')
    base.load('turn_runner_guard', ROOT / 'experiments/sim-stop-supervisor/supervisor.py').require_dedicated_process()
    output, build, case, environment, model = (Path(p).absolute() for p in (output, build, case, environment, model))
    with guarded():
        if output.exists() or output.is_symlink():
            raise FileExistsError('output exists; preserve evidence')
        if shutil.disk_usage(output.parent).free < 38 * 1024**3:
            raise ValueError('insufficient disk before trial')
        builder.verify(build, recompile=True); hidden.rescan.verify_model(model)
        for key, supplied in (('case', case), ('environment', environment), ('model', model / 'weights.bin'),
                              ('policy', model / 'policy'), ('receipt', model / 'receipt.json')):
            if sha(supplied) != sha(builder.INPUTS[key]):
                raise ValueError('pilot selection input differs: ' + key)
        output.mkdir(); inputs = output / 'inputs'; inputs.mkdir()
        shutil.copyfile(case, inputs / 'case.json'); shutil.copyfile(environment, inputs / 'environment.bin')
        shutil.copytree(model, inputs / 'model')
        worker = hidden.supervisor.worker_snapshot(env_for())
        (output / 'worker-inputs.json').write_text(json.dumps(worker, sort_keys=True, indent=2) + '\n')
        manifest = {'schema': 'puppybot.dock-turn-rendered-pair.v1', 'build': str(build),
                    'case': str(inputs / 'case.json'), 'environment': str(inputs / 'environment.bin'),
                    'model': str(inputs / 'model'), 'client': str(builder.INPUTS['client']),
                    'arms': list(ARMS), 'navigationLimit': 30, 'collectorPollLimit': 1499,
                    'wallSecondsPerArm': 300, 'files': pins(output, build),
                    'scope': 'synthetic visual observation loss in one simulated selection case'}
        (output / 'inputs.json').write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n')
        check_manifest(output, manifest)
        for name in ARMS:
            if shutil.disk_usage(output).free < 34 * 1024**3:
                raise ValueError('insufficient disk during pilot')
            check_manifest(output, manifest)
            arm = output / name; arm.mkdir(); monitor = arm / 'monitor'; monitor.mkdir()
            command, env = command_for(output, manifest, name), env_for()
            (arm / 'command.json').write_text(json.dumps(command, indent=2) + '\n')
            (arm / 'environment.json').write_text(json.dumps(env, sort_keys=True, indent=2) + '\n')
            status = hidden.supervise(command, monitor, env, 300)
            if not base.clean_status(status) or json.loads((monitor / 'supervisor-result.json').read_text()) != status:
                raise RuntimeError('arm process failed; retained evidence censored')
            (arm / 'supervisor-result.json').write_text(json.dumps(status, sort_keys=True, indent=2) + '\n')
            check_manifest(output, manifest); check_invocation(output, manifest, name); check_run_inputs(arm, manifest, name)
            trace_audit = subprocess.run([sys.executable, '-I', str(ROOT / 'flex/exploration/manipulation_audit.py'),
                                          manifest['case'], str(arm / 'run/trace.jsonl')], cwd=ROOT,
                                         capture_output=True, text=True, timeout=60)
            (arm / 'manipulation-audit.log').write_text(trace_audit.stderr)
            if trace_audit.returncode:
                raise RuntimeError('manipulation audit failed; retained evidence censored')
            (arm / 'manipulation-audit.json').write_text(trace_audit.stdout)
        check_manifest(output, manifest)
        result = auditor.audit(output)
        (output / 'audit.json').write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
        check_manifest(output, manifest)
        return result


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and resource scheduling.')
