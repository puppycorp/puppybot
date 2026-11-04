#!/usr/bin/env python3
"""Disabled outer resource monitor for the three-arm simulator diagnostic."""
import importlib.util
import hashlib
import json
import math
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
TRIAL=ROOT/'experiments/physical-search-fallback-trial-v1'
OUTER_SECONDS=3000
WORKER_SECONDS=2700
FINAL_SECONDS=900
GIB=1024**3


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


runner=load('monitored_search_runner',TRIAL/'run.py')
telemetry=load('monitored_search_telemetry',ROOT/'flex/tests/monitored-visual-v4-smoke.py')
guard=load('monitored_search_guard',ROOT/'experiments/sim-stop-supervisor/supervisor.py')


def write_new(path,value):
    with Path(path).open('x') as stream:json.dump(value,stream,indent=2,sort_keys=True);stream.write('\n')


def clean(status):
    return ('signal' in status and type(status.get('clientExit')) is int and status['clientExit']==0 and status.get('signal') is None and status.get('timedOut') is False and status.get('remainingWorkersTerminated') is False and type(status.get('processGroup')) is int and status['processGroup']>0)


def disk_paths(output):return {'workspace':str(ROOT),'home':str(Path.home()),'output':str(Path(output))}


def sample_disk(stream,phase,paths,gib):
    values={key:shutil.disk_usage(path).free for key,path in paths.items()}
    row={'phase':phase,'monotonicSeconds':time.monotonic(),'freeBytes':values}
    stream.write(json.dumps(row,sort_keys=True)+'\n');stream.flush()
    if any(type(value) is not int or value<gib*GIB for value in values.values()):raise RuntimeError(f'disk unavailable or below {gib} GiB')


def baseline(stream):
    first=None;busy=0
    while True:
        row=telemetry.sample(stream,'baseline')
        if first is None:first=row['monotonicSeconds']
        if row['freeBytes']<6*GIB:raise RuntimeError('baseline free VRAM below 6 GiB')
        busy=busy+1 if row['busyPercent']>10 else 0
        if busy>=5:raise RuntimeError('baseline GPU busy')
        remaining=30-(row['monotonicSeconds']-first)
        if remaining<=0:return
        time.sleep(min(1,remaining))


def verify_logs(output):
    def read(name):
        rows=[json.loads(line) for line in (Path(output)/name).read_text().splitlines()];previous=-1.0
        for row in rows:
            tick=row.get('monotonicSeconds')
            if type(tick) not in (int,float) or not math.isfinite(tick) or tick<=previous:raise ValueError('invalid telemetry time')
            previous=tick
        return rows
    gpu=read('telemetry.jsonl');disk=read('disk.jsonl');base=[r for r in gpu if r.get('phase')=='baseline'];active=[r for r in gpu if r.get('phase')=='trial']
    if len(base)<2 or not active or [r.get('phase') for r in gpu]!=['baseline']*len(base)+['trial']*len(active)+['after-trial'] or base[-1]['monotonicSeconds']-base[0]['monotonicSeconds']<30 or any(b['monotonicSeconds']-a['monotonicSeconds']>2.5 for a,b in zip(gpu,gpu[1:])):raise ValueError('GPU sampling incomplete')
    busy=0
    for row in gpu:
        if any(type(row.get(k)) is not int for k in ('busyPercent','totalBytes','usedBytes','freeBytes')) or not 0<=row['busyPercent']<=100 or row['totalBytes']<=0 or not 0<=row['usedBytes']<=row['totalBytes'] or row['freeBytes']!=row['totalBytes']-row['usedBytes'] or row['freeBytes']<(6 if row['phase']=='baseline' else 2)*GIB:raise ValueError('invalid GPU sample')
        if row['phase']=='baseline':
            busy=busy+1 if row['busyPercent']>10 else 0
            if busy>=5:raise ValueError('GPU baseline busy')
    if [r.get('phase') for r in disk]!=['pre-baseline','post-baseline']+['trial']*len(active)+['after-trial'] or disk[0]['monotonicSeconds']>base[0]['monotonicSeconds'] or not base[-1]['monotonicSeconds']<=disk[1]['monotonicSeconds']<=active[0]['monotonicSeconds'] or disk[-1]['monotonicSeconds']<gpu[-1]['monotonicSeconds']:raise ValueError('disk sampling incomplete')
    for row in disk:
        values=row.get('freeBytes');floor=36 if row['phase'] in ('pre-baseline','post-baseline') else 34
        if not isinstance(values,dict) or set(values)!={'workspace','home','output'} or any(type(v) is not int or v<floor*GIB for v in values.values()):raise ValueError('invalid disk sample')
    for i,row in enumerate(active):
        if not row['monotonicSeconds']<=disk[i+2]['monotonicSeconds']<=gpu[len(base)+i+1]['monotonicSeconds']:raise ValueError('disk samples out of order')


