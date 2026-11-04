#!/usr/bin/env python3
"""Frozen two-arm fault diagnostic using the existing GPU monitor."""
import importlib.util
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
BUILD = P / 'sim-fault-real-peer-build-v1'
BUILD_MONITOR = P / 'sim-fault-real-peer-build-monitor-v1'
SCENE = P / 'contact-stop-trial-v2/games/1/disabled/6800107/scene'
OUTPUT = P / 'sim-fault-real-peer-trial-v1'
MONITOR = P / 'sim-fault-real-peer-monitor-v1'
MANIFEST = P / 'sim-fault-real-peer-plan-v1.json'
ARMS = ('control', 'fault')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


builder = load('fault_peer_build', HERE / 'build.py')
trial = load('fault_peer_trial', HERE / 'trial.py')
monitor = load('fault_peer_monitor', ROOT / 'experiments/l5-steering-hysteresis-v1/monitor.py')
base = monitor.base
guard = monitor.guard
prior = load('fault_runtime_identity', ROOT / 'experiments/l5-steering-kick-v1/register.py')


def environment():
    return {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'SDL_VIDEODRIVER': 'offscreen',
            'PUPPYBOT_PROJECT': str(ROOT), 'LD_LIBRARY_PATH': str(ROOT / 'build/flex/rocm-runtime')}


def simulator_command():
    return [str(BUILD / 'simulator'), '--hidden', '--case-file', str(SCENE / 'case.json'),
            '--environment', str(SCENE / 'environment.bin'), '--steps', '1000000', '--bind', '127.0.0.1:0',
            '--observer-distance-mm', '2500', '--tcp-view', '--no-visual-odometry', '--camera-pitch', '82']


def python_call(function, *args):
    code = ('import importlib.util,sys;s=importlib.util.spec_from_file_location("e",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);getattr(m,sys.argv[2])(*sys.argv[3:])')
    return [sys.executable, '-I', '-c', code, str(Path(__file__).resolve()), function, *map(str, args)]


def current():
    report = builder.verify(BUILD)
    build_status = json.loads((BUILD_MONITOR / 'result.json').read_text())
    if build_status.get('status') != 'isolated_build_only': raise ValueError('missing successful build supervision')
    paths = [Path(__file__), HERE / 'build.py', HERE / 'probe.flex', HERE / 'trial.py',
             HERE / 'build-supervisor.py', ROOT / 'experiments/l5-steering-kick-v1/register.py',
             ROOT / 'experiments/l5-steering-kick-v1/plan.py',
             ROOT / 'experiments/l5-steering-kick-v1/prepare.py',
             ROOT / 'experiments/l5-steering-kick-v1/transform.py',
             ROOT / 'experiments/l5-steering-hysteresis-v1/prepare.py',
             ROOT / 'experiments/l5-steering-hysteresis-v1/transform.py',
             ROOT / 'experiments/contact-stop-v1/transform.py',
             ROOT / 'experiments/contact-stop-v1/contact-stop.flex',
             ROOT / 'experiments/contact-stop-trial-v1/build.py',
             ROOT / 'experiments/physical-dock-confirm-v1/build.py',
             ROOT / 'experiments/physical-dock-confirm-v1/transform.py',
             ROOT / 'experiments/physical-dock-confirm-trial-v1/run.py',
             ROOT / 'experiments/physical-search-fallback-trial-v1/run.py',
             ROOT / 'experiments/physical-search-fallback-v1/prepare.py',
             ROOT / 'experiments/contact-stop-io-failsafe-v1/transform.py',
             ROOT / 'experiments/l5-steering-hysteresis-v1/monitor.py',
             ROOT / 'experiments/sim-stop-supervisor/supervisor.py',
             ROOT / 'experiments/sim-stop-supervisor/proxy.py',
             ROOT / 'flex/tests/monitored-visual-v4-smoke.py',
             ROOT / 'flex/tests/run-physical-hidden-trial.py',
             ROOT / 'flex/tests/run-physical-rescan-trial.py',
             ROOT / 'flex/tests/run-physical-hybrid-trial.py',
             ROOT / 'datasets/visual-control/chase-v1/levels/run-route-factorial.py',
             ROOT / 'datasets/visual-control/chase-v1/levels/route-coverage.py',
             ROOT / 'datasets/visual-control/chase-v1/levels/prepare-route-factorial.py',
             ROOT / 'datasets/visual-control/chase-v1/levels/package-matched-epoch8.py',
             ROOT / 'datasets/visual-control/chase-v1/levels/audit-matched-training.py',
             ROOT / 'datasets/visual-control/chase-v1/levels/audit-selection.py',
             BUILD / 'build.json', BUILD / 'simulator', BUILD / 'probe',
             BUILD_MONITOR / 'result.json', BUILD_MONITOR / 'worker-result.json',
             SCENE / 'case.json', SCENE / 'environment.bin', ROOT / 'puppybot.json',
             ROOT / 'build/flex/sim/puppybot.bin', Path(sys.executable).resolve()]
    return {'schema': 'puppybot.sim-fault-real-peer-plan.v1', 'status': 'frozen_before_play',
            'arms': list(ARMS), 'simulatorCommand': simulator_command(),
            'buildSHA256': builder.sha(BUILD / 'build.json'), 'simulatorSHA256': report['simulatorSHA256'],
            'probeSHA256': report['probeSHA256'], 'files': {str(p): builder.sha(p) for p in paths},
            'runtime': prior.runtime_chain(),
            'scope': 'one known virtual selection case, synthetic client response fault; no physical or policy claim'}


