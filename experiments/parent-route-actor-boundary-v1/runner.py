#!/usr/bin/env python3
"""Dedicated guarded collector; direct CLI is disabled pending review."""
import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


registration = load('parent_route_registration', HERE / 'register.py')
guardian = load('parent_route_guardian', ROOT / 'experiments/dock-turn-rendered-probe-v1/guardian.py')
telemetry = load('parent_route_gpu', ROOT / 'flex/tests/monitored-visual-v4-smoke.py')
hidden = load('parent_route_subreaper', ROOT / 'flex/tests/run-physical-hidden-trial.py')
standalone = load('parent_route_standalone', ROOT / 'experiments/sim-stop-supervisor/supervisor.py')
game_audit = load('parent_route_game_audit', HERE / 'game-audit.py')
companion = load('parent_route_companion_audit', registration.COMPANION)
OUTPUT = registration.OUTPUT
LOCK = registration.BASE / '.l4-matched.lock'
GIB = 1024 ** 3


def write_new(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False); stream.write('\n')


def clean(status):
    return (isinstance(status, dict) and type(status.get('clientExit')) is int and status['clientExit'] == 0 and
            status.get('timedOut') is False and status.get('remainingWorkersTerminated') is False and
            status.get('signal') is None and type(status.get('processGroup')) is int and status['processGroup'] > 0)


def resource_read(output):
    output = Path(output)
    marker = output / 'baseline-passed.json'
    passed = marker.is_file() and not marker.is_symlink()
    if passed:
        value = json.loads(marker.read_text()); tick = value.get('monotonicSeconds')
        if value.get('status') != 'passed' or type(tick) not in (int, float) or not 0 < tick <= time.monotonic():
            raise ValueError('invalid baseline marker')
    gpu = telemetry.telemetry(telemetry.DEVICE)
    volumes = {name: shutil.disk_usage(path).free for name, path in
               (('workspace', ROOT), ('home', Path.home()), ('output', output))}
    return {'freeBytes': min(volumes.values()), 'volumes': volumes, 'gpuFreeBytes': gpu['freeBytes'],
            'gpuTotalBytes': gpu['totalBytes'], 'gpuUsedBytes': gpu['usedBytes'],
            'gpuBusyPercent': gpu['busyPercent'], 'baselinePassed': passed}


def catalog(plan, create=False):
    expected = {}
    for row in plan['rows']:
        name = OUTPUT / 'catalogs' / str(row['shard']) / str(row['episode'])
        target = Path(row['scene'])
        if create:
            name.parent.mkdir(parents=True, exist_ok=True)
            name.symlink_to(target, target_is_directory=True)
        if not name.is_symlink() or os.readlink(name) != str(target) or name.resolve(strict=True) != target:
            raise ValueError('collector scene catalog changed')
        for filename, digest in row['sceneSHA256'].items():
            if registration.sha(name / filename) != digest:
                raise ValueError('collector scene bytes changed')
        expected[str(name.relative_to(OUTPUT))] = str(target)
    return expected


def inventory(expected_links):
    files, links, directories = {}, {}, []
    excluded = {'inventory.json', 'completion.json', 'worker-result.json', 'coordinator-result.json', 'guardian-client.log', 'guardian.log',
                'guardian-telemetry.jsonl', 'guardian-result.json', 'guardian-launch.json'}
    def walk_error(error):
        raise error
    for directory, children, names in os.walk(OUTPUT, topdown=True, followlinks=False, onerror=walk_error):
        parent = Path(directory)
        for name in sorted(children):
            path = parent / name; relative = str(path.relative_to(OUTPUT))
            if relative in ('worker-supervisor', 'final-supervisor'):
                if path.is_symlink() or not path.is_dir():
                    raise ValueError('unsafe supervisor directory')
                children.remove(name)
            elif path.is_symlink():
                links[relative] = os.readlink(path); children.remove(name)
            elif path.is_dir():
                directories.append(relative)
            else:
                raise ValueError('unsafe output directory')
        for name in sorted(names):
            path = parent / name; relative = str(path.relative_to(OUTPUT))
            if relative in excluded:
                continue
            if path.is_symlink() or not path.is_file():
                raise ValueError('unsafe output file')
            files[relative] = {'size': path.stat().st_size, 'sha256': registration.sha(path)}
    if links != expected_links:
        raise ValueError('output catalog links differ')
    return {'files': files, 'links': links, 'directories': sorted(directories)}


