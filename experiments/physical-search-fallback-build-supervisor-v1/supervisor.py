#!/usr/bin/env python3
"""Disabled, low-priority CPU-only watchdog for an isolated fallback build."""
import fcntl
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
P=ROOT/'build/flex/sim/levels-v2/pitch82'
BUILD=P/'physical-search-fallback-build-v1'
MONITOR=P/'physical-search-fallback-build-cpu-monitor-v1'
LOCK=P/'.l4-matched.lock'
PREPARE=ROOT/'experiments/physical-search-fallback-v1/prepare.py'
TRIAL=ROOT/'experiments/physical-search-fallback-trial-v1/run.py'
NICE=Path('/usr/bin/nice')
IONICE=Path('/usr/bin/ionice')
WALL_SECONDS=900
GIB=1024**3


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


hidden=load('build_hidden',ROOT/'flex/tests/run-physical-hidden-trial.py')
guard=load('build_guard',ROOT/'experiments/sim-stop-supervisor/supervisor.py')


def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for part in iter(lambda:stream.read(1024*1024),b''):digest.update(part)
    return digest.hexdigest()


def write_new(path,value):
    with Path(path).open('x') as stream:json.dump(value,stream,indent=2,sort_keys=True);stream.write('\n')


def clean(status):
    return ('signal' in status and type(status.get('clientExit')) is int and status['clientExit']==0 and status['signal'] is None and
            status.get('timedOut') is False and status.get('remainingWorkersTerminated') is False and
            type(status.get('processGroup')) is int and status['processGroup']>0)


def sources():
    archive=P/'physical-handoff-hint-build-v3'
    paths=[Path(__file__),PREPARE,TRIAL,ROOT/'flex/tests/run-physical-hidden-trial.py',ROOT/'flex/tests/run-physical-rescan-trial.py',
           ROOT/'flex/tests/run-physical-hybrid-trial.py',ROOT/'experiments/sim-stop-supervisor/supervisor.py',
           ROOT/'experiments/sim-stop-supervisor/proxy.py',ROOT/'build/flex/control/compiler',Path(sys.executable).resolve(),NICE,IONICE,
           archive/'build.json',archive/'inputs/client',archive/'inputs/simulator']
    def fail(error):raise error
    for folder in (archive/'inputs/flex-source',archive/'inputs/build/flex/sim/library',archive/'original-source'):
        if not folder.is_dir():raise ValueError('archived source missing')
        for directory,dirs,files in os.walk(folder,followlinks=False,onerror=fail):
            for name in dirs+files:
                if (Path(directory)/name).is_symlink():raise ValueError('symlink in archived source')
            for name in files:
                path=Path(directory)/name
                if path.suffix!='.pyc' and '__pycache__' not in path.parts:
                    if not path.is_file():raise ValueError('invalid archived source')
                    paths.append(path)
    return {str(path):sha(path) for path in paths}


def command():
    code=('import importlib.util,json,sys;'
          's=importlib.util.spec_from_file_location("b",sys.argv[1]);'
          'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.worker()')
    return [str(NICE),'-n','15',str(IONICE),'-c','3',sys.executable,'-I','-c',code,str(Path(__file__).resolve())]


def worker():
    # Build and all heavyweight source verification remain inside the outer deadline.
    cpu_nice=os.getpriority(os.PRIO_PROCESS,0)
    io=subprocess.run([str(IONICE),'-p',str(os.getpid())],capture_output=True,text=True,timeout=5,check=True).stdout.strip()
    if cpu_nice<15 or io!='idle':raise RuntimeError('CPU or I/O priority not applied')
    before=sources();prepare=load('worker_search_prepare',PREPARE);report=prepare.build(BUILD)
    trial=load('worker_search_trial',TRIAL);verified=trial.check_build(BUILD)
    if report!=verified or sources()!=before:raise ValueError('build sources or receipt changed')
    write_new(MONITOR/'worker-result.json',{'status':'isolated_build_only','buildReceiptSHA256':sha(BUILD/'build.json'),
              'clientSHA256':sha(BUILD/'client'),'simulatorSHA256':sha(BUILD/'simulator'),'sourcePins':before,'cpuNice':cpu_nice,'ioClass':io,
              'scope':'CPU build consistency only; no actor, simulator run or hardware proof'})