def verify():
    saved = json.loads(MANIFEST.read_text())
    if current() != saved: raise ValueError('registered fault inputs changed')
    return saved


def freeze():
    guard.require_dedicated_process()
    with base.acquire_lock(P / '.l4-matched.lock'):
        for path in (MANIFEST, OUTPUT, MONITOR): base.require_new_output(path)
        base.require_capacity(P, 36 * 1024**3); value = current()
        if current() != value: raise ValueError('inputs changed during registration')
        with MANIFEST.open('x') as stream:
            json.dump(value, stream, sort_keys=True, indent=2); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        return value


def arm(mode):
    trial.run_arm(OUTPUT / mode, simulator_command(), BUILD / 'probe', mode, environment())


def reaudit(frozen):
    if json.loads((OUTPUT / 'inputs.json').read_text()) != frozen: raise ValueError('input manifest differs')
    for mode in ARMS:
        receipt = OUTPUT / 'supervisors' / mode
        expected = {'argv': python_call('arm', mode), 'environment': environment(), 'wallSeconds': 180}
        if (json.loads((receipt / 'invocation.json').read_text()) != expected or
                not monitor.clean(json.loads((receipt / 'supervisor-result.json').read_text()))):
            raise ValueError('arm invocation or supervisor failed')
    return trial.audit(OUTPUT / 'control', OUTPUT / 'fault')


def verify_saved(frozen):
    report = json.loads((OUTPUT / 'report.json').read_text())
    if reaudit(frozen) != report: raise ValueError('saved re-audit differs')
    return report


def run():
    guard.require_dedicated_process()
    with base.acquire_lock(P / '.l4-matched.lock'):
        base.require_new_output(OUTPUT); base.require_capacity(P, 36 * 1024**3); frozen = verify()
        OUTPUT.mkdir(); monitor.write_new(OUTPUT / 'inputs.json', frozen); (OUTPUT / 'supervisors').mkdir(); done = []
        try:
            for mode in ARMS:
                base.require_capacity(P, 34 * 1024**3)
                if verify() != frozen: raise ValueError('inputs changed')
                receipt = OUTPUT / 'supervisors' / mode; receipt.mkdir()
                argv = python_call('arm', mode); env = environment()
                monitor.write_new(receipt / 'invocation.json', {'argv': argv, 'environment': env, 'wallSeconds': 180})
                status = base.hidden.supervise(argv, receipt, env, 180)
                if not monitor.clean(status) or json.loads((receipt / 'supervisor-result.json').read_text()) != status:
                    raise ValueError('arm failed')
                done.append(mode)
            report = reaudit(frozen)
            if verify() != frozen: raise ValueError('inputs changed during trial')
            base.require_capacity(P, 32 * 1024**3); monitor.write_new(OUTPUT / 'report.json', report)
        except BaseException as error:
            if not (OUTPUT / 'report.json').exists():
                monitor.write_new(OUTPUT / 'partial.json', {'status': 'censored', 'finished': done, 'reason': str(error)})
            raise


