#!/usr/bin/env python3
"""Disabled lock-held guardian for a preregistered full-epoch pair."""
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


HERE = Path(__file__).resolve().parent
import importlib.util
spec = importlib.util.spec_from_file_location('full_pair_plan', HERE / 'plan.py')
plan = importlib.util.module_from_spec(spec); spec.loader.exec_module(plan)
spec = importlib.util.spec_from_file_location('full_pair_audit', HERE / 'audit.py')
audit = importlib.util.module_from_spec(spec); spec.loader.exec_module(audit)
guardian = plan.smoke.guardian
hidden = plan.smoke.hidden
telemetry = plan.smoke.telemetry
GIB = plan.GIB
LOCK = plan.P / '.l4-matched.lock'
WALL = 7500
HEADROOM = 128 * 1024 ** 2


def write_new(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False); stream.write('\n')
        stream.flush(); os.fsync(stream.fileno())


def reserve(free, data_size):
    needed = 34 * GIB + data_size + HEADROOM
    if type(free) is not int or type(data_size) is not int or data_size <= 0 or free < needed:
        raise ValueError('insufficient unshared data-copy reservation above active floor')
    return {'freeBytes': free, 'dataBytes': data_size, 'headroomBytes': HEADROOM, 'requiredBytes': needed}


def resource_read():
    marker = plan.OUTPUT / 'baseline-passed.json'; passed = marker.is_file() and not marker.is_symlink()
    if passed:
        data = json.loads(marker.read_text()); tick = data.get('monotonicSeconds')
        if (data.get('status') != 'passed' or type(tick) not in (int, float) or
                not math.isfinite(tick) or not 0 < tick <= time.monotonic()):
            raise ValueError('invalid baseline marker')
    gpu = telemetry.telemetry(telemetry.DEVICE)
    volumes = {key: shutil.disk_usage(path).free for key, path in
               (('workspace', plan.ROOT), ('home', Path.home()), ('output', plan.OUTPUT))}
    return {'freeBytes': min(volumes.values()), 'volumes': volumes, 'gpuFreeBytes': gpu['freeBytes'],
            'gpuTotalBytes': gpu['totalBytes'], 'gpuUsedBytes': gpu['usedBytes'],
            'gpuBusyPercent': gpu['busyPercent'], 'baselinePassed': passed}


def baseline(arm):
    rows = []; consecutive = 0
    with (plan.OUTPUT / f'baseline-{arm}.jsonl').open('x') as log:
        while True:
            row = telemetry.sample(log, 'baseline'); rows.append(row)
            if row['freeBytes'] < 6 * GIB: raise ValueError('baseline free VRAM below 6 GiB')
            consecutive = consecutive + 1 if row['busyPercent'] > 10 else 0
            if consecutive >= 5: raise ValueError('GPU busy during baseline')
            remaining = 30 - (row['monotonicSeconds'] - rows[0]['monotonicSeconds'])
            if remaining <= 0: break
            time.sleep(min(1, remaining))
    check_baseline(rows)


def check_baseline(rows):
    if not isinstance(rows, list) or len(rows) < 2: raise ValueError('baseline samples missing')
    ticks = [row.get('monotonicSeconds') for row in rows]
    if (any(type(t) not in (int, float) or not math.isfinite(t) for t in ticks) or
            ticks[-1] - ticks[0] < 30 or any(not 0 < b - a <= 2.5 for a, b in zip(ticks, ticks[1:]))):
        raise ValueError('baseline duration or samples differ')
    consecutive = 0
    for row in rows:
        if (row.get('phase') != 'baseline' or
                any(type(row.get(k)) is not int for k in ('busyPercent', 'freeBytes', 'usedBytes', 'totalBytes')) or
                not 0 <= row['busyPercent'] <= 100 or row['totalBytes'] <= 0 or
                not 0 <= row['usedBytes'] <= row['totalBytes'] or
                row['freeBytes'] != row['totalBytes'] - row['usedBytes'] or row['freeBytes'] < 6 * GIB):
            raise ValueError('invalid GPU baseline row')
        consecutive = consecutive + 1 if row['busyPercent'] > 10 else 0
        if consecutive >= 5: raise ValueError('GPU baseline busy')


def read_json(path):
    if Path(path).is_symlink() or not Path(path).is_file(): raise ValueError('missing or linked evidence')
    return json.loads(Path(path).read_text())


def clean(status):
    return plan.smoke.clean(status)


def inventory():
    result = {}
    def walk_error(error):
        raise error
    for arm in ('control', 'treatment', 'fixed-control', 'fixed-treatment'):
        root = plan.OUTPUT / arm
        if root.is_symlink() or not root.is_dir(): raise ValueError('model output missing or linked')
        for directory, children, names in os.walk(root, followlinks=False, onerror=walk_error):
            parent = Path(directory)
            for name in children:
                child = parent / name
                if child.is_symlink() or not child.is_dir(): raise ValueError('unsafe model directory')
            for name in names:
                path = parent / name
                if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
                    raise ValueError('unsafe model file')
                result[str(path.relative_to(plan.OUTPUT))] = {'size': path.stat().st_size, 'sha256': plan.sha(path)}
    return result


