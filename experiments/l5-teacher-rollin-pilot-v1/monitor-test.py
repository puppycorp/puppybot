#!/usr/bin/env python3
"""CPU-only paired pilot monitor evidence, bounds and lifecycle fixtures."""
import importlib.util
import json
import signal
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location('rollin_monitor_fixture', HERE / 'monitor.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


class MonitorTests(unittest.TestCase):
    def test_limits_cli_and_exact_worker(self):
        self.assertEqual(m.OUTER_SECONDS, 2100); self.assertEqual(m.WORKER_SECONDS, 1950); self.assertEqual(m.FINAL_CHECK_SECONDS, 300)
        self.assertEqual(m.worker_command()[-1], str(HERE / 'pilot.py'))
        self.assertIn('m.run()', m.worker_command()[-2])
        for arm in ('student', 'teacher'):
            self.assertEqual(m.pilot.command(arm, '/tmp/pilot')[-1] if arm == 'student' else 'teacher', str(m.pilot.MODEL) if arm == 'student' else 'teacher')
        result = subprocess.run([sys.executable, '-I', str(HERE / 'monitor.py')], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0); self.assertIn('Disabled', result.stderr)

    def test_existing_pilot_refuses_before_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); pilot = root / 'pilot'; pilot.mkdir()
            with mock.patch.object(m.pilot, 'P', root), mock.patch.object(m.pilot, 'OUTPUT', pilot), \
                 mock.patch.object(m.pilot.standalone, 'require_dedicated_process'), mock.patch.object(m, 'require_disk'):
                with self.assertRaises(FileExistsError): m.launch()
            self.assertFalse((root / 'l5-teacher-rollin-pilot-monitored-v1').exists())

    def test_worker_rechecks_inputs_and_refuses_changed_pins(self):
        process = type('Process', (), {'pid': 123, 'returncode': 0, 'poll': lambda self: 0})()
        for mode in ('ok', 'changed-before-audit', 'changed-after-audit'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                pins = [{'input': 'a'}, {'input': 'b' if mode == 'changed-before-audit' else 'a'},
                        {'input': 'b' if mode == 'changed-after-audit' else 'a'}]
                with mock.patch.object(m.pilot, 'pin_inputs', side_effect=pins), mock.patch.object(m, 'baseline'), \
                     mock.patch.object(m, 'sample_disk'), mock.patch.object(m, 'verify_logs'), mock.patch.object(m, 'require_disk'), \
                     mock.patch.object(m, 'verify_pilot', return_value={'status': 'diagnostic_only'}) as checked, \
                     mock.patch.object(m, 'inventory', return_value={}), \
                     mock.patch.object(m.telemetry, 'sample', return_value={'freeBytes': 8*m.telemetry.GIB}), \
                     mock.patch.object(m.subprocess, 'Popen', return_value=process) as spawned, \
                     mock.patch.object(m.os, 'pidfd_open', return_value=456), mock.patch.object(m.os, 'close'):
                    if mode == 'ok':
                        m.monitor_worker(tmp)
                        self.assertEqual(json.loads((Path(tmp) / 'monitor-result.json').read_text())['status'], 'passed')
                    else:
                        with self.assertRaisesRegex(ValueError, 'inputs changed'): m.monitor_worker(tmp)
                        self.assertEqual(json.loads((Path(tmp) / 'monitor-result.json').read_text())['status'], 'failed')
                        if mode == 'changed-before-audit': checked.assert_not_called()
                    self.assertEqual(spawned.call_args.args[0], m.worker_command())

    def test_completion_checks_logs_report_and_status(self):
        for mode in ('ok', 'bad-monitor', 'bad-outer', 'wrong-report', 'wrong-input', 'bad-inventory', 'missing-baseline', 'missing-middle', 'missing-final', 'low-gpu', 'low-disk', 'reordered-disk', 'final-timeout'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); trial = root / 'pilot'; report = {'status': 'diagnostic_only', 'pairs': []}; frozen = {'input': 'digest'}
                clean = {'clientExit': 0, 'timedOut': False, 'signal': None, 'remainingWorkersTerminated': False, 'processGroup': 123}
                def supervise(command, directory, env, timeout):
                    if directory.name == 'final-inventory-monitor':
                        self.assertEqual(timeout, 300)
                        (directory / 'client.log').write_text(json.dumps({'status': 'final_inventory_verified'}))
                        (directory / 'supervisor-result.json').write_text(json.dumps(clean))
                        return dict(clean, timedOut=True) if mode == 'final-timeout' else clean
                    self.assertEqual(timeout, 2100); monitor = directory.parent
                    (monitor / 'monitor-result.json').write_text(json.dumps({'status': 'failed' if mode == 'bad-monitor' else 'passed'}))
                    gpu = [dict(phase=phase, monotonicSeconds=tick, busyPercent=0, totalBytes=10*m.telemetry.GIB,
                                usedBytes=m.telemetry.GIB, freeBytes=9*m.telemetry.GIB) for phase,tick in
                           [*[('baseline', i) for i in range(1, 32)], ('rollin', 33), ('after-rollin', 35)]]
                    disk = [dict(phase=phase, monotonicSeconds=tick, freeBytes=40*m.telemetry.GIB) for phase,tick in
                            [('pre-baseline',0),('post-baseline',32),('rollin',34),('after-rollin',36)]]
                    if mode == 'missing-baseline': gpu = gpu[1:]
                    if mode == 'missing-middle': del gpu[5:7]
                    if mode == 'missing-final': gpu = gpu[:-1]
                    if mode == 'low-gpu': gpu[-2]['freeBytes'] = 0
                    if mode == 'low-disk': disk[2]['freeBytes'] = 0
                    if mode == 'reordered-disk': disk[1]['monotonicSeconds'] = 33.5
                    (monitor / 'telemetry.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in gpu))
                    (monitor / 'disk.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in disk))
                    (monitor / 'frozen-inputs.json').write_text(json.dumps(frozen))
                    trial.mkdir(); (trial / 'inputs.json').write_text(json.dumps({'files': {'wrong':'hash'} if mode == 'wrong-input' else frozen}))
                    (trial / 'report.json').write_text(json.dumps(report))
                    files = {name:'sha' for name in ('inputs.json','report.json',*[f'monitor-{a}/{x}' for a in ('student','teacher') for x in ('invocation.json','supervisor-result.json')],*[f'{a}/{x}' for a in ('student','teacher') for x in ('report.json','data.bin','map.bin')])}
                    if mode == 'bad-inventory': files.pop('teacher/map.bin')
                    (monitor / 'evidence.json').write_text(json.dumps({'status':'diagnostic_only','report': {'status':'wrong'} if mode=='wrong-report' else report,'files':files}))
                    if mode == 'bad-outer': return dict(clean, processGroup=True)
                    return clean
                with mock.patch.object(m.pilot, 'P', root), mock.patch.object(m.pilot, 'OUTPUT', trial), \
                     mock.patch.object(m.pilot.standalone, 'require_dedicated_process'), mock.patch.object(m, 'require_disk'), \
                     mock.patch.object(m.pilot, 'sha', return_value='sha'), mock.patch.object(m.pilot.base.hidden, 'supervise', side_effect=supervise):
                    if mode == 'ok':
                        self.assertEqual(m.launch(), report)
                        self.assertTrue((root/'l5-teacher-rollin-pilot-monitored-v1/completion.json').exists())
                    else:
                        with self.assertRaises((RuntimeError, ValueError)): m.launch()
                        self.assertFalse((root/'l5-teacher-rollin-pilot-monitored-v1/completion.json').exists())

    def test_final_inventory_rejects_deleted_or_modified_data(self):
        for mode in ('ok', 'deleted', 'changed', 'changed-input'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); trial = root / 'pilot'; trial.mkdir(); output = root / 'monitor'; output.mkdir()
                (trial / 'student').mkdir(); (trial / 'teacher').mkdir()
                (trial / 'student/data.bin').write_bytes(b'student data')
                (trial / 'teacher/data.bin').write_bytes(b'teacher data')
                report = {'status': 'diagnostic_only'}; (trial / 'report.json').write_text(json.dumps(report))
                frozen = {'source': 'original'}; (output / 'frozen-inputs.json').write_text(json.dumps(frozen))
                (output / 'evidence.json').write_text(json.dumps({'status': 'diagnostic_only', 'report': report, 'files': m.inventory(trial)}))
                if mode == 'deleted': (trial / 'teacher/data.bin').unlink()
                if mode == 'changed': (trial / 'student/data.bin').write_bytes(b'different')
                pins = {'source': 'changed'} if mode == 'changed-input' else frozen
                with mock.patch.object(m.pilot, 'OUTPUT', trial), mock.patch.object(m.pilot, 'pin_inputs', return_value=pins):
                    if mode == 'ok': self.assertEqual(m.final_check(output, m.pilot.sha(output / 'evidence.json')), {'status': 'final_inventory_verified'})
                    else:
                        with self.assertRaises(ValueError): m.final_check(output, m.pilot.sha(output / 'evidence.json'))

    def test_per_arm_supervisor_and_intended_command(self):
        clean = {'clientExit':0,'signal':None,'timedOut':False,'remainingWorkersTerminated':False,'processGroup':123}
        for mode in ('ok','wrong-command','timeout','wrong-input','wrong-report'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp); frozen={'input':'hash'}; report={'status':'diagnostic_only'}
                (root/'inputs.json').write_text(json.dumps({'files':{} if mode=='wrong-input' else frozen,'seeds':list(m.pilot.SEEDS)}))
                (root/'report.json').write_text(json.dumps({'status':'wrong'} if mode=='wrong-report' else report))
                for arm in ('student','teacher'):
                    directory=root/f'monitor-{arm}'; directory.mkdir()
                    command=m.pilot.command(arm, root/arm)
                    if mode=='wrong-command' and arm=='teacher': command.append('--blackout')
                    (directory/'invocation.json').write_text(json.dumps({'argv':command,'environment':m.environment(),'wallSeconds':600}))
                    (directory/'supervisor-result.json').write_text(json.dumps(dict(clean,timedOut=True) if mode=='timeout' and arm=='student' else clean))
                with mock.patch.object(m.pilot,'OUTPUT',root), mock.patch.object(m.pilot,'audit_arm',return_value={}), \
                     mock.patch.object(m.pilot,'compare',return_value=report):
                    if mode=='ok': self.assertEqual(m.verify_pilot(frozen),report)
                    else:
                        with self.assertRaises(ValueError): m.verify_pilot(frozen)

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
            subprocess.Popen.wait=wait;m.pilot.pin_inputs=lambda:{};m.require_disk=lambda gib:None;m.sample_disk=lambda stream,phase,gib: (_ for _ in ()).throw(RuntimeError('disk unavailable')) if mode=='disk' and phase=='rollin' else None;m.baseline=lambda log:None;m.WORKER_SECONDS=.1
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


if __name__ == '__main__': unittest.main()