def configure_monitor():
    monitor.OUTPUT = OUTPUT; monitor.MONITOR = MONITOR; monitor.MANIFEST = MANIFEST
    monitor.REGISTER = Path(__file__).resolve(); monitor.verify_saved = verify_saved
    monitor.worker_command = lambda: python_call('run')


def describe_configuration():
    configure_monitor()
    print(json.dumps({'output': str(monitor.OUTPUT), 'registration': str(monitor.REGISTER),
                      'worker': monitor.worker_command()}, sort_keys=True))


def monitor_worker(path):
    configure_monitor(); monitor.monitor_worker(path)


def final_check(path, evidence_sha):
    configure_monitor(); print(json.dumps(monitor.final_check(path, evidence_sha), sort_keys=True))


def launch():
    guard.require_dedicated_process(); configure_monitor(); monitor.require_disk(36); frozen = verify()
    for path in (MONITOR, OUTPUT): base.require_new_output(path)
    env = monitor.environment(); command = python_call('monitor_worker', MONITOR)
    MONITOR.mkdir(); outer = MONITOR / 'outer-monitor'; outer.mkdir()
    monitor.write_new(MONITOR / 'launch.json', {'command': command, 'environment': env,
        'wallSeconds': monitor.OUTER_SECONDS, 'sourcePins': frozen['files']})
    status = base.hidden.supervise(command, outer, env, monitor.OUTER_SECONDS)
    if not monitor.clean(status) or json.loads((outer / 'supervisor-result.json').read_text()) != status:
        raise RuntimeError('resource monitor failed; retained output censored')
    if verify() != frozen or json.loads((MONITOR / 'monitor-result.json').read_text()).get('status') != 'passed':
        raise ValueError('inputs or monitor differ')
    evidence_path = MONITOR / 'evidence.json'; evidence_sha = builder.sha(evidence_path)
    evidence = json.loads(evidence_path.read_text())
    if evidence.get('status') != 'diagnostic_only' or evidence.get('report') != verify_saved(frozen):
        raise ValueError('saved evidence differs')
    monitor.verify_logs(MONITOR); monitor.require_disk(32)
    snapshots = {str(path): builder.sha(path) for path in (MONITOR / 'telemetry.jsonl', MONITOR / 'disk.jsonl',
        MONITOR / 'frozen-manifest.json', MONITOR / 'monitor-result.json', outer / 'supervisor-result.json')}
    final = MONITOR / 'final-inventory-monitor'; final.mkdir(); argv = python_call('final_check', MONITOR, evidence_sha)
    monitor.write_new(final / 'invocation.json', {'argv': argv, 'environment': env, 'wallSeconds': monitor.FINAL_CHECK_SECONDS})
    status = base.hidden.supervise(argv, final, env, monitor.FINAL_CHECK_SECONDS)
    if (not monitor.clean(status) or json.loads((final / 'supervisor-result.json').read_text()) != status or
            json.loads((final / 'client.log').read_text()) != {'status': 'final_inventory_verified'}):
        raise RuntimeError('final inventory failed; retained output censored')
    if verify() != frozen or builder.sha(evidence_path) != evidence_sha or any(builder.sha(p) != h for p, h in snapshots.items()):
        raise ValueError('inputs or evidence changed')
    monitor.require_disk(32)
    monitor.write_new(MONITOR / 'completion.json', {'status': 'diagnostic_only', 'evidenceSHA256': evidence_sha,
        'monitorSnapshots': snapshots, 'finalStatusSHA256': builder.sha(final / 'supervisor-result.json'),
        'scope': 'simulator-only fault experiment; no physical or policy claim'})
    return evidence['report']


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and resource scheduling.')
