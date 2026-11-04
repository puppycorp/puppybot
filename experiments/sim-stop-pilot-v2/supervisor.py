#!/usr/bin/env python3
"""Disabled standalone simulator-only supervisor for the experimental proxy.

It must run as a dedicated process: the outer subreaper cleans its children.
The client and simulator remain separate children. No physical stop follows
from a simulated acknowledgment, process exit or a missing report.
"""
import importlib.util
import json
import os
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


proxy=load('sim_stop_proxy',HERE/'proxy.py')
hidden=load('physical_cpu_supervisor',ROOT/'flex/tests/run-physical-hidden-trial.py')


def clean_env(env):
    clean={'PATH':'/usr/bin:/bin','HOME':str(Path.home()),'SDL_VIDEODRIVER':'offscreen',
           'LD_LIBRARY_PATH':str(ROOT/'build/flex/rocm-runtime')}
    allowed=('PUPPYBOT_PHYSICAL_NAV_LIMIT','PUPPYBOT_PHYSICAL_POLL_LIMIT',
             'PUPPY_TEST_MODE','PUPPY_TEST_COMMANDS','PUPPY_TEST_ACTOR','PUPPY_TEST_VISIBLE','PUPPY_TEST_NAN','PUPPY_TEST_CHILD_PID','PUPPY_TEST_HANDSHAKE_DELAY')
    for key in allowed:
        if key in env:
            if not isinstance(env[key],str):raise ValueError('invalid diagnostic environment')
            clean[key]=env[key]
    return clean


def require_dedicated_process():
    # The inherited subreaper waits for any child, so only a single-threaded
    # process with no existing children may own it. Check before any output.
    tasks=list(Path('/proc/self/task').iterdir())
    if len(tasks)!=1 or threading.active_count()!=1:
        raise RuntimeError('supervisor requires a dedicated single-thread process')
    if (tasks[0]/'children').read_text().strip():
        raise RuntimeError('supervisor requires a process without existing children')


def terminate(process,seconds=1):
    if process is None:return None
    if process.poll() is None:
        try:os.killpg(process.pid,signal.SIGTERM)
        except ProcessLookupError:pass
        try:process.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            process.wait()
    return process.returncode


def worker(output,client,simulator,model,case,environment,env,io_seconds,stop_seconds,wall_seconds,fault,startup_seconds):
    output=Path(output);run=output/'client';signals=[];client_proc=sim_proc=None
    previous={sig:signal.signal(sig,lambda number,_frame:signals.append(number)) for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP)}
    client_end=upstream=peer=sim_end=None;result=None;started=time.monotonic();journal=None
    try:
        if fault not in ('none','after-reset'):raise ValueError('invalid fixed fault')
        journal=(output/'protocol.bin').open('xb',buffering=0)
        def record(kind,data):
            pending=memoryview(struct.pack('<BQ',kind,len(data))+data)
            while pending:
                written=journal.write(pending)
                if not written:raise OSError('protocol journal short write')
                pending=pending[written:]
            os.fsync(journal.fileno())
        def after_reply(sequence,row):
            if fault!='after-reset' or sequence!=1:return False
            if row['owner']!=0 or row['ack']!=0:raise ValueError('fault boundary not reset')
            fd=os.pidfd_open(client_proc.pid)
            try:signal.pidfd_send_signal(fd,signal.SIGKILL)
            finally:os.close(fd)
            client_proc.wait(timeout=1);record(6,b'client-killed-after-reset');return True
        client_end,upstream=socket.socketpair();peer,sim_end=socket.socketpair()
        client_end.setblocking(False)
        client_env=dict(env,PUPPYBOT_SIM_SUPERVISOR_FD=str(client_end.fileno()),PUPPYBOT_SIM_FAILURE_REPORT='1')
        with (output/'client-process.log').open('x') as client_log,(output/'simulator-process.log').open('x') as sim_log:
            if not signals:
                client_proc=subprocess.Popen([str(client),str(simulator),str(model),str(case),str(environment),str(run),'--allow-zero-contact'],
                    cwd=ROOT,env=client_env,stdout=client_log,stderr=subprocess.STDOUT,pass_fds=(client_end.fileno(),),start_new_session=True)
            client_end.close();client_end=None
            deadline=started+min(5,wall_seconds/3)
            while client_proc is not None and not run.is_dir() and client_proc.poll() is None and not signals and time.monotonic()<deadline:time.sleep(.01)
            if client_proc is None or signals:raise RuntimeError('interrupted before client ready')
            if not run.is_dir():raise RuntimeError('client did not create output before deadline')
            sim_argv=[str(simulator),'--hidden','--case-file',str(case),'--environment',str(environment),'--steps','1000000',
                      '--bind','127.0.0.1:0','--agent-fd',str(sim_end.fileno()),'--agent-physical','--camera-pitch','82',
                      '--localization','wheel-drift','--no-visual-odometry','--record',str(run/'trace.jsonl')]
            if not signals:sim_proc=subprocess.Popen(sim_argv,cwd=ROOT,env=env,stdout=sim_log,stderr=subprocess.STDOUT,
                                                     pass_fds=(sim_end.fileno(),),start_new_session=True)
            sim_end.close();sim_end=None
            if sim_proc is None:raise RuntimeError('interrupted before simulator start')
            remaining=wall_seconds-(time.monotonic()-started)
            if remaining<=0:raise TimeoutError('worker deadline before protocol')
            result=proxy.session(upstream,peer,io_seconds=io_seconds,stop_seconds=stop_seconds,wall_seconds=remaining,startup_seconds=startup_seconds,interrupted=lambda:bool(signals),record=record,after_reply=after_reply)
    except (OSError,ValueError,RuntimeError,TimeoutError) as error:
        result={'status':'failed','reason':str(error),'stopAttempted':False,'stopAcknowledged':False,'stopCommandSource':None,
                'peerReportedZeroDrive':False,'delivery':'unverified','physicalStop':'unverified','lastCompletedSequence':0}
    finally:
        if journal is not None:journal.close()
        for channel in (client_end,upstream,peer,sim_end):
            if channel is not None:channel.close()
        # Allow normal exits first; otherwise terminate only the worker-owned
        # groups. The outer subreaper handles any escaped descendants.
        for process in (client_proc,sim_proc):
            if process is not None and process.poll() is None:
                try:process.wait(timeout=1)
                except subprocess.TimeoutExpired:pass
        client_exit=terminate(client_proc);simulator_exit=terminate(sim_proc)
        if result is not None:
            result.update(clientExit=client_exit,simulatorExit=simulator_exit,signal=signals[0] if signals else None,
                          scope='simulated peer reply only; direct child status, not physical stop or delivery')
            with (output/'session.json').open('x') as stream:json.dump(result,stream,sort_keys=True,indent=2);stream.write('\n')
        for sig,handler in previous.items():signal.signal(sig,handler)
    return result