def run_shard(plan, shard):
    directory = OUTPUT / f'monitor-{shard}'
    directory.mkdir()
    argv = plan['commands'][shard]; env = plan['environment']; deadline = plan['thresholds']['perShardSeconds']
    write_new(directory / 'invocation.json', {'argv': argv, 'environment': env, 'wallSeconds': deadline})
    status = hidden.supervise(argv, directory, env, deadline)
    if not clean(status) or json.loads((directory / 'supervisor-result.json').read_text()) != status:
        raise RuntimeError(f'collector shard {shard} failed or left descendants')


def worker():
    """Collect and audit inside the coordinator's separate subreaper."""
    plan = registration.verify()
    expected_links = catalog(plan, create=True)
    for shard in range(2):
        if registration.verify() != plan or catalog(plan) != expected_links:
            raise ValueError('collector inputs changed before shard')
        run_shard(plan, shard)
        if registration.verify() != plan or catalog(plan) != expected_links:
            raise ValueError('collector inputs changed during shard')
    report = game_audit.audit(registration.PRIOR, OUTPUT, companion)
    write_new(OUTPUT / 'report.json', report)
    observed = inventory(expected_links)
    if inventory(expected_links) != observed:
        raise ValueError('collector inventory changed during audit')
    write_new(OUTPUT / 'inventory.json', observed)
    if (json.loads((OUTPUT / 'inventory.json').read_text()) != observed or
            inventory(expected_links) != observed or registration.verify() != plan or
            game_audit.audit(registration.PRIOR, OUTPUT, companion) != report):
        raise ValueError('collector final readback differs')
    if inventory(expected_links) != observed:
        raise ValueError('collector inventory changed during final audit')
    write_new(OUTPUT / 'worker-result.json', {'status': 'collection_diagnostic_only',
              'reportSHA256': registration.sha(OUTPUT / 'report.json'),
              'inventorySHA256': registration.sha(OUTPUT / 'inventory.json'),
              'scope': 'local fitting-family data only; training and promotion are not authorized'})


def worker_command(function):
    if function not in ('worker', 'final_check'):
        raise ValueError('unexpected collector subprocess')
    return [sys.executable, '-I', '-c',
            'import importlib.util,sys;s=importlib.util.spec_from_file_location("r",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);getattr(m,sys.argv[2])()',
            str(Path(__file__).resolve()), function]


def verify_shards(plan):
    for shard in range(2):
        directory = OUTPUT / f'monitor-{shard}'
        expected = {'argv': plan['commands'][shard], 'environment': plan['environment'],
                    'wallSeconds': plan['thresholds']['perShardSeconds']}
        if (json.loads((directory / 'invocation.json').read_text()) != expected or
                not clean(json.loads((directory / 'supervisor-result.json').read_text()))):
            raise ValueError('collector shard invocation or supervisor differs')


def final_check():
    """Re-read all saved evidence after the collection worker has exited."""
    plan_hash = registration.sha(registration.PLAN); plan = registration.verify()
    paths = (OUTPUT / 'report.json', OUTPUT / 'inventory.json', OUTPUT / 'worker-result.json')
    hashes = {path.name: registration.sha(path) for path in paths}
    worker_result = json.loads((OUTPUT / 'worker-result.json').read_text())
    if (worker_result.get('status') != 'collection_diagnostic_only' or
            worker_result.get('reportSHA256') != hashes['report.json'] or
            worker_result.get('inventorySHA256') != hashes['inventory.json']):
        raise ValueError('collector worker evidence differs')
    verify_shards(plan)
    expected_links = catalog(plan)
    observed = json.loads((OUTPUT / 'inventory.json').read_text())
    if inventory(expected_links) != observed:
        raise ValueError('collector output changed after worker')
    report = game_audit.audit(registration.PRIOR, OUTPUT, companion)
    if report != json.loads((OUTPUT / 'report.json').read_text()):
        raise ValueError('collector saved-game audit differs')
    if (registration.verify() != plan or registration.sha(registration.PLAN) != plan_hash or
            any(registration.sha(path) != hashes[path.name] for path in paths) or
            catalog(plan) != expected_links or inventory(expected_links) != observed):
        raise ValueError('collector inputs or inventory changed during final check')
    print(json.dumps({'status': 'final_inventory_verified', 'planSHA256': plan_hash,
                      'workerSHA256': hashes['worker-result.json'], 'reportSHA256': hashes['report.json'],
                      'inventorySHA256': hashes['inventory.json']}, sort_keys=True))


