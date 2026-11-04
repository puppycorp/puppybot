#!/usr/bin/env python3
"""Prepare and run one bounded paired simulated visual-stop diagnostic.

Usage: run-sim-visual-stop-pair.py NEW_DIRECTORY
Run only after independent review and while the GPU is otherwise idle. A
completed run is not held-out qualification or physical hardware evidence.
"""
import fcntl
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / 'build/flex/sim/levels-v2/pitch82/.l4-matched.lock'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


hidden = module('physical_hidden', ROOT / 'flex/tests/run-physical-hidden-trial.py')
builder = module('visual_builder', ROOT / 'flex/tests/prepare-sim-visual-stop.py')
rescan = hidden.rescan
sha = rescan.sha


def pinned_files(inputs, output):
    paths = [inputs / 'visual-build/client', inputs / 'simulator', inputs / 'case.json', inputs / 'environment.bin',
             ROOT / 'build/flex/sim/puppybot.bin', ROOT / 'puppybot.json', ROOT / 'build/flex/control/compiler',
             ROOT / 'build/flex/rocm-runtime/libamdhip64.so', Path(__file__),
             ROOT / 'flex/tests/prepare-sim-visual-stop.py', ROOT / 'flex/tests/audit-sim-visual-stop.py',
             ROOT / 'flex/tests/audit-sim-visual-stop-pair.py', ROOT / 'flex/tests/run-physical-hidden-trial.py',
             ROOT / 'flex/tests/run-physical-rescan-trial.py', ROOT / 'flex/tests/run-physical-hybrid-trial.py',
             output / 'worker-inputs.json', inputs / 'visual-build/build.json', inputs / 'model/receipt.json', inputs / 'model/weights.bin', inputs / 'model/policy']
    paths += sorted((inputs / 'model/kernels').iterdir())
    paths += [p for folder in (inputs / 'flex-source', inputs / 'visual-build/flex', inputs / 'build/flex/sim/library')
              for p in sorted(folder.rglob('*')) if p.is_file()]
    return {str(path): sha(path) for path in paths}


def run(output):
    output = Path(output).absolute()
    with LOCK.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if shutil.disk_usage(output.parent).free < 12 * 1024**3: raise ValueError('insufficient free space before preparation')
        output.mkdir(parents=False, exist_ok=False)
        inputs = output / 'inputs'; inputs.mkdir()
        (inputs / 'case.json').write_text(hidden.prepare_case())
        shutil.copy2(hidden.ENVIRONMENT, inputs / 'environment.bin')
        rescan.verify_model(hidden.MODEL); shutil.copytree(hidden.MODEL, inputs / 'model'); rescan.verify_model(inputs / 'model')
        sources, libraries, compiler_sha = rescan.build_snapshot(inputs)
        visual = builder.prepare(inputs / 'visual-build')
        if visual['originalSource'] != builder.hashes(inputs / 'flex-source'):
            raise ValueError('simulator and visual client source snapshots differ')
        env = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'SDL_VIDEODRIVER': 'offscreen',
               'LD_LIBRARY_PATH': str(ROOT / 'build/flex/rocm-runtime'),
               'PUPPYBOT_PHYSICAL_NAV_LIMIT': '90', 'PUPPYBOT_PHYSICAL_POLL_LIMIT': '1499'}
        worker = hidden.supervisor.worker_snapshot(env)
        (output / 'worker-inputs.json').write_text(json.dumps(worker, sort_keys=True, indent=2) + '\n')
        pins = pinned_files(inputs, output)
        paths = {'client': str(inputs / 'visual-build/client'), 'simulator': str(inputs / 'simulator'),
                 'case': str(inputs / 'case.json'), 'environment': str(inputs / 'environment.bin'),
                 'asset': str(ROOT / 'build/flex/sim/puppybot.bin'), 'model': str(inputs / 'model'),
                 'config': str(ROOT / 'puppybot.json'), 'runtime': str(ROOT / 'build/flex/rocm-runtime/libamdhip64.so')}
        manifest = {'schema': 'puppybot.sim-visual-stop-pair.v1', 'files': pins,
                    'requiredFiles': sorted(pins), 'paths': paths, 'compilerSHA256': compiler_sha,
                    'navigationLimit': 90, 'wallSecondsPerArm': 300,
                    'scope': 'single training-selection simulation; camera-based suspicion; no hardware stop guarantee'}
        (output / 'inputs.json').write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n')
        for arm in ('disabled', 'enabled'):
            if shutil.disk_usage(output).free < 8 * 1024**3: raise ValueError('insufficient free space')
            if pinned_files(inputs, output) != pins: raise ValueError('pinned inputs changed')
            parent = output / arm; parent.mkdir(); monitor = parent / 'monitor'; monitor.mkdir()
            argv = [paths['client'], paths['simulator'], paths['model'], paths['case'], paths['environment'], str(parent / 'run'), '--allow-zero-contact']
            (parent / 'command.json').write_text(json.dumps(argv, indent=2) + '\n')
            arm_env = dict(env, PUPPYBOT_SIM_VISUAL_STOP='1' if arm == 'enabled' else '0')
            (parent / 'environment.json').write_text(json.dumps(arm_env, sort_keys=True, indent=2) + '\n')
            status = hidden.supervise(argv, monitor, arm_env, 300)
            if status['signal'] is not None or status['timedOut'] or status['clientExit'] != 0 or status['remainingWorkersTerminated']:
                raise RuntimeError(arm + ' failed or needed cleanup; retain artifacts')
            if pinned_files(inputs, output) != pins: raise ValueError('pinned inputs changed')
            launch = shutil.which('python3', path=arm_env['PATH'])
            if not launch or Path(launch).absolute() != Path(worker['launchPath']) or Path(launch).resolve() != Path(worker['executable']):
                raise ValueError('mapping worker interpreter path changed')
            hidden.supervisor.verify_worker(worker); rescan.verify_model(inputs / 'model')
        auditor = ROOT / 'flex/tests/audit-sim-visual-stop-pair.py'
        audited = subprocess.run([sys.executable, '-I', str(auditor), str(output)], cwd=ROOT, capture_output=True, text=True, timeout=120)
        (output / 'audit.log').write_text(audited.stderr)
        if audited.returncode: raise RuntimeError('pair audit failed; retain artifacts')
        (output / 'audit.json').write_text(audited.stdout)
        print(audited.stdout, end='')


if __name__ == '__main__':
    if len(sys.argv) != 2: raise SystemExit(__doc__)
    run(Path(sys.argv[1]))
