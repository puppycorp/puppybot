#!/usr/bin/env python3
"""Dedicated, low-priority, lock-serialized candidate dataset build."""
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
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
MONITOR = P / 'outbound-five-aggregate-cpu-monitor-v1'
LOCK = P / '.l4-matched.lock'
WALL_SECONDS = 1800
GIB = 1024**3


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


builder = load('outbound_five_supervised_builder', HERE / 'build.py')
base = load('outbound_five_cpu_supervisor', ROOT / 'experiments/physical-search-fallback-build-supervisor-v1/supervisor.py')


def pins():
    frozen = json.loads((builder.MONITOR / 'frozen-inputs.json').read_text())
    result = builder.source_pins(frozen)
    paths = (Path(__file__), ROOT / 'experiments/physical-search-fallback-build-supervisor-v1/supervisor.py',
             ROOT / 'flex/tests/run-physical-hidden-trial.py',
             ROOT / 'experiments/sim-stop-supervisor/supervisor.py',
             ROOT / 'experiments/sim-stop-supervisor/proxy.py',
             Path(sys.executable).resolve(), base.NICE, base.IONICE)
    for path in paths:
        if not path.is_file(): raise ValueError('supervisor source or tool missing')
        result[str(path)] = base.sha(path)
    return result


def command():
    code = ('import importlib.util,sys;'
            's=importlib.util.spec_from_file_location("aggregate_supervisor",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.worker()')
    return [str(base.NICE), '-n', '15', str(base.IONICE), '-c', '3', sys.executable, '-I', '-c', code, str(HERE / 'supervise.py')]


def priority():
    cpu = os.getpriority(os.PRIO_PROCESS, 0)
    io = subprocess.run([str(base.IONICE), '-p', str(os.getpid())], capture_output=True, text=True, timeout=5, check=True).stdout.strip()
    if cpu < 15 or io != 'idle': raise ValueError('worker not low priority')
    return cpu, io


def worker():
    cpu, io = priority()
    expected = json.loads((MONITOR / 'launch.json').read_text())['sourcePins']
    if pins() != expected: raise ValueError('builder or supervisor sources changed before worker')
    report = builder.run()
    if pins() != expected: raise ValueError('builder or supervisor sources changed during worker')
    base.write_new(MONITOR / 'worker-result.json', {'status': 'candidate_data_only',
        'reportSHA256': base.sha(builder.OUTPUT / 'report.json'), 'dataSHA256': report['dataSHA256'],
        'mapSHA256': report['mapSHA256'], 'sourcePins': expected, 'cpuNice': cpu, 'ioClass': io})


def final_command():
    code = ('import importlib.util,sys;'
            's=importlib.util.spec_from_file_location("aggregate_supervisor",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.final_worker()')
    return [str(base.NICE), '-n', '15', str(base.IONICE), '-c', '3', sys.executable, '-I', '-c', code, str(HERE / 'supervise.py')]


def final_worker():
    cpu, io = priority()
    expected = json.loads((MONITOR / 'launch.json').read_text())['sourcePins']
    if pins() != expected: raise ValueError('sources changed before final recheck')
    report = json.loads((builder.OUTPUT / 'report.json').read_text())
    selected = [(r['episode'], r['firstConsumptionAction']) for r in report['selectedTeacherEpisodes']]
    if selected != [(3, 162), (4, 107), (5, 171), (6, 43), (8, 38)]:
        raise ValueError('selected episode order differs')
    measured = builder.verify.verify(builder.BASE/'data.bin', builder.BASE/'map.bin',
        builder.PILOT/'teacher/data.bin', builder.PILOT/'teacher/map.bin',
        builder.OUTPUT/'data.bin', builder.OUTPUT/'map.bin', selected)
    if measured != report['verification']: raise ValueError('independent byte and order verification differs')
    if (base.sha(builder.OUTPUT/'data.bin') != report['dataSHA256'] or
            base.sha(builder.OUTPUT/'map.bin') != report['mapSHA256'] or
            any(base.sha(path) != value for path,value in report['sourceFiles'].items()) or pins() != expected):
        raise ValueError('dataset or source changed during final recheck')
    base.write_new(MONITOR/'final-result.json', {'status':'candidate_bytes_verified',
        'reportSHA256':base.sha(builder.OUTPUT/'report.json'), 'verification':measured,
        'cpuNice':cpu, 'ioClass':io})


