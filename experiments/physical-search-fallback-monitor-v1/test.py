#!/usr/bin/env python3
"""Synthetic resource receipts and real CPU-only descendant cleanup."""
import importlib.util
import json
import os
import subprocess
import sys
import time
import signal
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
spec=importlib.util.spec_from_file_location('search_monitor',HERE/'monitor.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class MonitorTest(unittest.TestCase):
    def test_cli_disabled_and_no_overwrite(self):
        r=subprocess.run([sys.executable,'-I',str(HERE/'monitor.py')],capture_output=True,text=True)
        self.assertNotEqual(r.returncode,0);self.assertIn('disabled',r.stderr.lower())
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out';out.mkdir();(out/'sentinel').write_text('keep')
            with mock.patch.object(m.guard,'require_dedicated_process'):
                with self.assertRaisesRegex(ValueError,'output exists'):m.launch(out,'b','c','e','m')
            self.assertEqual((out/'sentinel').read_text(),'keep')

    def test_baseline_rejects_low_or_busy_gpu(self):
        for row in ({'monotonicSeconds':0,'freeBytes':5*m.GIB,'busyPercent':0},
                    {'monotonicSeconds':0,'freeBytes':8*m.GIB,'busyPercent':11}):
            with self.subTest(row=row),mock.patch.object(m.telemetry,'sample',return_value=row),mock.patch.object(m.time,'sleep'):
                with self.assertRaises(RuntimeError):m.baseline(None)

    def test_preflight_all_filesystems(self):
        with tempfile.TemporaryDirectory() as tmp,mock.patch.object(m.guard,'require_dedicated_process'):
            out=Path(tmp)/'out'
            for low in range(3):
                calls=iter([type('D',(),{'free':(33 if i==low else 40)*m.GIB})() for i in range(3)])
                with mock.patch.object(m.shutil,'disk_usage',side_effect=lambda p:next(calls)):
                    with self.assertRaisesRegex(ValueError,'insufficient disk'):m.launch(out,'b','c','e','m')
                self.assertFalse(out.exists())

    def test_worker_command_and_reaudit(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp);trial=out/'trial';trial.mkdir();report={'status':'diagnostic_only','comparisonEligible':False,'censorReason':'search_not_started'}
            (trial/'audit.json').write_text(json.dumps(report));(trial/'inputs.json').write_text('{}')
            auditor=type('Auditor',(),{'audit':staticmethod(lambda p:dict(report))})
            with mock.patch.object(m.runner,'launch') as run,mock.patch.object(m.runner,'check_manifest'),mock.patch.object(m,'load',return_value=auditor):m.trial_worker(out,'b','c','e','m')
            run.assert_called_once();self.assertEqual(json.loads((out/'worker-result.json').read_text())['censorReason'],'search_not_started')
            (out/'worker-result.json').unlink();auditor.audit=lambda p:dict(report,censorReason='different')
            with mock.patch.object(m.runner,'launch'),mock.patch.object(m,'load',return_value=auditor):
                with self.assertRaisesRegex(ValueError,'audit differs'):m.trial_worker(out,'b','c','e','m')
            self.assertFalse((out/'worker-result.json').exists())
            self.assertEqual(m.worker_env()['PUPPYBOT_SEARCH_TRIAL_REVIEWED_WORKER'],'1')
            self.assertEqual(m.worker_command(out,'b','c','e','m')[-5:],[str(out),'b','c','e','m'])

    def test_receipt_and_censor_fail_closed(self):
        for mode in ('ok','censored','bad-outer','missing-signal','bad-arm','arm-missing-signal','bad-worker','changed-pin','wrong-command','bad-audit','missing-final','low-gpu','low-disk','disk-order','sample-gap','missing-active','final-failure','status-file-mismatch'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);out=root/'output';build=(root/'build').absolute();case=(root/'case').absolute();environment=(root/'env').absolute();model=(root/'model').absolute()
                clean={'clientExit':0,'signal':None,'timedOut':False,'remainingWorkersTerminated':False,'processGroup':123}
                report={'status':'diagnostic_only','comparisonEligible':mode not in ('censored',),'censorReason':'search_not_started' if mode=='censored' else None}
                def supervise(command,directory,env,seconds):
                    if directory.name=='final-monitor':
                        (directory/'supervisor-result.json').write_text(json.dumps(clean))
                        (out/'final-result.json').write_text(json.dumps({'status':'verified_diagnostic','workerSHA256':'sha','auditSHA256':'sha'}))
                        return dict(clean,timedOut=True) if mode=='final-failure' else clean
                    (directory/'supervisor-result.json').write_text(json.dumps(dict(clean,timedOut=True) if mode=='status-file-mismatch' else clean))
                    trial=out/'trial';trial.mkdir();(trial/'audit.json').write_text(json.dumps(report));(trial/'inputs.json').write_text(json.dumps({'build':str(build)}))
                    for arm in m.runner.ARMS:
                        p=trial/arm/'monitor';p.mkdir(parents=True);(p/'supervisor-result.json').write_text(json.dumps(dict(clean,processGroup=True) if mode=='bad-arm' and arm=='baseline' else {k:v for k,v in clean.items() if k!='signal'} if mode=='arm-missing-signal' and arm=='baseline' else clean))
                    worker={'status':'diagnostic_only','auditSHA256':'sha','inputsSHA256':'sha','comparisonEligible':report['comparisonEligible'],'censorReason':report['censorReason']}
                    if mode=='bad-audit':worker['auditSHA256']='wrong'
                    (out/'worker-result.json').write_text(json.dumps(worker));(out/'monitor-result.json').write_text(json.dumps({'status':'failed' if mode=='bad-worker' else 'passed'}))
                    intent={'command':m.worker_command(out,build,case,environment,model),'environment':m.worker_env(),'wallSeconds':m.WORKER_SECONDS}
                    if mode=='wrong-command':intent['command'][-1]='different'
                    (out/'worker-launch.json').write_text(json.dumps(intent))
                    gpu=[{'phase':phase,'monotonicSeconds':t,'busyPercent':0,'totalBytes':10*m.GIB,'usedBytes':m.GIB,'freeBytes':9*m.GIB} for phase,t in [*[('baseline',i) for i in range(1,32)],('trial',33),('after-trial',35)]]
                    disk=[{'phase':phase,'monotonicSeconds':t,'freeBytes':{'home':40*m.GIB,'output':40*m.GIB,'workspace':40*m.GIB}} for phase,t in [('pre-baseline',0),('post-baseline',32),('trial',34),('after-trial',36)]]
                    if mode=='missing-final':gpu.pop()
                    if mode=='low-gpu':gpu[-2]['freeBytes']=1
                    if mode=='low-disk':disk[2]['freeBytes']['home']=1
                    if mode=='disk-order':disk[1]['monotonicSeconds']=33.5
                    if mode=='sample-gap':gpu[-1]['monotonicSeconds']=36;disk[-1]['monotonicSeconds']=37
                    if mode=='missing-active':gpu.pop(-2)
                    (out/'telemetry.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in gpu));(out/'disk.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in disk))
                    return dict(clean,clientExit=False) if mode=='bad-outer' else {k:v for k,v in clean.items() if k!='signal'} if mode=='missing-signal' else clean
                pins=iter([{'source':'first'},{'source':'changed' if mode=='changed-pin' else 'first'},{'source':'first'}])
                with mock.patch.object(m.guard,'require_dedicated_process'),mock.patch.object(m.shutil,'disk_usage',return_value=type('D',(),{'free':40*m.GIB})()),mock.patch.object(m,'source_pins',side_effect=lambda:next(pins)),mock.patch.object(m.runner,'sha',return_value='sha'),mock.patch.object(m.runner.hidden,'supervise',side_effect=supervise):
                    if mode in ('ok','censored'):
                        result=m.launch(out,build,case,environment,model);self.assertEqual(result,report)
                        receipt=json.loads((out/'completion.json').read_text());self.assertEqual(receipt['comparisonEligible'],mode=='ok')
                        self.assertTrue(all(receipt[k]=='sha' for k in ('outerStatusSHA256','finalStatusSHA256','finalLaunchSHA256','finalResultSHA256','workerLaunchSHA256')))
                    else:
                        with self.assertRaises((ValueError,RuntimeError)):m.launch(out,build,case,environment,model)
                        self.assertFalse((out/'completion.json').exists())

    def test_inventory_fails_closed_on_walk_error(self):
        def broken(root,followlinks,onerror):
            onerror(PermissionError('unreadable directory'))
            yield None
        with mock.patch.object(m.os,'walk',side_effect=broken):
            with self.assertRaisesRegex(PermissionError,'unreadable'):m.inventory('/unused')

    def test_final_inventory_rejects_trace_actor_and_status_changes(self):
        for name in ('trace.jsonl','actors/actor-1.rgb','monitor/supervisor-result.json'):
            with self.subTest(name=name),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);trial=root/'trial';trial.mkdir()
                for item in ('trace.jsonl','actors/actor-1.rgb','monitor/supervisor-result.json'):
                    path=trial/item;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('original')
                (trial/'audit.json').write_text(json.dumps({'status':'diagnostic_only'}))
                expected=m.inventory(trial);worker={'inventory':expected,'auditSHA256':'saved'}
                (root/'worker-result.json').write_text(json.dumps(worker));digest=m.runner.sha(root/'worker-result.json')
                auditor=type('Auditor',(),{'audit':staticmethod(lambda p:{'status':'diagnostic_only'})})
                with mock.patch.object(m,'load',return_value=auditor):m.final_worker(root,digest)
                (root/'final-result.json').unlink();(trial/name).write_text('changed')
                with mock.patch.object(m,'load',return_value=auditor):
                    with self.assertRaisesRegex(ValueError,'evidence changed'):m.final_worker(root,digest)
                self.assertFalse((root/'final-result.json').exists())
                (trial/name).write_text('original')
                def alter(p):
                    (trial/name).write_text('mutated during audit');return {'status':'diagnostic_only'}
                auditor.audit=alter
                with mock.patch.object(m,'load',return_value=auditor):
                    with self.assertRaisesRegex(ValueError,'during final audit'):m.final_worker(root,digest)
                self.assertFalse((root/'final-result.json').exists())

    def test_nested_abort_reaps_detached_and_preserves_sibling(self):
        child=('import signal,sys,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);'
               'open(sys.argv[1],"w").write("ready");time.sleep(30)')
        worker=textwrap.dedent('''
            import os,signal,subprocess,sys,time
            signal.signal(signal.SIGTERM,signal.SIG_IGN)
            ready=sys.argv[1]+'.ready'
            p=subprocess.Popen([sys.executable,'-c',sys.argv[2],ready],start_new_session=True)
            deadline=time.monotonic()+4
            while not os.path.exists(ready) and time.monotonic()<deadline:time.sleep(.01)
            if not os.path.exists(ready):raise RuntimeError('detached child did not initialize')
            open(sys.argv[1],'w').write(str(os.getpid())+' '+str(p.pid))
            time.sleep(30)
        ''')
        monitor=textwrap.dedent('''
            import importlib.util,os,signal,subprocess,sys,time
            from pathlib import Path
            s=importlib.util.spec_from_file_location('m',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
            output=Path(sys.argv[2]);mode=sys.argv[3];pidfile=output/'workers.pid';original=m.subprocess.Popen
            def spawn(*args,**kwargs):return original([sys.executable,'-c',sys.argv[4],str(pidfile),sys.argv[5]],**kwargs)
            def ready():
                end=time.monotonic()+4
                while not pidfile.exists() and time.monotonic()<end:time.sleep(.01)
                if not pidfile.exists():raise RuntimeError('fixture worker did not start')
            def sample(stream,phase):
                ready()
                if mode=='kill-monitor':os.kill(os.getpid(),signal.SIGKILL)
                if mode=='telemetry':raise RuntimeError('GPU telemetry unavailable')
                return {'freeBytes':(8 if mode in ('timeout','signal') else 1)*m.GIB}
            original_pidfd=os.pidfd_open
            def pidfd(pid):
                if mode=='pidfd':ready();raise OSError('pidfd failure')
                return original_pidfd(pid)
            original_wait=subprocess.Popen.wait
            def wait(self,timeout=None):return original_wait(self,timeout=min(timeout,.1) if timeout is not None else None)
            subprocess.Popen.wait=wait;m.sample_disk=lambda stream,phase,paths,gib:(_ for _ in ()).throw(RuntimeError('disk unavailable')) if mode=='disk' and phase=='trial' else None
            m.baseline=lambda stream:None;m.WORKER_SECONDS=30 if mode=='signal' else .1;m.telemetry.sample=sample;m.subprocess.Popen=spawn;m.os.pidfd_open=pidfd
            m.monitor_worker(output,'build','case','environment','model')
        ''')
        outer=textwrap.dedent('''
            import importlib.util,json,os,sys
            from pathlib import Path
            s=importlib.util.spec_from_file_location('h',sys.argv[1]);h=importlib.util.module_from_spec(s);s.loader.exec_module(h)
            result=h.supervise([sys.executable,'-c',sys.argv[3],sys.argv[4],sys.argv[2],sys.argv[5],sys.argv[6],sys.argv[7]],Path(sys.argv[2]),os.environ.copy(),15)
            print(json.dumps(result))
        ''')
        sibling=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])
        try:
            for mode in ('low','telemetry','kill-monitor','pidfd','timeout','disk','signal'):
                with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                    args=[sys.executable,'-c',outer,str(ROOT/'flex/tests/run-physical-hidden-trial.py'),tmp,monitor,str(HERE/'monitor.py'),mode,worker,child]
                    if mode=='signal':
                        process=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                        try:
                            deadline=time.monotonic()+5
                            while not (Path(tmp)/'workers.pid').exists() and time.monotonic()<deadline:time.sleep(.01)
                            self.assertTrue((Path(tmp)/'workers.pid').exists())
                            child_pid=int((Path(tmp)/'workers.pid').read_text().split()[1]);os.kill(process.pid,signal.SIGTERM)
                            deadline=time.monotonic()+8;reparented=False
                            while time.monotonic()<deadline:
                                try:
                                    fields=Path(f'/proc/{child_pid}/status').read_text().splitlines()
                                    parent=int(next(x.split()[1] for x in fields if x.startswith('PPid:')))
                                    if parent==process.pid:reparented=True;break
                                except (FileNotFoundError,StopIteration,ProcessLookupError):pass
                                time.sleep(.002)
                            self.assertTrue(reparented,'escaped child was not observed under outer subreaper')
                            os.kill(process.pid,signal.SIGTERM)
                            stdout,stderr=process.communicate(timeout=25);self.assertEqual(process.returncode,0,stderr);status=json.loads(stdout);self.assertEqual(status['signal'],signal.SIGTERM)
                        finally:
                            if process.poll() is None:
                                process.terminate()
                                try:process.communicate(timeout=25)
                                except subprocess.TimeoutExpired:process.kill();process.communicate()
                            else:process.communicate()
                    else:
                        result=subprocess.run(args,capture_output=True,text=True,timeout=25,check=True);status=json.loads(result.stdout)
                    self.assertNotEqual(status['clientExit'],0);self.assertIsNone(sibling.poll())
                    for pid in map(int,(Path(tmp)/'workers.pid').read_text().split()):self.assertFalse(Path(f'/proc/{pid}').exists())
                    if mode not in ('kill-monitor','signal'):self.assertEqual(json.loads((Path(tmp)/'monitor-result.json').read_text())['status'],'failed')
                    self.assertFalse((Path(tmp)/'completion.json').exists())
        finally:sibling.terminate();sibling.wait(timeout=5)


if __name__=='__main__':unittest.main()