def verify_arms():
    reports = {}
    for arm in ('control', 'treatment'):
        directory = plan.OUTPUT / f'supervisor-{arm}'
        if (read_json(directory / 'invocation.json') != {'argv': plan.command(arm),
                'environment': plan.smoke.plan.environment(), 'wallSeconds': plan.WALL} or
                not clean(read_json(directory / 'supervisor-result.json'))):
            raise ValueError('training subprocess invocation or completion differs')
        rows = [json.loads(line) for line in (plan.OUTPUT / f'baseline-{arm}.jsonl').read_text().splitlines()]
        check_baseline(rows)
        reports[arm] = {'model': audit.model(plan, arm), 'fixedPackage': audit.verify_package(plan, arm)}
    schedules = audit.schedules(plan)
    return {'status': 'full_epoch_pair_diagnostic_only', 'arms': reports, 'schedule': schedules,
            'scope': 'matched training only; no automatic promotion, held-out or physical claim'}


def evidence_hashes():
    paths = ['baseline-control.jsonl', 'baseline-treatment.jsonl', 'reservation-control.json',
             'reservation-treatment.json', 'final-result.json']
    for arm in ('control', 'treatment'):
        paths += [f'supervisor-{arm}/{name}' for name in ('invocation.json', 'supervisor-result.json', 'client.log')]
    return {name: plan.sha(plan.OUTPUT / name) for name in paths}


def final_check():
    frozen = plan.verify(); digest = plan.sha(plan.PLAN)
    plan.deep_check(frozen)
    report = verify_arms(); files = inventory()
    if plan.verify() != frozen or plan.sha(plan.PLAN) != digest:
        raise ValueError('inputs changed during final paired training audit')
    plan.verify_smoke_data_copies(frozen)
    write_new(plan.OUTPUT / 'final-result.json', {'status': 'full_epoch_pair_diagnostic_only',
              'planSHA256': digest, 'report': report, 'inventory': files})


def command(function):
    if function not in ('coordinator', 'final_check'): raise ValueError('unknown smoke phase')
    code = ('import importlib.util,sys;s=importlib.util.spec_from_file_location("fullpair",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);getattr(m,sys.argv[2])()')
    return [sys.executable, '-I', '-c', code, str(Path(__file__).resolve()), function]


def coordinator():
    frozen = plan.verify(); digest = plan.sha(plan.PLAN)
    for arm in ('control', 'treatment'):
        if plan.verify() != frozen or plan.sha(plan.PLAN) != digest: raise ValueError('training inputs changed')
        baseline(arm)
        if arm == 'control':
            temporary = plan.OUTPUT / 'baseline-passed.tmp'; marker = plan.OUTPUT / 'baseline-passed.json'
            write_new(temporary, {'status': 'passed', 'monotonicSeconds': time.monotonic()})
            os.link(temporary, marker); temporary.unlink()
        directory = plan.OUTPUT / f'supervisor-{arm}'; directory.mkdir()
        write_new(directory / 'invocation.json', {'argv': plan.command(arm), 'environment': plan.smoke.plan.environment(),
                  'wallSeconds': plan.WALL})
        free = min(shutil.disk_usage(path).free for path in (plan.ROOT, Path.home(), plan.OUTPUT))
        reservation = reserve(free, (plan.smoke.plan.DATA / arm / 'data.bin').stat().st_size)
        write_new(plan.OUTPUT / f'reservation-{arm}.json', reservation)
        status = hidden.supervise(plan.command(arm), directory, plan.smoke.plan.environment(), plan.WALL)
        if not clean(status) or read_json(directory / 'supervisor-result.json') != status:
            raise RuntimeError('training arm failed; partial evidence retained')
        audit.model(plan, arm)
    audit.schedules(plan)
    for arm in ('control', 'treatment'):
        audit.create_package(plan, arm)
    directory = plan.OUTPUT / 'supervisor-final'; directory.mkdir()
    write_new(directory / 'invocation.json', {'argv': command('final_check'), 'environment': plan.smoke.plan.environment(),
              'wallSeconds': 2400})
    status = hidden.supervise(command('final_check'), directory, plan.smoke.plan.environment(), 2400)
    if not clean(status) or read_json(directory / 'supervisor-result.json') != status:
        raise RuntimeError('training final checker failed')
    final = read_json(plan.OUTPUT / 'final-result.json')
    if final.get('status') != 'full_epoch_pair_diagnostic_only' or final.get('planSHA256') != digest:
        raise ValueError('training final audit missing')
    hashes = evidence_hashes()
    for name in ('invocation.json', 'supervisor-result.json', 'client.log'):
        hashes[f'supervisor-final/{name}'] = plan.sha(directory / name)
    write_new(plan.OUTPUT / 'coordinator-result.json', {'status': 'full_epoch_pair_diagnostic_only',
              'planSHA256': digest, 'evidenceSHA256': hashes})