def base_env():
    return {'PATH':'/usr/bin:/bin','HOME':str(Path.home()),'SDL_VIDEODRIVER':'offscreen','LD_LIBRARY_PATH':str(ROOT/'build/flex/rocm-runtime')}


def worker_env():return dict(base_env(),PUPPYBOT_SEARCH_TRIAL_REVIEWED_WORKER='1')


def worker_command(output,build,case,environment,model):
    code=('import importlib.util,sys;'
          's=importlib.util.spec_from_file_location("search_monitor",sys.argv[1]);'
          'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.trial_worker(*sys.argv[2:])')
    return [sys.executable,'-I','-c',code,str(Path(__file__).resolve()),str(output),str(build),str(case),str(environment),str(model)]


def file_sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def inventory(root):
    root=Path(root);result={}
    def failed(error):raise error
    for directory,dirs,files in os.walk(root,followlinks=False,onerror=failed):
        for name in dirs+files:
            path=Path(directory)/name
            if path.is_symlink():raise ValueError('symlink in trial evidence')
        for name in files:
            path=Path(directory)/name
            if not path.is_file():raise ValueError('non-file trial evidence')
            result[str(path.relative_to(root))]=file_sha(path)
    if not result:raise ValueError('empty trial evidence')
    return result


def trial_worker(output,build,case,environment,model):
    output=Path(output);trial=output/'trial'
    runner.launch(trial,build,case,environment,model)
    saved=json.loads((trial/'audit.json').read_text());auditor=load('independent_search_audit',TRIAL/'audit.py');fresh=auditor.audit(trial)
    if saved!=fresh or saved.get('status')!='diagnostic_only':raise ValueError('saved audit differs from independent rerun')
    runner.check_manifest(trial,json.loads((trial/'inputs.json').read_text()))
    write_new(output/'worker-result.json',{'status':'diagnostic_only','auditSHA256':runner.sha(trial/'audit.json'),
              'inputsSHA256':runner.sha(trial/'inputs.json'),'inventory':inventory(trial),'comparisonEligible':saved.get('comparisonEligible'),
              'censorReason':saved.get('censorReason'),'scope':'saved-output comparison only; local records are not execution attestation'})