def supervise_phase(plan, name, function, seconds):
    directory = OUTPUT / name
    argv = worker_command(function)
    write_new(directory / 'invocation.json', {'argv': argv, 'environment': plan['environment'], 'wallSeconds': seconds})
    status = hidden.supervise(argv, directory, plan['environment'], seconds)
    if not clean(status) or json.loads((directory / 'supervisor-result.json').read_text()) != status:
        raise RuntimeError(f'{name} failed or left descendants')
    return status


def supervisor_hashes():
    paths = {'workerStatusSHA256': OUTPUT / 'worker-supervisor/supervisor-result.json',
             'workerInvocationSHA256': OUTPUT / 'worker-supervisor/invocation.json',
             'workerLogSHA256': OUTPUT / 'worker-supervisor/client.log',
             'finalStatusSHA256': OUTPUT / 'final-supervisor/supervisor-result.json',
             'finalInvocationSHA256': OUTPUT / 'final-supervisor/invocation.json',
             'finalLogSHA256': OUTPUT / 'final-supervisor/client.log'}
    for path in paths.values():
        if path.is_symlink() or not path.is_file():
            raise ValueError('collector supervisor evidence missing or linked')
    return {key: registration.sha(path) for key, path in paths.items()}


def verify_supervisor_hashes(receipt):
    if any(receipt.get(key) != digest for key, digest in supervisor_hashes().items()):
        raise ValueError('collector supervisor evidence changed')


def verify_post_guard(plan, plan_hash):
    paths = (ROOT, OUTPUT, Path.home())
    if min(shutil.disk_usage(path).free for path in paths) < 34 * GIB:
        raise ValueError('disk below floor after guardian')
    if registration.verify() != plan or registration.sha(registration.PLAN) != plan_hash:
        raise ValueError('collector frozen inputs changed after guardian')
    if min(shutil.disk_usage(path).free for path in paths) < 34 * GIB:
        raise ValueError('disk below floor during final source verification')


def coordinator():
    """Run baseline, worker and final check while guardian retains its lock."""
    plan = registration.verify()
    with (OUTPUT / 'baseline.jsonl').open('x') as stream:
        telemetry.baseline(stream)
    marker_tmp = OUTPUT / 'baseline-passed.tmp'; marker = OUTPUT / 'baseline-passed.json'
    write_new(marker_tmp, {'status': 'passed', 'monotonicSeconds': time.monotonic()})
    os.link(marker_tmp, marker); marker_tmp.unlink()
    for name in ('worker-supervisor', 'final-supervisor'):
        (OUTPUT / name).mkdir()
    supervise_phase(plan, 'worker-supervisor', 'worker', 4000)
    supervise_phase(plan, 'final-supervisor', 'final_check', 1200)
    final = json.loads((OUTPUT / 'final-supervisor/client.log').read_text())
    if (final.get('status') != 'final_inventory_verified' or
            final.get('planSHA256') != registration.sha(registration.PLAN) or
            final.get('workerSHA256') != registration.sha(OUTPUT / 'worker-result.json') or
            final.get('reportSHA256') != registration.sha(OUTPUT / 'report.json') or
            final.get('inventorySHA256') != registration.sha(OUTPUT / 'inventory.json')):
        raise ValueError('collector final-check receipt differs')
    write_new(OUTPUT / 'coordinator-result.json', {**final, 'status': 'collection_diagnostic_only',
              **supervisor_hashes()})


def guardian_entry(parent_pid):
    command = coordinator_command()
    plan = json.loads(registration.PLAN.read_text())
    result = guardian.run(OUTPUT, LOCK, command, plan['environment'], int(parent_pid), lambda: resource_read(OUTPUT),
                          wall_seconds=7500)
    if result.get('status') != 'passed':
        raise RuntimeError('collector guardian failed; partial evidence retained')


def coordinator_command():
    return [sys.executable, '-I', '-c',
            'import importlib.util,sys;s=importlib.util.spec_from_file_location("r",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.coordinator()', str(Path(__file__).resolve())]