def launch(output,client,simulator,model,case,environment,env,*,io_seconds=5,stop_seconds=2,wall_seconds=30,fault='none',startup_seconds=None):
    """Standalone only, with a second subreaper/process-group wall watchdog."""
    output=Path(output).absolute()
    if output.exists() or output.is_symlink():raise FileExistsError('output exists; retain it')
    if startup_seconds is None:startup_seconds=io_seconds
    if not 0<wall_seconds<=60 or not 0<io_seconds<=30 or not 0<stop_seconds<=5 or not 0<startup_seconds<=30 or fault not in ('none','after-reset'):raise ValueError('invalid wall, I/O limit or fault')
    require_dedicated_process()
    env=clean_env(env);paths=[Path(p).absolute() for p in (client,simulator,model,case,environment)]
    if not all(p.exists() for p in paths):raise ValueError('missing simulator diagnostic input')
    output.mkdir(parents=False,exist_ok=False);outer=output/'outer-monitor';outer.mkdir()
    code=('import importlib.util,json,sys;'
          's=importlib.util.spec_from_file_location("guard",sys.argv[1]);'
          'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);'
          'm.worker(sys.argv[2],*sys.argv[3:8],json.loads(sys.argv[8]),*map(float,sys.argv[9:12]),sys.argv[12],float(sys.argv[13]))')
    command=[sys.executable,'-I','-c',code,str(Path(__file__).resolve()),str(output),*map(str,paths),json.dumps(env,sort_keys=True),str(io_seconds),str(stop_seconds),str(wall_seconds),fault,str(startup_seconds)]
    (output/'launch.json').write_text(json.dumps({'command':command,'outerSeconds':wall_seconds+6,'scope':'simulator-only diagnostic; input intent, not attestation'},indent=2)+'\n')
    status=hidden.supervise(command,outer,env,wall_seconds+6)
    if status.get('clientExit')!=0 or status.get('timedOut') is not False or status.get('signal') is not None or status.get('remainingWorkersTerminated') is not False:
        raise RuntimeError('outer supervisor failed or cleaned surviving workers; evidence retained')
    return json.loads((output/'session.json').read_text())


if __name__=='__main__':raise SystemExit('Disabled: simulator-only diagnostic requires independent review and scheduling.')
