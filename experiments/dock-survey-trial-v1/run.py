#!/usr/bin/env python3
"""Three-arm rendered survey diagnostic; launch through the resource monitor."""
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
builder = load('survey_trial_builder', ROOT / 'experiments/dock-survey-diagnostic-v1/build.py')
base.__file__ = str(HERE / 'run.py')
original_required = base.required
ARMS = base.ARMS
sha = base.sha
hidden = base.hidden


def check_build(build):
    build = Path(build); report = json.loads((build / 'build.json').read_text())
    archive = builder.ARCHIVE; original = builder.dock.check_build(archive)
    if (report.get('schema') != 'puppybot.dock-survey-diagnostic-build.v1' or
            report.get('archiveReportSHA256') != sha(archive / 'build.json') or
            report.get('transformSHA256') != sha(builder.HERE / 'transform.py') or
            report.get('compilerSHA256') != original['compilerSHA256'] or
            sha(builder.COMPILER) != report['compilerSHA256']):
        raise ValueError('survey build provenance differs')
    source = build / 'source'; library = build / 'build/flex/sim/library'
    current = base.prepare.hashes(source); libhash = base.prepare.hashes(library)
    if current != report['source'] or libhash != report['library']:
        raise ValueError('survey source or library changed')
    names = ('main.flex', 'dock-vision.flex', 'dock-search.flex', 'navigation.flex')
    archived = [archive / 'source/sim' / name for name in names]
    changed = dict(zip(('sim/' + name for name in names),
                       builder.transform.transform(*(path.read_text() for path in archived))))
    if set(current) != set(original['source']): raise ValueError('source inventory differs')
    for name, digest in original['source'].items():
        if name in changed:
            if (source / name).read_text() != changed[name]: raise ValueError('transform differs')
        elif current[name] != digest: raise ValueError('unrelated source changed')
    for name, digest in original['library'].items():
        if name == 'lib/f64.flex':
            old = f'import "{archive / "source/core/words.flex"}";'
            new = f'import "{source / "core/words.flex"}";'
            expected = builder.transform.once((archive / 'build/flex/sim/library' / name).read_text(), old, new)
            if (library / name).read_text() != expected: raise ValueError('library adapter differs')
        elif libhash.get(name) != digest: raise ValueError('unrelated library changed')
    if set(libhash) != set(original['library']): raise ValueError('library inventory differs')
    dependencies = f'import "{library / "libs/render.flex"}";\nimport "{library / "libs/physics/physics.flex"}";\n'
    if (library.parent / 'dependencies.flex').read_text() != dependencies: raise ValueError('dependencies differ')
    for name in ('client', 'simulator'):
        expected = report[name + 'SHA256']
        if (sha(build / name) != expected or sha(build / ('baseline-' + name)) != expected or
                not os.access(build / name, os.X_OK) or not os.access(build / ('baseline-' + name), os.X_OK)):
            raise ValueError('binary changed or same-binary comparison lost')
    if report['clientSHA256'] != original['clientSHA256']: raise ValueError('client differs')
    return report


def env_for(root, name):
    env = dict(PATH='/usr/bin:/bin', HOME=str(Path.home()), SDL_VIDEODRIVER='offscreen',
               LD_LIBRARY_PATH=str(ROOT / 'build/flex/rocm-runtime'),
               PUPPYBOT_PHYSICAL_NAV_LIMIT='90', PUPPYBOT_PHYSICAL_POLL_LIMIT='1499',
               PUPPYBOT_PHYSICAL_SEARCH_FALLBACK='1', PUPPYBOT_DOCK_CONFIRM='1')
    if name == 'candidate-search':
        env['PUPPYBOT_DOCK_DIAG_DIRECTORY'] = str(Path(root) / name / 'diagnostic')
    return env


def required(root, build):
    return original_required(root, build) + [Path(__file__), HERE / 'audit.py', HERE / 'monitor.py',
        Path(builder.__file__), builder.HERE / 'transform.py',
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
                if name == 'candidate-search': (parent / 'diagnostic').mkdir()
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