def verify_baseline(path, start, marker_tick):
    rows = [json.loads(line) for line in Path(path).read_text().splitlines()]
    if len(rows) < 2 or any(row.get('phase') != 'baseline' or 'error' in row for row in rows):
        raise ValueError('baseline telemetry missing')
    times = [row.get('monotonicSeconds') for row in rows]
    if (any(type(t) not in (int, float) or not math.isfinite(t) for t in times) or
            any(not 0 < b - a <= 2.5 for a, b in zip(times, times[1:])) or
            times[-1] - times[0] < 30 or not start <= times[0] <= times[-1] <= marker_tick):
        raise ValueError('baseline telemetry coverage differs')
    sustained = 0
    for row in rows:
        total = row.get('totalBytes'); used = row.get('usedBytes'); free = row.get('freeBytes'); busy = row.get('busyPercent')
        if (type(total) is not int or type(used) is not int or type(free) is not int or total <= 0 or
                not 0 <= used <= total or free != total - used or free < 6 * GIB or
                type(busy) is not int or not 0 <= busy <= 100):
            raise ValueError('baseline telemetry sample invalid')
        sustained = sustained + 1 if busy > 10 else 0
        if sustained >= 5:
            raise ValueError('GPU busy throughout baseline')
    return {'samples': len(rows), 'duration': times[-1] - times[0]}


def verify_guardian(output, launcher, guardian_pid):
    output = Path(output)
    launch = json.loads((output / 'guardian-launch.json').read_text())
    result = json.loads((output / 'guardian-result.json').read_text())
    rows = [json.loads(line) for line in (output / 'guardian-telemetry.jsonl').read_text().splitlines()]
    active = [row for row in rows if row.get('phase') == 'active']
    cleanup = [row for row in rows if row.get('phase') == 'cleanup']
    env = dict(launcher['environment'])
    env.update(PUPPY_TURN_GUARD_PID=str(guardian_pid),
               PUPPY_TURN_GUARD_FD=launch.get('environment', {}).get('PUPPY_TURN_GUARD_FD'),
               PUPPY_TURN_GUARD_OUTPUT=str(output))
    if (launch.get('guardianPID') != guardian_pid or launch.get('parentPID') != os.getpid() or
            type(launch.get('coordinatorPID')) is not int or launch['coordinatorPID'] <= 1 or
            launch.get('wallSeconds') != 7500 or launch.get('environment') != env or launch.get('command') != coordinator_command() or
            not isinstance(env['PUPPY_TURN_GUARD_FD'], str) or not env['PUPPY_TURN_GUARD_FD'].isdigit()):
        raise ValueError('guardian invocation differs')
    if (result.get('status') != 'passed' or result.get('reason') is not None or
            type(result.get('coordinatorExit')) is not int or result['coordinatorExit'] != 0 or
            result.get('descendantsTerminated') is not False or result.get('diskEmergency') is not False or
            len(active) < 1 or len(cleanup) < 2 or len(rows) != result.get('samples') or
            [row.get('phase') for row in rows] != ['active'] * len(active) + ['cleanup'] * len(cleanup)):
        raise ValueError('guardian did not finish cleanly')
    times = [row.get('monotonicSeconds') for row in rows]
    if (any(type(t) not in (int, float) or not math.isfinite(t) for t in times) or
            any(not 0 < b - a <= 2.5 for a, b in zip(times, times[1:])) or
            not launch['startedMonotonic'] <= times[0] <= result['observedDoneMonotonic'] <= times[-1] <= result['endedMonotonic'] or
            times[0] - launch['startedMonotonic'] > 2.5 or result['endedMonotonic'] - times[-1] > 2.5):
        raise ValueError('guardian resource sample coverage incomplete')
    marker_path = output / 'baseline-passed.json'
    if marker_path.is_symlink() or not marker_path.is_file():
        raise ValueError('invalid baseline marker file')
    marker = json.loads(marker_path.read_text())
    marker_tick = marker.get('monotonicSeconds')
    if (marker.get('status') != 'passed' or type(marker_tick) not in (int, float) or
            not math.isfinite(marker_tick) or not launch['startedMonotonic'] <= marker_tick <= result['observedDoneMonotonic']):
        raise ValueError('baseline marker differs')
    seen_passed = False
    for row in rows:
        volumes = row.get('volumes'); passed = row.get('baselinePassed')
        if type(passed) is not bool or (seen_passed and not passed) or (passed and row['monotonicSeconds'] < marker_tick):
            raise ValueError('guardian baseline phase differs')
        seen_passed = seen_passed or passed
        floor = 34 if passed else 38
        if (not isinstance(volumes, dict) or set(volumes) != {'workspace', 'home', 'output'} or
                any(type(value) is not int or value < floor * GIB for value in volumes.values()) or
                row.get('freeBytes') != min(volumes.values()) or type(row.get('gpuFreeBytes')) is not int or
                type(row.get('gpuTotalBytes')) is not int or type(row.get('gpuUsedBytes')) is not int or
                row['gpuTotalBytes'] <= 0 or not 0 <= row['gpuUsedBytes'] <= row['gpuTotalBytes'] or
                row['gpuFreeBytes'] != row['gpuTotalBytes'] - row['gpuUsedBytes'] or row['gpuFreeBytes'] < 2 * GIB or
                type(row.get('gpuBusyPercent')) is not int or not 0 <= row['gpuBusyPercent'] <= 100):
            raise ValueError('guardian resource sample invalid')
    if not seen_passed:
        raise ValueError('guardian missed baseline completion')
    verify_baseline(output / 'baseline.jsonl', launch['startedMonotonic'], marker_tick)
    return result


