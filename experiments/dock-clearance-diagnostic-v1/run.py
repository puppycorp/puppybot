#!/usr/bin/env python3
"""Three-arm elevated-survey diagnostic; launch through the resource monitor."""
import fcntl
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


base = load('survey_trial_base', ROOT / 'experiments/physical-search-fallback-trial-v1/run.py')
builder = load('elevation_trial_builder', HERE / 'build.py')
base.__file__ = str(HERE / 'run.py')
original_required = base.required
ARMS = base.ARMS
sha = base.sha
hidden = base.hidden


def check_build(build):
    return builder.verify(build)


def env_for(root, name):
    env = dict(PATH='/usr/bin:/bin', HOME=str(Path.home()), SDL_VIDEODRIVER='offscreen',
               LD_LIBRARY_PATH=str(ROOT / 'build/flex/rocm-runtime'),
               PUPPYBOT_PHYSICAL_NAV_LIMIT='90', PUPPYBOT_PHYSICAL_POLL_LIMIT='1499',
               PUPPYBOT_PHYSICAL_SEARCH_FALLBACK='1', PUPPYBOT_DOCK_CONFIRM='1',
               PUPPYBOT_DOCK_HIGH_SURVEY='1' if name == 'candidate-search' else '0')
    env['PUPPYBOT_DOCK_DIAG_DIRECTORY'] = str(Path(root) / name / 'diagnostic')
    return env


def required(root, build):
    return original_required(root, build) + [Path(__file__), HERE / 'audit.py', HERE / 'monitor.py',
        Path(builder.__file__), builder.TRANSFORM,
        ROOT / 'experiments/dock-survey-trial-v1/run.py',
        ROOT / 'experiments/dock-survey-trial-v1/audit.py',
        ROOT / 'experiments/dock-survey-elevation-trial-v1/build.py',
        ROOT / 'experiments/dock-survey-elevation-trial-v1/audit.py', HERE / 'transform.py',
        ROOT / 'experiments/dock-survey-diagnostic-v1/build.py',
        ROOT / 'experiments/dock-survey-diagnostic-v1/transform.py',
        ROOT / 'experiments/physical-dock-confirm-trial-v1/audit.py',
        ROOT / 'experiments/physical-dock-confirm-trial-v1/run.py',
        ROOT / 'experiments/physical-search-fallback-trial-v1/run.py',
        ROOT / 'experiments/physical-search-fallback-trial-v1/audit.py']


base.check_build = check_build
base.required = required
# The underlying manifest verifier uses this only to locate python3.
base.env_for = lambda flag: env_for('/unused', 'baseline')
check_manifest = base.check_manifest


def check_invocation(root, manifest, name):
    parent = Path(root) / name
    if (json.loads((parent / 'command.json').read_text()) != base.command_for(root, manifest, name) or
            json.loads((parent / 'environment.json').read_text()) != env_for(root, name)):
        raise ValueError('arm invocation differs')


def launch(output, build, case, environment, model):
    output, build, case, environment, model = (Path(p).absolute() for p in (output, build, case, environment, model))
    if os.environ.get('PUPPYBOT_SEARCH_TRIAL_REVIEWED_WORKER') != '1': raise RuntimeError('external monitor required')
    base.load('survey_guard', ROOT / 'experiments/sim-stop-supervisor/supervisor.py').require_dedicated_process()
    with base.LOCK.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if output.exists() or output.is_symlink(): raise ValueError('output exists; preserve it')
        if shutil.disk_usage(output.parent).free < 36 * 1024**3: raise ValueError('insufficient disk')
        check_build(build); hidden.rescan.verify_model(model)
        reference = base.REFERENCE / 'inputs'
        for supplied, expected in ((case, reference / 'case.json'), (environment, reference / 'environment.bin')):
            if sha(supplied) != sha(expected): raise ValueError('selection scene differs')
        for name in ('policy', 'weights.bin', 'receipt.json'):
            if sha(model / name) != sha(reference / 'model' / name): raise ValueError('selection model differs')
        output.mkdir(); inputs = output / 'inputs'; inputs.mkdir()
        try:
            shutil.copyfile(case, inputs / 'case.json'); shutil.copyfile(environment, inputs / 'environment.bin')
            shutil.copytree(model, inputs / 'model')
            if sha(case) != sha(inputs / 'case.json') or sha(environment) != sha(inputs / 'environment.bin'):
                raise ValueError('scene changed during copy')
            worker = hidden.supervisor.worker_snapshot(env_for(output, 'baseline'))
            (output / 'worker-inputs.json').write_text(json.dumps(worker, sort_keys=True, indent=2) + '\n')
            manifest = {'schema': 'puppybot.physical-search-fallback-trial.v1', 'build': str(build),
                        'case': str(inputs / 'case.json'), 'environment': str(inputs / 'environment.bin'),
                        'model': str(inputs / 'model'), 'navigationLimit': 90, 'collectorPollLimit': 1499,
                        'wallSecondsPerArm': 300, 'files': base.pins(output, build),
                        'scope': 'simulator selection diagnostic only'}
            (output / 'inputs.json').write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n')
            check_manifest(output, manifest)
            for name in ARMS:
                if shutil.disk_usage(output).free < 34 * 1024**3: raise ValueError('insufficient disk during trial')
                check_manifest(output, manifest); parent = output / name; parent.mkdir()
                arm_monitor = parent / 'monitor'; arm_monitor.mkdir()
                (parent / 'diagnostic').mkdir()
                argv = base.command_for(output, manifest, name); env = env_for(output, name)
                (parent / 'command.json').write_text(json.dumps(argv, indent=2) + '\n')
                (parent / 'environment.json').write_text(json.dumps(env, sort_keys=True, indent=2) + '\n')
                status = hidden.supervise(argv, arm_monitor, env, 300)
                if not base.clean_status(status): raise RuntimeError('arm failed; evidence censored')
                check_manifest(output, manifest)
            result = subprocess.run([sys.executable, '-I', str(HERE / 'audit.py'), str(output)],
                                    cwd=ROOT, capture_output=True, text=True, timeout=300)
            (output / 'audit.log').write_text(result.stderr)
            if result.returncode: raise RuntimeError('audit failed')
            check_manifest(output, manifest); (output / 'audit.json').write_text(result.stdout)
        except Exception:
            base.partial_audit(output); raise


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and resource scheduling.')
