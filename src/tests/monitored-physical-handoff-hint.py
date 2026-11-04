#!/usr/bin/env python3
"""Disabled GPU-resource and descendant monitor for the handoff diagnostic."""
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
SUPERVISOR=ROOT/'flex/tests/supervise-physical-handoff-hint.py'
OUTER_SECONDS=1950
WORKER_SECONDS=1840


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


telemetry=load('gpu_telemetry',ROOT/'flex/tests/monitored-visual-v4-smoke.py')
handoff=load('handoff_supervisor',SUPERVISOR)


def require_disk(path):
    if shutil.disk_usage(path).free<12*telemetry.GIB:raise RuntimeError('free disk below 12 GiB')


def worker_command(output):
    code=('import importlib.util,sys;'
          's=importlib.util.spec_from_file_location("h",sys.argv[1]);'
          'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.launch(sys.argv[2],sys.argv[3])')
    return [sys.executable,'-I','-c',code,str(SUPERVISOR),str(output/'trial'),str(output/'process-monitor')]


def _monitor_worker(output):
    output=Path(output)
    with (output/'telemetry.jsonl').open('x') as log:
        require_disk(output);telemetry.baseline(log);require_disk(output)
        with (output/'handoff-worker.log').open('x') as child_log:
            process=subprocess.Popen(worker_command(output),cwd=ROOT,stdout=child_log,stderr=subprocess.STDOUT)
            pidfd=os.pidfd_open(process.pid);deadline=time.monotonic()+WORKER_SECONDS;reason=None
            try:
                while process.poll() is None:
                    try:
                        row=telemetry.sample(log,'handoff')
                        if row['freeBytes']<2*telemetry.GIB:reason='free VRAM below 2 GiB'
                    except RuntimeError as error:reason=str(error)
                    if time.monotonic()>=deadline:reason=reason or 'handoff worker deadline exceeded'
                    if reason:break
                    time.sleep(1)
            finally:
                try:
                    if process.poll() is None:
                        try:signal.pidfd_send_signal(pidfd,signal.SIGTERM)
                        except ProcessLookupError:pass
                        try:process.wait(timeout=15)
                        except subprocess.TimeoutExpired:
                            try:signal.pidfd_send_signal(pidfd,signal.SIGKILL)
                            except ProcessLookupError:pass
                            process.wait()
                finally:os.close(pidfd)
            if reason:raise RuntimeError(reason)
            if process.returncode!=0:raise RuntimeError(f'handoff worker exited {process.returncode}')
            if telemetry.sample(log,'after-handoff')['freeBytes']<2*telemetry.GIB:raise RuntimeError('free VRAM below 2 GiB after handoff')


def monitor_worker(output):
    try:_monitor_worker(output)
    except BaseException as error:
        (Path(output)/'gpu-monitor-result.json').write_text(json.dumps({'status':'failed','reason':str(error)},indent=2)+'\n');raise
    (Path(output)/'gpu-monitor-result.json').write_text(json.dumps({'status':'completed_diagnostic'},indent=2)+'\n')


def launch(output):
    """Use only in a dedicated standalone process: it becomes a subreaper."""
    output=Path(output).absolute()
    if output.exists() or output.is_symlink():raise ValueError('output exists; preserve evidence')
    require_disk(output.parent);handoff.runner.check()
    paths=[Path(__file__),SUPERVISOR,ROOT/'flex/tests/monitored-visual-v4-smoke.py',ROOT/'flex/tests/run-physical-hidden-trial.py',Path(sys.executable).resolve()]
    pins={str(path):handoff.sha(path) for path in paths};output.mkdir(parents=False,exist_ok=False)
    outer=output/'outer-monitor';outer.mkdir()
    code=('import importlib.util,sys;'
          's=importlib.util.spec_from_file_location("monitored",sys.argv[1]);'
          'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.monitor_worker(sys.argv[2])')
    command=[sys.executable,'-I','-c',code,str(Path(__file__).resolve()),str(output)]
    env={'PATH':'/usr/bin:/bin','HOME':str(Path.home()),'SDL_VIDEODRIVER':'offscreen','LD_LIBRARY_PATH':str(ROOT/'build/flex/rocm-runtime')}
    (output/'launch.json').write_text(json.dumps({'command':command,'environment':env,'files':pins,'wallSeconds':OUTER_SECONDS},indent=2)+'\n')
    status=handoff.runner.hidden.supervise(command,outer,env,OUTER_SECONDS)
    if any(handoff.sha(Path(path))!=digest for path,digest in pins.items()):raise RuntimeError('GPU monitor inputs changed')
    if status.get('clientExit')!=0 or status.get('timedOut') is not False or status.get('signal') is not None or status.get('remainingWorkersTerminated') is not False:raise RuntimeError('GPU-monitored handoff failed; partial evidence retained')
    result=json.loads((output/'gpu-monitor-result.json').read_text());report=json.loads((output/'process-monitor/result.json').read_text())
    if result.get('status')!='completed_diagnostic' or report.get('status')!='diagnostic_only':raise RuntimeError('GPU-monitored evidence incomplete')
    return report


if __name__=='__main__':raise SystemExit('Disabled pending independent review and a scheduling decision; no GPU launch authorized.')