def launch():
    standalone.require_dedicated_process()
    if OUTPUT.exists() or OUTPUT.is_symlink():
        raise FileExistsError('collector output exists; preserve it')
    if min(shutil.disk_usage(path).free for path in (ROOT, Path.home())) < 38 * GIB:
        raise ValueError('insufficient free disk before collection')
    plan = registration.verify(); plan_hash = registration.sha(registration.PLAN)
    OUTPUT.mkdir()
    command = [sys.executable, '-I', '-c',
               'import importlib.util,sys;s=importlib.util.spec_from_file_location("r",sys.argv[1]);'
               'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.guardian_entry(sys.argv[2])',
               str(Path(__file__).resolve()), str(os.getpid())]
    launch_record = {'command': command, 'environment': plan['environment'], 'planSHA256': plan_hash}
    write_new(OUTPUT / 'launcher.json', launch_record)
    with (OUTPUT / 'guardian.log').open('x') as log:
        process = subprocess.Popen(command, cwd=ROOT, env=plan['environment'], stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        code = process.wait()
    if code != 0:
        raise RuntimeError('collector guardian failed; partial evidence retained')
    verify_guardian(OUTPUT, launch_record, process.pid)
    worker = json.loads((OUTPUT / 'worker-result.json').read_text())
    coordinator_result = json.loads((OUTPUT / 'coordinator-result.json').read_text())
    for name, function, seconds in (('worker-supervisor', 'worker', 4000),
                                    ('final-supervisor', 'final_check', 1200)):
        directory = OUTPUT / name
        expected = {'argv': worker_command(function), 'environment': plan['environment'], 'wallSeconds': seconds}
        if (json.loads((directory / 'invocation.json').read_text()) != expected or
                not clean(json.loads((directory / 'supervisor-result.json').read_text()))):
            raise ValueError('collector supervisor invocation or status differs')
    verify_supervisor_hashes(coordinator_result)
    verify_post_guard(plan, plan_hash)
    if (coordinator_result.get('status') != 'collection_diagnostic_only' or
            coordinator_result.get('planSHA256') != plan_hash or
            coordinator_result.get('workerSHA256') != registration.sha(OUTPUT / 'worker-result.json') or
            coordinator_result.get('reportSHA256') != registration.sha(OUTPUT / 'report.json') or
            coordinator_result.get('inventorySHA256') != registration.sha(OUTPUT / 'inventory.json') or
            worker.get('status') != 'collection_diagnostic_only' or
            worker.get('reportSHA256') != registration.sha(OUTPUT / 'report.json') or
            worker.get('inventorySHA256') != registration.sha(OUTPUT / 'inventory.json') or
            registration.sha(registration.PLAN) != plan_hash):
        raise ValueError('collector final evidence differs')
    write_new(OUTPUT / 'completion.json', {'status': 'collection_diagnostic_only', 'planSHA256': plan_hash,
              'coordinatorSHA256': registration.sha(OUTPUT / 'coordinator-result.json'),
              'workerSHA256': registration.sha(OUTPUT / 'worker-result.json'),
              'guardianLaunchSHA256': registration.sha(OUTPUT / 'guardian-launch.json'),
              'guardianResultSHA256': registration.sha(OUTPUT / 'guardian-result.json'),
              'guardianTelemetrySHA256': registration.sha(OUTPUT / 'guardian-telemetry.jsonl'),
              'baselineSHA256': registration.sha(OUTPUT / 'baseline-passed.json'),
              'scope': 'fitting-family collection only; no training or promotion authorization'})
    return worker


if __name__ == '__main__':
    raise SystemExit('Disabled pending complete tests and independent review.')
