#!/usr/bin/env python3
"""Disabled, no-overwrite wrapper for one hybrid physical-simulator trial.

Call only from a separately reviewed GPU/disk monitor in a dedicated process.
This script does not enable physical hardware or held-out qualification.
"""
import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
MODELS = P / 'search-dagger-heading/models'
PACKAGE = MODELS / 'heading-epoch8-pair'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


hidden = load('hybrid_hidden_runner', ROOT / 'flex/tests/run-physical-hidden-trial.py')
plan = load('heading_package', ROOT / 'datasets/visual-control/chase-v1/levels/heading-epoch8-selection.py')
guard = load('standalone_guard', ROOT / 'experiments/sim-stop-supervisor/supervisor.py')
base = plan.base


def write_new(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False); stream.write('\n')


def pins(arm):
    if arm not in ('control', 'treatment'): raise ValueError('expected control or treatment')
    paths = [Path(__file__), HERE / 'audit.py', ROOT / 'flex/tests/run-physical-hidden-trial.py',
             ROOT / 'flex/tests/run-physical-rescan-trial.py', ROOT / 'flex/tests/run-physical-hybrid-trial.py',
             ROOT / 'flex/exploration/manipulation_audit.py', ROOT / 'flex/tests/sim-cases.py',
             ROOT / 'experiments/sim-stop-supervisor/supervisor.py',
             ROOT / 'datasets/visual-control/chase-v1/levels/heading-epoch8-selection.py',
             ROOT / 'datasets/visual-control/chase-v1/levels/package-matched-epoch8.py',
             ROOT / 'puppybot.json', ROOT / 'build/flex/rocm-runtime/libamdhip64.so',
             ROOT / 'build/flex/control/compiler', hidden.ASSET, hidden.ENVIRONMENT,
             hidden.rescan.REFERENCE / 'case.json',
             PACKAGE / 'manifest.json', PACKAGE / arm / 'weights.bin', PACKAGE / arm / 'policy']
    return {str(path): hidden.sha(path) for path in paths}


def worker(output, arm):
    if arm not in ('control', 'treatment'): raise ValueError('expected fixed packaged arm')
    hidden.MODEL = PACKAGE / arm
    hidden.run_trial(Path(output))


def run(arm):
    """Must be wrapped by a reviewed GPU and disk monitor; never run in a shared process."""
    guard.require_dedicated_process()
    if arm not in ('control', 'treatment'): raise ValueError('expected control or treatment')
    output = P / f'hybrid-physical-eval-v1-{arm}'
    with base.acquire_lock(P / '.l4-matched.lock'):
        base.require_new_output(output); base.require_capacity(P, 36 * 1024**3)
        package_manifest = plan.package.verify(MODELS / 'control-s0', MODELS / 'treatment-s0', PACKAGE)
        initial = pins(arm)
        expected_weights = package_manifest['arms'][arm]['weightsSHA256']
        if hidden.sha(PACKAGE / arm / 'weights.bin') != expected_weights: raise ValueError('package weights differ')
        output.mkdir(); monitor = output / 'monitor'; monitor.mkdir()
        env = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'SDL_VIDEODRIVER': 'offscreen',
               'LD_LIBRARY_PATH': str(ROOT / 'build/flex/rocm-runtime')}
        launch = {'arm': arm, 'weightsSHA256': expected_weights,
                  'policySHA256': hidden.sha(PACKAGE / arm / 'policy'), 'sourcePins': initial,
                  'scope': 'single training-selection simulator case; intended inputs only; no execution attestation'}
        write_new(output / 'launch.json', launch)
        try:
            code = ('import importlib.util,sys;'
                    's=importlib.util.spec_from_file_location("hybrid",sys.argv[1]);'
                    'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.worker(sys.argv[2],sys.argv[3])')
            command = [sys.executable, '-I', '-c', code, str(Path(__file__).resolve()), str(output / 'trial'), arm]
            write_new(output / 'command.json', {'argv': command, 'cwd': str(ROOT), 'environment': env, 'wallSeconds': 900})
            status = hidden.supervise(command, monitor, env, wall_seconds=900)
            if (type(status.get('clientExit')) is not int or status['clientExit'] != 0 or status.get('signal') is not None or
                    status.get('timedOut') is not False or status.get('remainingWorkersTerminated') is not False):
                raise RuntimeError('trial timed out, failed or required cleanup')
            if pins(arm) != initial or plan.package.verify(MODELS / 'control-s0', MODELS / 'treatment-s0', PACKAGE) != package_manifest:
                raise ValueError('package or evaluation inputs changed')
            audit_monitor = output / 'audit-monitor'; audit_monitor.mkdir()
            audit_cmd = [sys.executable, '-I', str(HERE / 'audit.py'), str(output)]
            write_new(output / 'audit-command.json', {'argv': audit_cmd, 'cwd': str(ROOT), 'environment': env, 'wallSeconds': 300})
            audit_status = hidden.supervise(audit_cmd, audit_monitor, env, wall_seconds=300)
            if (type(audit_status.get('clientExit')) is not int or audit_status['clientExit'] != 0 or audit_status.get('signal') is not None or
                    audit_status.get('timedOut') is not False or audit_status.get('remainingWorkersTerminated') is not False):
                raise RuntimeError('independent outcome audit failed or timed out')
            outcome = json.loads((audit_monitor / 'client.log').read_text())
            if pins(arm) != initial: raise ValueError('inputs changed during outcome audit')
            base.require_capacity(P, 32 * 1024**3)
            write_new(output / 'outcome.json', outcome)
            if outcome.get('status') != 'diagnostic_only': raise ValueError('trial evidence was censored')
            return outcome
        except BaseException as error:
            if not (output / 'outcome.json').exists():
                write_new(output / 'outcome.json', {'status': 'censored', 'reason': str(error),
                          'scope': 'incomplete trial; no physical, held-out or policy-success claim'})
            raise


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and external GPU/disk monitoring.')