def launch():
    """Invoke in a dedicated process; never overwrite a partial output."""
    base.guard.require_dedicated_process(); priority = base.low_priority()
    for path in (MONITOR, builder.OUTPUT):
        if path.exists() or path.is_symlink(): raise FileExistsError('output exists; preserve it')
    # Reserve a complete unshared candidate even though FICLONE is required.
    # The creator separately checks the same amount under this lock.
    full = 64 + 1029 * 300 * (21168 + 56 + 144)
    if any(shutil.disk_usage(path).free < 36 * GIB + full for path in (ROOT, Path.home(), P)):
        raise ValueError('insufficient disk for conservative full-size reservation')
    with LOCK.open('r+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for path in (MONITOR, builder.OUTPUT):
            if path.exists() or path.is_symlink(): raise FileExistsError('output exists; preserve it')
        if any(shutil.disk_usage(path).free < 36 * GIB + full for path in (ROOT, Path.home(), P)):
            raise ValueError('disk changed before lock acquisition')
        sources = pins(); env = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home())}
        MONITOR.mkdir(); base.write_new(MONITOR/'launch.json', {'command':command(), 'environment':env,
            'wallSeconds':WALL_SECONDS, 'sourcePins':sources, 'output':str(builder.OUTPUT),
            'supervisorPriority':priority, 'scope':'CPU data build; advisory lock; 36 GiB plus full-size reservation'})
        try: status = base.hidden.supervise(command(), MONITOR, env, WALL_SECONDS)
        except BaseException as error:
            base.write_new(MONITOR/'result.json', {'status':'failed','reason':str(error)})
            raise
        reason = None
        try:
            if not base.clean(status) or json.loads((MONITOR/'supervisor-result.json').read_text()) != status:
                raise ValueError('unclean or inconsistent worker status')
            worker_result = json.loads((MONITOR/'worker-result.json').read_text())
            report = json.loads((builder.OUTPUT/'report.json').read_text())
            if pins() != sources or worker_result.get('sourcePins') != sources:
                raise ValueError('source pins changed')
            if (worker_result.get('status') != 'candidate_data_only' or report.get('status') != 'candidate_data_only' or
                    report.get('trainingAuthorized') is not False or worker_result.get('cpuNice',0) < 15 or
                    worker_result.get('ioClass') != 'idle' or
                    worker_result.get('reportSHA256') != base.sha(builder.OUTPUT/'report.json') or
                    worker_result.get('dataSHA256') != report.get('dataSHA256') or
                    worker_result.get('mapSHA256') != report.get('mapSHA256')):
                raise ValueError('worker result or report differs')
            if any(shutil.disk_usage(path).free < 36 * GIB for path in (ROOT, Path.home(), P)):
                raise ValueError('disk below final 36 GiB floor')
            final = MONITOR / 'final-monitor'; final.mkdir()
            base.write_new(final/'invocation.json', {'command':final_command(), 'environment':env, 'wallSeconds':WALL_SECONDS})
            final_status = base.hidden.supervise(final_command(), final, env, WALL_SECONDS)
            final_result = json.loads((MONITOR/'final-result.json').read_text())
            if (not base.clean(final_status) or json.loads((final/'supervisor-result.json').read_text()) != final_status or
                    final_result.get('status') != 'candidate_bytes_verified' or
                    final_result.get('reportSHA256') != base.sha(builder.OUTPUT/'report.json') or
                    final_result.get('verification') != report['verification'] or
                    type(final_result.get('cpuNice')) is not int or final_result['cpuNice'] < 15 or
                    final_result.get('ioClass') != 'idle'):
                raise ValueError('independent final byte/order check failed')
            if pins() != sources: raise ValueError('source pins changed during final recheck')
            if any(shutil.disk_usage(path).free < 36 * GIB for path in (ROOT, Path.home(), P)):
                raise ValueError('disk below final 36 GiB floor')
        except (OSError,ValueError,KeyError,TypeError) as error:
            reason = str(error)
        base.write_new(MONITOR/'result.json', {'status':'failed' if reason else 'candidate_data_only', 'reason':reason,
            'supervisorStatus':status, 'launchSHA256':base.sha(MONITOR/'launch.json'),
            'workerSHA256':base.sha(MONITOR/'worker-result.json') if (MONITOR/'worker-result.json').is_file() else None,
            'finalResultSHA256':base.sha(MONITOR/'final-result.json') if (MONITOR/'final-result.json').is_file() else None,
            'finalStatusSHA256':base.sha(MONITOR/'final-monitor/supervisor-result.json') if (MONITOR/'final-monitor/supervisor-result.json').is_file() else None,
            'scope':'CPU dataset candidate; no training, held-out or physical claim'})
        if reason: raise RuntimeError(reason)
        return report


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and bounded scheduling.')
