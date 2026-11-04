#!/usr/bin/env python3
"""Post-hoc matched contact-stop trial using the existing GPU monitor."""
import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


debug = load('contact_debug_base', ROOT / 'experiments/l5-steering-hysteresis-debug-v1/replay.py')
prior_verify = debug.verify
PRIOR_OUTPUT = debug.plan.OUTPUT
PRIOR_MONITOR = debug.MONITOR
build = load('contact_build', HERE / 'build.py')
audit = load('contact_audit', HERE / 'audit.py')
base = debug.base
monitor = debug.monitor
P = debug.plan.P
OUTPUT = P / 'contact-stop-trial-v2'
MONITOR = P / 'contact-stop-monitored-v2'
MANIFEST = P / 'contact-stop-plan-v2.json'
ARMS = ('disabled', 'enabled')
ARM_SECONDS = 600


def command(row, arm):
    if row not in debug.plan.design()['conditions'] or arm not in ARMS: raise ValueError('unknown case or arm')
    argv = debug.plan.command(row, 'kick-hysteresis')
    argv[0] = str(build.BUILD / 'control')
    argv[argv.index('--output') + 1] = str(OUTPUT / 'games' / str(row['index']) / arm)
    if arm == 'enabled': argv.append('--contact-stop')
    return argv


def previous(row):
    return PRIOR_OUTPUT / 'games' / str(row['index']) / 'kick-hysteresis' / str(row['seed'])


def current():
    old = prior_verify(); receipt = build.verify(build.BUILD)
    paths = [Path(__file__), HERE / 'build.py', HERE / 'audit.py', debug.MANIFEST,
             PRIOR_MONITOR / 'completion.json', build.BUILD / 'build.json', build.BUILD / 'control']
    for row in debug.plan.design()['conditions']:
        prior = previous(row)
        paths += [prior / name for name in ('result.json', 'initial.json', 'chase.jsonl', 'decisions.jsonl',
                                            'steer-probe.jsonl', 'hysteresis.jsonl', 'scene/case.json', 'scene/environment.bin')]
    return {'schema': 'puppybot.contact-stop-plan.v1', 'status': 'frozen_before_play',
            'conditions': old['scenes'], 'arms': list(ARMS), 'horizon': 300,
            'weightsSHA256': old['weightsSHA256'], 'buildSHA256': receipt['controlSHA256'],
            'commands': [command(row, arm) for row in debug.plan.design()['conditions'] for arm in ARMS],
            'files': {str(path): base.sha(path) for path in paths},
            'scope': 'two deliberately selected training cases, stopped games fail; no physical or promotion claim'}


def verify():
    frozen = json.loads(MANIFEST.read_text())
    if current() != frozen: raise ValueError('contact trial inputs changed')
    return frozen


def freeze():
    monitor.guard.require_dedicated_process()
    with base.acquire_lock(P / '.l4-matched.lock'):
        for path in (MANIFEST, OUTPUT, MONITOR): base.require_new_output(path)
        base.require_capacity(P, 36 * 1024**3)
        frozen = current()
        if current() != frozen: raise ValueError('inputs changed while freezing')
        with MANIFEST.open('x') as stream:
            json.dump(frozen, stream, sort_keys=True, indent=2); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        fd = os.open(MANIFEST.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)
        return frozen


def reaudit(frozen):
    if json.loads((OUTPUT / 'inputs.json').read_text()) != frozen: raise ValueError('input mismatch')
    results = []
    for row in debug.plan.design()['conditions']:
        roots = [OUTPUT / 'games' / str(row['index']) / arm for arm in ARMS]
        for arm, root in zip(ARMS, roots):
            receipt = OUTPUT / 'monitors' / str(row['index']) / arm
            if json.loads((receipt / 'invocation.json').read_text()) != {'argv': command(row, arm), 'environment': debug.environment(), 'wallSeconds': ARM_SECONDS}:
                raise ValueError('arm invocation mismatch')
            if not monitor.clean(json.loads((receipt / 'supervisor-result.json').read_text())): raise ValueError('unclean arm')
            if debug.selection.snapshot(root / 'policy', debug.plan.MODEL) != frozen['weightsSHA256']:
                raise ValueError('policy snapshot mismatch')
        scene = next(item for item in frozen['conditions'] if item['index'] == row['index'])
        expected = {'weightsSHA256': frozen['weightsSHA256'], 'case.json': scene['files']['case.json'],
                    'environment.bin': scene['files']['environment.bin']}
        debug.saved.kick.saved_game(roots[0] / str(row['seed']), row['seed'], expected)
        result = audit.audit_pair(*(root / str(row['seed']) for root in roots), previous(row))
        summary = json.loads((roots[1] / 'summary.json').read_text())
        if summary.get('complete') is not (not result['stopped']) or summary.get('contactStoppedEpisodes') != int(result['stopped']):
            raise ValueError('summary does not count failed stop')
        results.append(result)
    return {'schema': 'puppybot.contact-stop-comparison.v1', 'status': 'diagnostic_only', 'pairs': results,
            'scope': 'known training cases; no execution or physical-stop attestation'}