def _worker(output,build,case,environment,model):
    output=Path(output);paths=disk_paths(output)
    with (output/'telemetry.jsonl').open('x') as gpu,(output/'disk.jsonl').open('x') as disk:
        sample_disk(disk,'pre-baseline',paths,36);baseline(gpu);sample_disk(disk,'post-baseline',paths,36)
        with (output/'worker.log').open('x') as log:
            env=worker_env()
            command=worker_command(output,build,case,environment,model)
            write_new(output/'worker-launch.json',{'command':command,'environment':env,'wallSeconds':WORKER_SECONDS})
            process=subprocess.Popen(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
            # The enclosing subreaper owns cleanup even if pidfd_open fails.
            pidfd=os.pidfd_open(process.pid);deadline=time.monotonic()+WORKER_SECONDS;reason=None
            try:
                while True:
                    try:
                        row=telemetry.sample(gpu,'trial');sample_disk(disk,'trial',paths,34)
                        if row['freeBytes']<2*GIB:reason='free VRAM below 2 GiB'
                    except (OSError,RuntimeError,ValueError) as error:reason=str(error)
                    if time.monotonic()>=deadline:reason=reason or 'trial deadline exceeded'
                    if reason or process.poll() is not None:break
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
            if process.returncode!=0:raise RuntimeError(f'trial worker exited {process.returncode}')
            if telemetry.sample(gpu,'after-trial')['freeBytes']<2*GIB:raise RuntimeError('free VRAM below 2 GiB after trial')
            sample_disk(disk,'after-trial',paths,34)


def monitor_worker(output,build,case,environment,model):
    try:_worker(output,build,case,environment,model)
    except BaseException as error:
        write_new(Path(output)/'monitor-result.json',{'status':'failed','reason':str(error)});raise
    write_new(Path(output)/'monitor-result.json',{'status':'passed'})


def source_pins():
    paths=(Path(__file__),TRIAL/'run.py',TRIAL/'audit.py',ROOT/'experiments/physical-search-fallback-v1/prepare.py',
           ROOT/'flex/tests/monitored-visual-v4-smoke.py',ROOT/'flex/tests/run-physical-hidden-trial.py',ROOT/'flex/tests/run-physical-rescan-trial.py',
           ROOT/'flex/tests/run-physical-hybrid-trial.py',ROOT/'experiments/sim-stop-supervisor/supervisor.py',ROOT/'experiments/sim-stop-supervisor/proxy.py',
           ROOT/'flex/exploration/manipulation_audit.py',ROOT/'flex/tests/sim-cases.py',ROOT/'flex/tests/sim.py',Path(sys.executable).resolve())
    return {str(path):runner.sha(path) for path in paths}



def final_command(output,worker_hash):
    code=('import importlib.util,sys;'
          's=importlib.util.spec_from_file_location("search_monitor",sys.argv[1]);'
          'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.final_worker(*sys.argv[2:])')
    return [sys.executable,'-I','-c',code,str(Path(__file__).resolve()),str(output),worker_hash]


def final_worker(output,worker_hash):
    output=Path(output);trial=output/'trial';receipt=output/'worker-result.json'
    if runner.sha(receipt)!=worker_hash:raise ValueError('worker receipt changed')
    worker=json.loads(receipt.read_text());expected=worker['inventory']
    if not isinstance(expected,dict) or inventory(trial)!=expected:raise ValueError('trial evidence changed before final audit')
    saved=json.loads((trial/'audit.json').read_text());auditor=load('final_search_audit',TRIAL/'audit.py')
    if auditor.audit(trial)!=saved:raise ValueError('final saved audit differs')
    if inventory(trial)!=expected or runner.sha(receipt)!=worker_hash:raise ValueError('trial evidence changed during final audit')
    write_new(output/'final-result.json',{'status':'verified_diagnostic','workerSHA256':worker_hash,'auditSHA256':worker['auditSHA256']})


def launch(output,build,case,environment,model):
    """Only a dedicated, separately scheduled process can own this subreaper."""
    guard.require_dedicated_process();output,build,case,environment,model=(Path(p).absolute() for p in (output,build,case,environment,model))
    if output.exists() or output.is_symlink():raise ValueError('output exists; preserve evidence')
    if any(shutil.disk_usage(path).free<36*GIB for path in disk_paths(output.parent).values()):raise ValueError('insufficient disk before output creation')
    pins=source_pins();output.mkdir();outer=output/'outer-monitor';outer.mkdir()
    code=('import importlib.util,sys;'
          's=importlib.util.spec_from_file_location("search_monitor",sys.argv[1]);'
          'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.monitor_worker(*sys.argv[2:])')
    command=[sys.executable,'-I','-c',code,str(Path(__file__).resolve()),str(output),str(build),str(case),str(environment),str(model)]
    env=base_env()
    write_new(output/'launch.json',{'command':command,'environment':env,'sourcePins':pins,'wallSeconds':OUTER_SECONDS,
              'paths':{'output':str(output),'build':str(build),'case':str(case),'environment':str(environment),'model':str(model)}})
    status=runner.hidden.supervise(command,outer,env,OUTER_SECONDS)
    if not clean(status) or json.loads((outer/'supervisor-result.json').read_text())!=status:raise RuntimeError('resource monitor failed; retained evidence is censored')
    if source_pins()!=pins:raise RuntimeError('monitor source changed')
    result=json.loads((output/'monitor-result.json').read_text());worker=json.loads((output/'worker-result.json').read_text());trial=output/'trial'
    audit=json.loads((trial/'audit.json').read_text());inputs=json.loads((trial/'inputs.json').read_text())
    intent=json.loads((output/'worker-launch.json').read_text())
    if intent!={'command':worker_command(output,build,case,environment,model),'environment':worker_env(),'wallSeconds':WORKER_SECONDS}:raise RuntimeError('worker invocation differs')
    if inputs.get('build')!=str(build) or type(audit.get('comparisonEligible')) is not bool or (audit['comparisonEligible'] and audit.get('censorReason') is not None) or (not audit['comparisonEligible'] and not isinstance(audit.get('censorReason'),str)):raise RuntimeError('invalid trial identity or censor outcome')
    if result.get('status')!='passed' or worker.get('status')!='diagnostic_only' or audit.get('status')!='diagnostic_only' or worker.get('comparisonEligible') is not audit.get('comparisonEligible') or worker.get('censorReason')!=audit.get('censorReason') or worker.get('auditSHA256')!=runner.sha(trial/'audit.json') or worker.get('inputsSHA256')!=runner.sha(trial/'inputs.json'):raise RuntimeError('incomplete or changed evidence')
    for arm in runner.ARMS:
        if not clean(json.loads((trial/arm/'monitor/supervisor-result.json').read_text())):raise RuntimeError('arm failed; retained evidence is censored')
    verify_logs(output)
    if any(shutil.disk_usage(path).free<34*GIB for path in disk_paths(output).values()):raise RuntimeError('disk below final-audit headroom')
    worker_hash=runner.sha(output/'worker-result.json');final=output/'final-monitor';final.mkdir()
    final_args=final_command(output,worker_hash)
    write_new(output/'final-launch.json',{'command':final_args,'environment':env,'wallSeconds':FINAL_SECONDS})
    final_status=runner.hidden.supervise(final_args,final,env,FINAL_SECONDS)
    if not clean(final_status) or json.loads((final/'supervisor-result.json').read_text())!=final_status:raise RuntimeError('bounded final audit failed; evidence censored')
    final_result=json.loads((output/'final-result.json').read_text())
    if final_result!={'status':'verified_diagnostic','workerSHA256':worker_hash,'auditSHA256':worker['auditSHA256']} or runner.sha(output/'worker-result.json')!=worker_hash or source_pins()!=pins:raise RuntimeError('final evidence changed')
    if any(shutil.disk_usage(path).free<32*GIB for path in disk_paths(output).values()):raise RuntimeError('disk below final 32 GiB floor')
    write_new(output/'completion.json',{'status':'diagnostic_only','comparisonEligible':audit.get('comparisonEligible'),'censorReason':audit.get('censorReason'),
              'auditSHA256':worker['auditSHA256'],'inputsSHA256':worker['inputsSHA256'],'telemetrySHA256':runner.sha(output/'telemetry.jsonl'),
              'diskSHA256':runner.sha(output/'disk.jsonl'),'finalWorkerSHA256':worker_hash,
              'outerStatusSHA256':runner.sha(outer/'supervisor-result.json'),'finalStatusSHA256':runner.sha(final/'supervisor-result.json'),
              'finalLaunchSHA256':runner.sha(output/'final-launch.json'),'finalResultSHA256':runner.sha(output/'final-result.json'),
              'workerLaunchSHA256':runner.sha(output/'worker-launch.json'),'scope':'one simulated selection case; no hardware or execution attestation'})
    return audit


if __name__=='__main__':raise SystemExit('Simulator launch disabled pending independent review and resource scheduling.')
