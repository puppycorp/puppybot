#!/usr/bin/env python3
"""Disabled, resource-supervised paired simulator pilot staging."""
import fcntl
import hashlib
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
LOCK=ROOT/'build/flex/sim/levels-v2/pitch82/.l4-matched.lock'
ASSET=ROOT/'build/flex/sim/puppybot.bin'
CONFIG=ROOT/'puppybot.json'
RUNTIME=ROOT/'build/flex/rocm-runtime/libamdhip64.so'


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


supervisor=load('pilot_supervisor',HERE/'supervisor.py')
audit=load('pilot_audit',HERE/'audit.py')
prepare=load('pilot_build',HERE/'prepare.py')
telemetry=load('pilot_gpu_monitor',ROOT/'flex/tests/monitored-visual-v4-smoke.py')


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def pins(paths):return {str(p):digest(p) for p in paths}


def free_disk(path):
    # Output may be on a different filesystem from the workspace or home.
    return min(shutil.disk_usage(p).free for p in (Path(path),ROOT,Path.home()))


def required(build,simulator,model,case,environment):
    model=Path(model)
    sources=[HERE/'launcher.py',HERE/'supervisor.py',HERE/'proxy.py',HERE/'audit.py',HERE/'prepare.py',
             ROOT/'experiments/physical-failure-report/prepare.py',ROOT/'flex/tests/run-physical-hidden-trial.py',
             ROOT/'flex/tests/run-physical-rescan-trial.py',ROOT/'flex/tests/run-physical-hybrid-trial.py',
             ROOT/'datasets/visual-control/chase-v1/levels/supervise-selection.py',ROOT/'flex/tests/monitored-visual-v4-smoke.py',Path(sys.executable).resolve(),
             Path(build)/'build.json',Path(build)/'client',prepare.failure.COMPILER,Path(simulator),Path(case),Path(environment),ASSET,CONFIG,RUNTIME,
             model/'policy',model/'weights.bin',model/'receipt.json']
    kernels=sorted((model/'kernels').iterdir())
    if not kernels or any(not p.is_file() for p in kernels):raise ValueError('invalid model kernels')
    trees=[prepare.failure.ARCHIVE,Path(build)/'flex']
    if any(not tree.is_dir() for tree in trees):raise ValueError('missing source archive')
    archived=[p for tree in trees for p in sorted(tree.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
    result=sources+kernels+archived
    if any(not p.is_file() for p in result):raise ValueError('missing pilot input')
    return result


def check_build(build):
    report=json.loads((Path(build)/'build.json').read_text())
    if report.get('schema')!='puppybot.sim-stop-client-build.v1' or report.get('clientSHA256')!=digest(Path(build)/'client'):raise ValueError('invalid copied client build')
    if (report.get('compilerSHA256')!=digest(prepare.failure.COMPILER) or report.get('archiveSource')!=prepare.failure.hashes(prepare.failure.ARCHIVE)
            or report.get('clientSource')!=prepare.failure.hashes(Path(build)/'flex')):raise ValueError('copied client source or compiler changed')
    original=(prepare.failure.ARCHIVE/'control/physical-client.flex').read_text()
    expected=prepare.patched_text(original)
    if (Path(build)/'flex/control/physical-client.flex').read_text()!=expected:raise ValueError('copied client transform differs')
    before=report['archiveSource'];after=report['clientSource']
    if before.keys()!=after.keys() or any(before[k]!=after[k] for k in before if k!='control/physical-client.flex'):raise ValueError('unexpected copied source changes')


def monitor_arm(output,build,simulator,model,case,environment,fault,log):
    code=('import importlib.util,json,sys;'
          's=importlib.util.spec_from_file_location("m",sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);'
          'm.launch(*json.loads(sys.argv[2]),io_seconds=5,stop_seconds=2,wall_seconds=60,fault=sys.argv[3])')
    env={'PATH':'/usr/bin:/bin','HOME':str(Path.home()),'SDL_VIDEODRIVER':'offscreen','LD_LIBRARY_PATH':str(ROOT/'build/flex/rocm-runtime'),
         'PUPPYBOT_PHYSICAL_NAV_LIMIT':'1','PUPPYBOT_PHYSICAL_POLL_LIMIT':'1'}
    args=[str(output),str(Path(build)/'client'),str(simulator),str(model),str(case),str(environment),env]
    command=[sys.executable,'-I','-c',code,str(HERE/'supervisor.py'),json.dumps(args),fault]
    with (output.parent/(output.name+'-worker.log')).open('x') as worker_log:
        process=subprocess.Popen(command,cwd=ROOT,stdout=worker_log,stderr=subprocess.STDOUT)
        try:fd=os.pidfd_open(process.pid)
        except OSError:
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=8)
                except subprocess.TimeoutExpired:process.kill();process.wait()
            raise
        deadline=time.monotonic()+70;reason=None
        try:
            while process.poll() is None:
                try:
                    if telemetry.sample(log,'arm-'+fault)['freeBytes']<2*telemetry.GIB:reason='free VRAM below 2 GiB'
                    if free_disk(output.parent)<34*telemetry.GIB:reason=reason or 'free disk below 34 GiB'
                except (OSError,RuntimeError,ValueError) as error:reason=str(error)
                if time.monotonic()>=deadline:reason=reason or 'arm deadline'
                if reason:break
                time.sleep(1)
        finally:
            try:
                if process.poll() is None:
                    try:signal.pidfd_send_signal(fd,signal.SIGTERM)
                    except ProcessLookupError:pass
                    try:process.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        try:signal.pidfd_send_signal(fd,signal.SIGKILL)
                        except ProcessLookupError:pass
                        process.wait()
            finally:os.close(fd)
        if reason or process.returncode:raise RuntimeError(reason or 'arm failed; partial evidence retained')


def worker(output,build,simulator,model,case,environment):
    output=Path(output);paths=required(build,simulator,model,case,environment);check_build(build);before=pins(paths)
    (output/'inputs.json').write_text(json.dumps({'schema':'puppybot.sim-stop-pilot.v1','files':before,'fault':'after-reset',
        'control':'none','scope':'saved intent and local peer evidence; no physical stop or delivery'},indent=2,sort_keys=True)+'\n')
    if free_disk(output)<36*telemetry.GIB:raise ValueError('free disk below 36 GiB')
    with (output/'telemetry.jsonl').open('x') as log:
        telemetry.baseline(log)
        for name,fault in (('control','none'),('fault','after-reset')):
            if pins(paths)!=before:raise ValueError('pilot inputs changed')
            if free_disk(output)<34*telemetry.GIB:raise ValueError('free disk below 34 GiB')
            monitor_arm(output/name,build,simulator,model,case,environment,fault,log)
        if telemetry.sample(log,'final')['freeBytes']<2*telemetry.GIB:raise RuntimeError('low final VRAM')
        if free_disk(output)<34*telemetry.GIB:raise RuntimeError('low final disk space')
    if pins(paths)!=before:raise ValueError('pilot inputs changed')
    report=audit.audit(output/'control',output/'fault')
    (output/'audit.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    return report


def launch(output,build,simulator,model,case,environment):
    """Dedicated process only; caller must separately schedule the GPU."""
    supervisor.require_dedicated_process();output=Path(output).absolute()
    build,simulator,model,case,environment=(Path(p).absolute() for p in (build,simulator,model,case,environment))
    if output.exists() or output.is_symlink():raise FileExistsError('output exists')
    if free_disk(output.parent)<36*telemetry.GIB:raise ValueError('free disk below 36 GiB')
    paths=required(build,simulator,model,case,environment);check_build(build);before=pins(paths)
    with LOCK.open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        output.mkdir();outer=output/'outer-monitor';outer.mkdir()
        code=('import importlib.util,sys;'
              's=importlib.util.spec_from_file_location("m",sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.worker(*sys.argv[2:])')
        command=[sys.executable,'-I','-c',code,str(HERE/'launcher.py'),str(output),*map(str,(build,simulator,model,case,environment))]
        env={'PATH':'/usr/bin:/bin','HOME':str(Path.home()),'SDL_VIDEODRIVER':'offscreen','LD_LIBRARY_PATH':str(ROOT/'build/flex/rocm-runtime')}
        (output/'launch.json').write_text(json.dumps({'command':command,'files':before,'wallSeconds':190},indent=2,sort_keys=True)+'\n')
        status=supervisor.hidden.supervise(command,outer,env,190)
        if status.get('clientExit')!=0 or status.get('timedOut') is not False or status.get('signal') is not None or status.get('remainingWorkersTerminated') is not False or pins(paths)!=before:raise RuntimeError('pilot incomplete or inputs changed; evidence retained')
        return json.loads((output/'audit.json').read_text())


if __name__=='__main__':raise SystemExit('Disabled pending independent review and GPU scheduling; no pilot authorized.')