def verify_saved(frozen):
    report = json.loads((OUTPUT / 'report.json').read_text())
    if report != reaudit(frozen): raise ValueError('saved audit differs')
    return report


def run():
    monitor.guard.require_dedicated_process()
    with base.acquire_lock(P / '.l4-matched.lock'):
        base.require_new_output(OUTPUT); base.require_capacity(P, 36 * 1024**3)
        frozen = verify(); OUTPUT.mkdir(); debug.write_new(OUTPUT / 'inputs.json', frozen)
        (OUTPUT / 'games').mkdir(); (OUTPUT / 'monitors').mkdir(); done = []
        try:
            for row in debug.plan.design()['conditions']:
                (OUTPUT / 'games' / str(row['index'])).mkdir(); (OUTPUT / 'monitors' / str(row['index'])).mkdir()
                for arm in ARMS:
                    base.require_capacity(P, 34 * 1024**3)
                    if verify() != frozen: raise ValueError('inputs changed')
                    receipt = OUTPUT / 'monitors' / str(row['index']) / arm; receipt.mkdir()
                    env = debug.environment(); argv = command(row, arm)
                    debug.write_new(receipt / 'invocation.json', {'argv': argv, 'environment': env, 'wallSeconds': ARM_SECONDS})
                    status = base.hidden.supervise(argv, receipt, env, ARM_SECONDS)
                    if not monitor.clean(status) or json.loads((receipt / 'supervisor-result.json').read_text()) != status:
                        raise ValueError('arm failed')
                    done.append({'seed': row['seed'], 'arm': arm})
            report = reaudit(frozen)
            if verify() != frozen: raise ValueError('inputs changed during trial')
            base.require_capacity(P, 32 * 1024**3); debug.write_new(OUTPUT / 'report.json', report)
        except BaseException as error:
            if not (OUTPUT / 'report.json').exists(): debug.write_new(OUTPUT / 'partial.json', {'status': 'censored', 'finished': done, 'reason': str(error)})
            raise


def python_call(function, *args):
    code = ('import importlib.util,sys;s=importlib.util.spec_from_file_location("contact_trial",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);getattr(m,sys.argv[2])(*sys.argv[3:])')
    return [sys.executable, '-I', '-c', code, str(Path(__file__).resolve()), function, *map(str, args)]


def configure_monitor():
    monitor.OUTPUT = OUTPUT; monitor.MONITOR = MONITOR; monitor.MANIFEST = MANIFEST
    monitor.REGISTER = Path(__file__).resolve(); monitor.verify_saved = verify_saved
    monitor.worker_command = lambda: python_call('run')


def describe_configuration():
    """CPU-only check that process-local monitor bindings survive reimport."""
    configure_monitor()
    print(json.dumps({'output': str(monitor.OUTPUT), 'registration': str(monitor.REGISTER),
                      'worker': monitor.worker_command()}, sort_keys=True))


def monitor_worker(path):
    configure_monitor(); monitor.monitor_worker(path)


def final_check(path, evidence_sha):
    configure_monitor(); print(json.dumps(monitor.final_check(path, evidence_sha), sort_keys=True))


def launch():
    # Reuse the reviewed debug launch and receipt checks, with all bindings
    # changed in this process. Spawned workers reimport this adapter above.
    debug.MONITOR = MONITOR; debug.plan.OUTPUT = OUTPUT
    debug.verify = verify; debug.verify_saved = verify_saved
    debug.configure_monitor = configure_monitor; debug.python_call = python_call
    return debug.launch()


if __name__ == '__main__':
    raise SystemExit('Disabled; reviewed build, frozen inputs and dedicated resource monitor required.')
