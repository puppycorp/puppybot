#!/usr/bin/env python3
"""CPU-only resource, identity, inventory and lifecycle monitor tests."""
import importlib.util
import io
import json
import signal
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location('steering_monitor_test', HERE / 'monitor.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def fake_logs(output, mode='ok'):
    output = Path(output)
    gpu = [dict(phase=phase, monotonicSeconds=tick, busyPercent=0,
                totalBytes=10*m.telemetry.GIB, usedBytes=m.telemetry.GIB, freeBytes=9*m.telemetry.GIB)
           for phase, tick in [*[('baseline', i) for i in range(1, 32)], ('steering',33),('after-steering',35)]]
    disk = [dict(phase=phase, monotonicSeconds=tick, freeBytes=40*m.telemetry.GIB,
                 volumes={name:40*m.telemetry.GIB for name in ('output','workspace','home')}) for phase,tick in
            [('pre-baseline',0),('post-baseline',32),('steering',34),('after-steering',36)]]
    if mode == 'missing-baseline': gpu = gpu[1:]
    if mode == 'missing-middle': del gpu[5:7]
    if mode == 'missing-final': gpu = gpu[:-1]
    if mode == 'missing-active': gpu.pop(-2)
    if mode == 'late-active': gpu[-2]['monotonicSeconds'] = 34
    if mode == 'late-final': gpu[-1]['monotonicSeconds'] = 38; disk[-1]['monotonicSeconds'] = 39
    if mode == 'low-vram': gpu[-2]['usedBytes'] = 9*m.telemetry.GIB; gpu[-2]['freeBytes'] = m.telemetry.GIB
    if mode == 'low-disk': disk[2]['freeBytes'] = 33*m.telemetry.GIB; disk[2]['volumes']['home'] = 33*m.telemetry.GIB
    if mode == 'reordered': disk[1]['monotonicSeconds'] = 33.5
    if mode == 'disk-after-next': disk[2]['monotonicSeconds'] = 35.5
    if mode == 'busy':
        for row in gpu[4:9]: row['busyPercent'] = 11
    (output/'telemetry.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in gpu))
    (output/'disk.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in disk))


class MonitorTests(unittest.TestCase):
    def test_disabled_cli_limits_and_exact_runner(self):
        self.assertEqual((m.OUTER_SECONDS,m.WORKER_SECONDS,m.FINAL_CHECK_SECONDS),(28800,27000,1800))
        self.assertGreaterEqual(m.WORKER_SECONDS, 36 * 600 + 5400)
        self.assertGreaterEqual(m.OUTER_SECONDS, m.WORKER_SECONDS + 1800)
        self.assertEqual(m.worker_command()[-1], str(HERE/'runner.py'))
        self.assertIn('m.run()', m.worker_command()[-2])
        result = subprocess.run([sys.executable,'-I',str(HERE/'monitor.py')],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0);self.assertIn('Disabled',result.stderr)
        with mock.patch.object(m.shutil,'disk_usage',return_value=SimpleNamespace(free=33*m.telemetry.GIB)):
            with self.assertRaisesRegex(RuntimeError,'34 GiB'):m.require_disk(34)

    def test_home_disk_low_or_unavailable_fails_closed(self):
        def usage(path):
            if path == Path.home(): return SimpleNamespace(free=33*m.telemetry.GIB)
            return SimpleNamespace(free=40*m.telemetry.GIB)
        with mock.patch.object(m.shutil,'disk_usage',side_effect=usage):
            with self.assertRaisesRegex(RuntimeError,'34 GiB'):m.require_disk(34)
            log=io.StringIO()
            with self.assertRaisesRegex(RuntimeError,'34 GiB'):m.sample_disk(log,'steering',34)
            self.assertEqual(json.loads(log.getvalue())['volumes']['home'],33*m.telemetry.GIB)
        def lost(path):
            if path == Path.home():raise OSError('home telemetry lost')
            return SimpleNamespace(free=40*m.telemetry.GIB)
        with mock.patch.object(m.shutil,'disk_usage',side_effect=lost):
            with self.assertRaises(OSError):m.require_disk(34)
            with self.assertRaises(OSError):m.sample_disk(io.StringIO(),'steering',34)

    def test_clean_status_requires_explicit_signal(self):
        clean={'clientExit':0,'timedOut':False,'signal':None,'remainingWorkersTerminated':False,'processGroup':123}
        self.assertTrue(m.clean(clean));missing=dict(clean);missing.pop('signal')
        self.assertFalse(m.clean(missing));self.assertFalse(m.clean(dict(clean,processGroup=True)))

    def test_registered_module_contract_and_monitor_is_pinned(self):
        registrar = m.load('steering_test_registration', m.REGISTER)
        self.assertEqual(registrar.MANIFEST, m.MANIFEST)
        self.assertEqual(registrar.plan.OUTPUT, m.OUTPUT)
        self.assertIn(HERE / 'monitor.py', registrar.source_paths())
        self.assertIn(HERE / 'runner.py', registrar.source_paths())

    def test_log_resource_and_completeness_fail_closed(self):
        for mode in ('ok','missing-baseline','missing-middle','missing-final','missing-active','late-active',
                     'late-final','low-vram','low-disk','reordered','disk-after-next','busy'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                fake_logs(tmp,mode)
                if mode=='ok': m.verify_logs(tmp)
                else:
                    with self.assertRaises((ValueError,IndexError)):m.verify_logs(tmp)

    def test_no_overwrite_and_missing_manifest_before_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); manifest=root/'manifest'; monitor=root/'monitor'; output=root/'output'
            with mock.patch.object(m,'MANIFEST',manifest),mock.patch.object(m,'MONITOR',monitor),mock.patch.object(m,'OUTPUT',output), \
                 mock.patch.object(m.guard,'require_dedicated_process'),mock.patch.object(m,'require_disk'):
                with self.assertRaisesRegex(ValueError,'manifest missing'):m.launch()
                manifest.write_text('{}');output.mkdir()
                with self.assertRaises(FileExistsError):m.launch()
                self.assertFalse(monitor.exists())

    def test_launch_binds_report_inventory_and_both_deadlines(self):
        for mode in ('ok', 'bad-outer', 'outer-missing-signal', 'outer-disk-mismatch', 'bad-monitor', 'bad-input', 'bad-report', 'bad-inventory', 'final-timeout', 'final-missing-signal', 'final-disk-mismatch', 'source-change', 'telemetry-change', 'disk-change'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp); manifest=root/'manifest';manifest.write_text('{}');monitor=root/'monitor';output=root/'output'
                frozen={'schema':'registered'}
                report={'schema':'puppybot.l5-steering-hysteresis-comparison.v1','status':'diagnostic_only',
                        'pairs':list(range(12)),'totals':{}}
                clean={'clientExit':0,'timedOut':False,'signal':None,'remainingWorkersTerminated':False,'processGroup':123}
                observed=[]
                source_reads = []; resource_reads = {}
                def digest(path):
                    if Path(path) == HERE/'monitor.py':
                        source_reads.append(1)
                        if mode == 'source-change' and len(source_reads) > 1: return 'changed'
                    if Path(path) in (monitor/'telemetry.jsonl', monitor/'disk.jsonl'):
                        resource_reads[Path(path).name] = resource_reads.get(Path(path).name, 0) + 1
                        if ((mode == 'telemetry-change' and Path(path).name == 'telemetry.jsonl') or
                                (mode == 'disk-change' and Path(path).name == 'disk.jsonl')) and resource_reads[Path(path).name] > 1:
                            return 'changed'
                    return 'sha'
                def supervise(command,directory,env,timeout):
                    observed.append((directory.name,timeout))
                    if directory.name=='final-inventory-monitor':
                        (directory/'client.log').write_text(json.dumps({'status':'final_inventory_verified'}))
                        if mode=='final-missing-signal':
                            no_signal=dict(clean);no_signal.pop('signal')
                            (directory/'supervisor-result.json').write_text(json.dumps(no_signal));return no_signal
                        (directory/'supervisor-result.json').write_text(json.dumps(dict(clean,clientExit=1) if mode=='final-disk-mismatch' else clean))
                        return dict(clean,timedOut=True) if mode=='final-timeout' else clean
                    if mode=='outer-missing-signal':
                        no_signal=dict(clean);no_signal.pop('signal')
                        (directory/'supervisor-result.json').write_text(json.dumps(no_signal));return no_signal
                    (directory/'supervisor-result.json').write_text(json.dumps(dict(clean,clientExit=1) if mode=='outer-disk-mismatch' else clean))
                    (monitor/'monitor-result.json').write_text(json.dumps({'status':'failed' if mode=='bad-monitor' else 'passed'}))
                    fake_logs(monitor);(monitor/'frozen-manifest.json').write_text(json.dumps(frozen))
                    output.mkdir();(output/'inputs.json').write_text(json.dumps({} if mode=='bad-input' else frozen))
                    (output/'report.json').write_text(json.dumps(report))
                    files={'inputs.json':'sha','report.json':'wrong' if mode=='bad-inventory' else 'sha'}
                    (monitor/'evidence.json').write_text(json.dumps({'status':'diagnostic_only',
                         'report':{} if mode=='bad-report' else report,'files':files}))
                    return dict(clean,processGroup=True) if mode=='bad-outer' else clean
                with mock.patch.object(m,'MANIFEST',manifest),mock.patch.object(m,'MONITOR',monitor),mock.patch.object(m,'OUTPUT',output), \
                     mock.patch.object(m.guard,'require_dedicated_process'),mock.patch.object(m,'require_disk'), \
                     mock.patch.object(m.base,'sha',side_effect=digest),mock.patch.object(m.base.hidden,'supervise',side_effect=supervise):
                    if mode=='ok':
                        self.assertEqual(m.launch(),report)
                        self.assertEqual(observed,[('outer-monitor',28800),('final-inventory-monitor',1800)])
                        self.assertTrue((monitor/'completion.json').is_file())
                        completion=json.loads((monitor/'completion.json').read_text())
                        self.assertIn('outerSupervisorStatusSHA256',completion)
                        self.assertIn('finalInventoryInvocationSHA256',completion)
                        saved=json.loads((monitor/'launch.json').read_text())
                        self.assertEqual(saved['workerCommand'],m.worker_command())
                        self.assertEqual(saved['workerEnvironment'],m.environment())
                    else:
                        with self.assertRaises((ValueError,RuntimeError)):m.launch()
                        self.assertFalse((monitor/'completion.json').exists())

    def test_verify_saved_compares_full_manifest_and_reaudit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); frozen={'schema':'frozen'};report={'schema':'puppybot.l5-steering-hysteresis-comparison.v1','status':'diagnostic_only','pairs':list(range(12)),'totals':{}}
            (root/'inputs.json').write_text(json.dumps(frozen));(root/'report.json').write_text(json.dumps(report))
            fake=SimpleNamespace(reaudit=lambda x:report if x==frozen else None)
            with mock.patch.object(m,'OUTPUT',root),mock.patch.object(m,'load',return_value=fake):
                self.assertEqual(m.verify_saved(frozen),report)
                (root/'report.json').write_text(json.dumps(dict(report, totals={'tampered':True})))
                with self.assertRaisesRegex(ValueError,'re-audit'):m.verify_saved(frozen)
                (root/'inputs.json').write_text('{}')
                with self.assertRaisesRegex(ValueError,'manifest'):m.verify_saved(frozen)

    def test_worker_checks_input_pins_before_and_after_reaudit(self):
        process=SimpleNamespace(pid=123,returncode=0,poll=lambda:0)
        for mode in ('ok','changed-before','changed-after'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                frozen={'pin':'a'}; values=[frozen,{'pin':'b'} if mode=='changed-before' else frozen,{'pin':'b'} if mode=='changed-after' else frozen]
                registrar=SimpleNamespace(verify=mock.Mock(side_effect=values))
                with mock.patch.object(m,'load',return_value=registrar),mock.patch.object(m,'baseline'),mock.patch.object(m,'sample_disk'), \
                     mock.patch.object(m,'verify_logs'),mock.patch.object(m,'require_disk'),mock.patch.object(m,'verify_saved',return_value={'status':'diagnostic_only'}) as checked, \
                     mock.patch.object(m,'inventory',return_value={}),mock.patch.object(m.telemetry,'sample',return_value={'freeBytes':8*m.telemetry.GIB}), \
                     mock.patch.object(m.subprocess,'Popen',return_value=process) as spawned,mock.patch.object(m.os,'pidfd_open',return_value=456),mock.patch.object(m.os,'close'):
                    if mode=='ok':
                        m.monitor_worker(tmp);self.assertEqual(json.loads((Path(tmp)/'monitor-result.json').read_text())['status'],'passed')
                    else:
                        with self.assertRaisesRegex(ValueError,'inputs changed'):m.monitor_worker(tmp)
                        self.assertEqual(json.loads((Path(tmp)/'monitor-result.json').read_text())['status'],'failed')
                        if mode=='changed-before':checked.assert_not_called()
                    self.assertEqual(spawned.call_args.args[0],m.worker_command())
                    self.assertEqual(spawned.call_args.kwargs['env'],m.environment())

    def test_final_inventory_detects_removed_changed_or_extra_files(self):
        for mode in ('ok','removed','changed','extra','inputs','late-input','evidence-before','evidence-during','wrong-reaudit','symlink'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);output=root/'game';output.mkdir();monitor=root/'monitor';monitor.mkdir()
                (output/'game.bin').write_bytes(b'original');report={'status':'diagnostic_only'}; frozen={'pin':'a'}
                (monitor/'frozen-manifest.json').write_text(json.dumps(frozen))
                (monitor/'evidence.json').write_text(json.dumps({'status':'diagnostic_only','report':report,'files':m.inventory(output)}))
                evidence_sha=m.base.sha(monitor/'evidence.json')
                if mode=='removed':(output/'game.bin').unlink()
                if mode=='changed':(output/'game.bin').write_bytes(b'changed')
                if mode=='extra':(output/'unexpected').write_text('x')
                if mode=='symlink':(output/'link').symlink_to('game.bin')
                if mode=='evidence-before':(monitor/'evidence.json').write_text('{}')
                calls=[]
                def verify():
                    calls.append(1)
                    if mode=='evidence-during' and len(calls)==2:(monitor/'evidence.json').write_text('{}')
                    if mode=='inputs' or (mode=='late-input' and len(calls)==2):return {'pin':'b'}
                    return frozen
                registrar=SimpleNamespace(verify=verify)
                actual_report={'status':'wrong'} if mode=='wrong-reaudit' else report
                with mock.patch.object(m,'OUTPUT',output),mock.patch.object(m,'load',return_value=registrar),mock.patch.object(m,'verify_saved',return_value=actual_report):
                    if mode=='ok':self.assertEqual(m.final_check(monitor,evidence_sha),{'status':'final_inventory_verified'})
                    else:
                        with self.assertRaises(ValueError):m.final_check(monitor,evidence_sha)

    def test_inventory_surfaces_walk_error_and_vanished_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def denied(*args, onerror=None, **kwargs):
                onerror(PermissionError('inaccessible directory'))
                yield
            with mock.patch.object(m.os,'walk',side_effect=denied):
                with self.assertRaises(PermissionError):m.inventory(root)
            def disappeared(*args,**kwargs):
                yield str(root), ['already-vanished'], []
            with mock.patch.object(m.os,'walk',side_effect=disappeared):
                with self.assertRaisesRegex(ValueError,'vanished'):m.inventory(root)

    def test_real_nested_failures_do_not_touch_unrelated_process(self):
        child_code = 'import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)'
        worker_code = ('import os,signal,subprocess,sys,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);'
                       'p=subprocess.Popen([sys.executable,"-c",sys.argv[2]],start_new_session=True);'
                       'open(sys.argv[1],"w").write(str(os.getpid())+" "+str(p.pid));time.sleep(30)')
        monitor_code = textwrap.dedent('''
            import importlib.util,os,signal,subprocess,sys,time
            from pathlib import Path
            s=importlib.util.spec_from_file_location('m',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
            output=Path(sys.argv[2]);mode=sys.argv[3];pidfile=output/'workers.pid'
            original=m.subprocess.Popen
            def spawn(*args,**kwargs): return original([sys.executable,'-c',sys.argv[4],str(pidfile),sys.argv[5]],**kwargs)
            def ready():
                end=time.monotonic()+4
                while not pidfile.exists() and time.monotonic()<end: time.sleep(.01)
                if not pidfile.exists(): raise RuntimeError('fixture worker did not start')
            def sample(stream,phase):
                ready()
                if mode=='kill-monitor': os.kill(os.getpid(),signal.SIGKILL)
                if mode=='telemetry': raise RuntimeError('GPU telemetry unavailable')
                return {'freeBytes':(1 if mode=='low' else 8)*m.telemetry.GIB}
            original_pidfd=os.pidfd_open
            def pidfd(pid):
                if mode=='pidfd': ready();raise OSError('fixture pidfd failure')
                return original_pidfd(pid)
            # The fixture worker ignores SIGTERM; shorten only the wait passed to Popen.wait.
            original_wait=subprocess.Popen.wait
            def wait(self,timeout=None): return original_wait(self,timeout=min(timeout,.1) if timeout is not None else None)
            subprocess.Popen.wait=wait;m.load=lambda *args:type('Registrar',(),{'verify':staticmethod(lambda:{})})();m.require_disk=lambda gib:None;m.sample_disk=lambda stream,phase,gib: (_ for _ in ()).throw(RuntimeError('disk unavailable')) if mode=='disk' and phase=='steering' else None;m.baseline=lambda log:None;m.WORKER_SECONDS=.1
            m.telemetry.sample=sample;m.subprocess.Popen=spawn;m.os.pidfd_open=pidfd
            m.monitor_worker(output)
        ''')
        outer_code = textwrap.dedent('''
            import importlib.util,json,os,sys
            from pathlib import Path
            s=importlib.util.spec_from_file_location('h',sys.argv[1]);h=importlib.util.module_from_spec(s);s.loader.exec_module(h)
            result=h.supervise([sys.executable,'-c',sys.argv[3],sys.argv[4],sys.argv[2],sys.argv[5],sys.argv[6],sys.argv[7]],Path(sys.argv[2]),os.environ.copy(),15)
            print(json.dumps(result))
        ''')
        other = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(30)'])
        try:
            for mode in ('low', 'telemetry', 'kill-monitor', 'pidfd', 'timeout', 'disk'):
                with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                    args = [sys.executable, '-c', outer_code, str(ROOT / 'flex/tests/run-physical-hidden-trial.py'),
                            tmp, monitor_code, str(HERE / 'monitor.py'), mode, worker_code, child_code]
                    completed = subprocess.run(args, capture_output=True, text=True, timeout=25, check=True)
                    self.assertNotEqual(json.loads(completed.stdout)['clientExit'], 0)
                    self.assertIsNone(other.poll())
                    for pid in map(int, (Path(tmp) / 'workers.pid').read_text().split()):
                        self.assertFalse(Path(f'/proc/{pid}').exists())
                    if mode != 'kill-monitor':
                        self.assertEqual(json.loads((Path(tmp) / 'monitor-result.json').read_text())['status'], 'failed')
        finally:
            other.terminate(); other.wait(timeout=5)

    def test_repeated_signals_during_cleanup_preserve_unrelated_sibling(self):
        child='import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)'
        worker=('import os,signal,subprocess,sys,time;'
                'p=subprocess.Popen([sys.executable,"-c",sys.argv[2]],start_new_session=True);'
                'open(sys.argv[1],"w").write(str(os.getpid())+" "+str(p.pid));'
                'signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)')
        code=textwrap.dedent('''
            import importlib.util,json,os,signal,sys
            from pathlib import Path
            s=importlib.util.spec_from_file_location('hidden',sys.argv[1]);h=importlib.util.module_from_spec(s);s.loader.exec_module(h)
            original=h.supervisor.cleanup_descendants
            def cleanup():
                os.kill(os.getpid(),signal.SIGTERM);os.kill(os.getpid(),signal.SIGTERM)
                return original()
            h.supervisor.cleanup_descendants=cleanup
            status=h.supervise([sys.executable,'-c',sys.argv[3],sys.argv[2]+'/workers.pid',sys.argv[4]],Path(sys.argv[2]),os.environ.copy(),1)
            print(json.dumps(status))
        ''')
        other=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])
        try:
            with tempfile.TemporaryDirectory() as tmp:
                run=subprocess.run([sys.executable,'-c',code,str(ROOT/'flex/tests/run-physical-hidden-trial.py'),tmp,worker,child],
                                   capture_output=True,text=True,timeout=20,check=True)
                status=json.loads(run.stdout);self.assertTrue(status['timedOut']);self.assertEqual(status['signal'],signal.SIGTERM)
                self.assertIsNone(other.poll())
                for pid in [status['processGroup'],*map(int,(Path(tmp)/'workers.pid').read_text().split())]:
                    self.assertFalse(Path(f'/proc/{pid}').exists())
        finally:
            other.terminate();other.wait(timeout=5)


if __name__ == '__main__': unittest.main()