def guardian_entry(parent_pid):
    result = guardian.run(plan.OUTPUT, LOCK, command('coordinator'), plan.smoke.plan.environment(), int(parent_pid),
                          resource_read, wall_seconds=WALL)
    if result.get('status') != 'passed': raise RuntimeError('training guardian failed')


def verify_guardian(pid):
    # Reuse the independently reviewed guardian-log validator with local bindings.
    paired = plan.smoke.plan.paired; old = paired.plan.MONITOR, paired.command, paired.environment
    try:
        paired.plan.MONITOR = plan.OUTPUT; paired.command = command; paired.environment = plan.smoke.plan.environment
        return paired.verify_guardian(pid)
    finally:
        paired.plan.MONITOR, paired.command, paired.environment = old


def launch():
    plan.smoke.plan.paired.standalone.require_dedicated_process()
    if plan.OUTPUT.exists() or plan.OUTPUT.is_symlink(): raise FileExistsError('training output exists')
    if min(shutil.disk_usage(path).free for path in (plan.ROOT, Path.home())) < 38 * GIB:
        raise ValueError('startup disk floor not met')
    frozen = plan.verify(); digest = plan.sha(plan.PLAN); plan.OUTPUT.mkdir()
    code = ('import importlib.util,sys;s=importlib.util.spec_from_file_location("fullpair",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.guardian_entry(sys.argv[2])')
    argv = [sys.executable, '-I', '-c', code, str(Path(__file__).resolve()), str(os.getpid())]
    write_new(plan.OUTPUT / 'launcher.json', {'argv': argv, 'environment': plan.smoke.plan.environment(), 'planSHA256': digest})
    with (plan.OUTPUT / 'guardian.log').open('x') as log:
        process = subprocess.Popen(argv, cwd=plan.ROOT, env=plan.smoke.plan.environment(), stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        code = process.wait()
    if code != 0: raise RuntimeError('training guardian failed; evidence retained')
    verify_guardian(process.pid)
    if min(shutil.disk_usage(path).free for path in (plan.ROOT, Path.home(), plan.OUTPUT)) < 34 * GIB:
        raise ValueError('post-guardian disk floor not met')
    coordinator_result = read_json(plan.OUTPUT / 'coordinator-result.json')
    final_supervisor = plan.OUTPUT / 'supervisor-final'
    if (read_json(final_supervisor / 'invocation.json') != {'argv': command('final_check'),
            'environment': plan.smoke.plan.environment(), 'wallSeconds': 2400} or
            not clean(read_json(final_supervisor / 'supervisor-result.json'))):
        raise ValueError('final training supervisor differs')
    for arm in ('control', 'treatment'):
        observed = read_json(plan.OUTPUT / f'reservation-{arm}.json')
        if observed != reserve(observed.get('freeBytes'), (plan.smoke.plan.DATA / arm / 'data.bin').stat().st_size):
            raise ValueError('training reservation receipt differs')
    hashes = evidence_hashes()
    for name in ('invocation.json', 'supervisor-result.json', 'client.log'):
        hashes[f'supervisor-final/{name}'] = plan.sha(plan.OUTPUT / 'supervisor-final' / name)
    final = read_json(plan.OUTPUT / 'final-result.json')
    if (coordinator_result.get('status') != 'full_epoch_pair_diagnostic_only' or
            coordinator_result.get('planSHA256') != digest or coordinator_result.get('evidenceSHA256') != hashes or
            final.get('planSHA256') != digest or final.get('inventory') != inventory() or
            final.get('report') != verify_arms() or plan.verify() != frozen or plan.sha(plan.PLAN) != digest):
        raise ValueError('training evidence changed after guardian cleanup')
    if min(shutil.disk_usage(path).free for path in (plan.ROOT, Path.home(), plan.OUTPUT)) < 34 * GIB:
        raise ValueError('post-guardian disk floor not met')
    plan.verify_smoke_data_copies(frozen)
    if min(shutil.disk_usage(path).free for path in (plan.ROOT, Path.home(), plan.OUTPUT)) < 34 * GIB:
        raise ValueError('post-guardian disk floor not met')
    write_new(plan.OUTPUT / 'completion.json', {'status': 'full_epoch_pair_diagnostic_only', 'planSHA256': digest,
              'coordinatorSHA256': plan.sha(plan.OUTPUT / 'coordinator-result.json'),
              'guardianResultSHA256': plan.sha(plan.OUTPUT / 'guardian-result.json'),
              'guardianTelemetrySHA256': plan.sha(plan.OUTPUT / 'guardian-telemetry.jsonl'),
              'scope': 'one epoch per arm; no selection, promotion, held-out or physical claim'})


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and scheduling; no GPU launch authorized.')