def low_priority():
    current=os.getpriority(os.PRIO_PROCESS,0)
    if current<15:os.nice(15-current)
    subprocess.run([str(IONICE),'-c','3','-p',str(os.getpid())],env={'PATH':'/usr/bin:/bin'},check=True,capture_output=True,text=True,timeout=5)
    io=subprocess.run([str(IONICE),'-p',str(os.getpid())],env={'PATH':'/usr/bin:/bin'},check=True,capture_output=True,text=True,timeout=5).stdout.strip()
    priority=os.getpriority(os.PRIO_PROCESS,0)
    if priority<15 or io!='idle':raise RuntimeError('supervisor priority not applied')
    return {'cpuNice':priority,'ioClass':io}


def launch():
    guard.require_dedicated_process()
    for tool in (NICE,IONICE):
        if not tool.is_file() or not os.access(tool,os.X_OK):raise ValueError('low-priority tool unavailable')
    priority=low_priority()
    if any(shutil.disk_usage(path).free<36*GIB for path in (ROOT,Path.home(),P)):raise ValueError('free disk below 36 GiB')
    for path in (BUILD,MONITOR):
        if path.exists() or path.is_symlink():raise FileExistsError('output exists; preserve evidence: '+str(path))
    # Open the existing shared lock; never create it or touch a running experiment.
    with LOCK.open('r+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        # Recheck after taking the lock, before creating the monitor output.
        for path in (BUILD,MONITOR):
            if path.exists() or path.is_symlink():raise FileExistsError('output exists; preserve evidence: '+str(path))
        if any(shutil.disk_usage(path).free<36*GIB for path in (ROOT,Path.home(),P)):raise ValueError('free disk below 36 GiB')
        pins=sources();env={'PATH':'/usr/bin:/bin','HOME':str(Path.home()),'SDL_VIDEODRIVER':'offscreen','LD_LIBRARY_PATH':str(ROOT/'build/flex/rocm-runtime')}
        MONITOR.mkdir();invocation={'command':command(),'environment':env,'wallSeconds':WALL_SECONDS,'build':str(BUILD),'sourcePins':pins,'supervisorPriority':priority,
                                  'scope':'local recorded launch intent; advisory lock; CPU/I/O low priority'}
        write_new(MONITOR/'launch.json',invocation)
        try:status=hidden.supervise(command(),MONITOR,env,WALL_SECONDS)
        except BaseException as error:
            write_new(MONITOR/'result.json',{'status':'failed','reason':str(error),'scope':'supervisor failed; partial evidence retained'})
            raise
        failure=None
        try:
            if not clean(status) or json.loads((MONITOR/'supervisor-result.json').read_text())!=status:raise ValueError('unclean or inconsistent supervisor status')
            result=json.loads((MONITOR/'worker-result.json').read_text());report=json.loads((BUILD/'build.json').read_text())
            if sources()!=pins or result.get('sourcePins')!=pins:raise ValueError('pinned build inputs changed')
            if (result.get('status')!='isolated_build_only' or type(result.get('cpuNice')) is not int or result['cpuNice']<15 or result.get('ioClass')!='idle' or report.get('schema')!='puppybot.physical-search-fallback-build.v1' or
                    result.get('buildReceiptSHA256')!=sha(BUILD/'build.json') or result.get('clientSHA256')!=sha(BUILD/'client') or
                    result.get('simulatorSHA256')!=sha(BUILD/'simulator') or result.get('clientSHA256')!=report.get('clientSHA256') or
                    result.get('simulatorSHA256')!=report.get('simulatorSHA256')):raise ValueError('build receipt or binaries differ')
            if any(shutil.disk_usage(path).free<32*GIB for path in (ROOT,Path.home(),P)):raise ValueError('free disk below final 32 GiB floor')
        except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError) as error:failure=str(error)
        write_new(MONITOR/'result.json',{'status':'failed' if failure else 'isolated_build_only','reason':failure,
                  'supervisorStatus':status,'launchSHA256':sha(MONITOR/'launch.json'),
                  'workerSHA256':sha(MONITOR/'worker-result.json') if (MONITOR/'worker-result.json').is_file() else None,
                  'scope':'CPU-only build consistency; no actor, rendered simulator or hardware proof; disk checked at start and end only'})
        return 1 if failure else 0


if __name__=='__main__':raise SystemExit('Disabled pending independent review and scheduling; no build authorized.')
