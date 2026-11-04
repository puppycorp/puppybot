#!/usr/bin/env python3
"""CPU-only resource-monitor and detached-process lifecycle fixtures."""
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
spec = importlib.util.spec_from_file_location('hybrid_monitor', HERE / 'monitor.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


class MonitorTests(unittest.TestCase):
    def test_disabled_cli_and_disk_guard(self):
        result = subprocess.run([sys.executable, '-I', str(HERE / 'monitor.py')], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Disabled pending', result.stderr)
        with mock.patch.object(m.shutil, 'disk_usage', return_value=type('D', (), {'free': 33 * m.telemetry.GIB})()):
            with self.assertRaisesRegex(RuntimeError, '34 GiB'): m.require_disk(34)

    def test_disk_baseline_failure_does_not_spawn(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(m, 'sample_disk', side_effect=[None, RuntimeError('disk fell')]), \
             mock.patch.object(m, 'baseline'), mock.patch.object(m.subprocess, 'Popen') as popen:
            with self.assertRaisesRegex(RuntimeError, 'disk fell'): m.monitor_worker(tmp, 'control')
            popen.assert_not_called()
            self.assertEqual(json.loads((Path(tmp) / 'monitor-result.json').read_text())['status'], 'failed')

    def test_completion_requires_passing_bound_audit_and_arm(self):
        for mode in ('ok', 'wrong-arm', 'wrong-audit', 'bad-audit-status', 'bad-monitor', 'changed-pin', 'missing-baseline', 'missing-final', 'low-gpu', 'low-disk', 'empty-log', 'malformed-log', 'missing-middle', 'disk-before-gpu', 'active-gap', 'final-gap', 'baseline-disk-after-active', 'bad-outer-status'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                trial = root / 'hybrid-physical-eval-v1-control'
                outcome = {'status': 'diagnostic_only', 'outcome': 'collector_incomplete_without_capture'}
                clean = {'clientExit': 0, 'timedOut': False, 'signal': None,
                         'remainingWorkersTerminated': False, 'processGroup': 123}
                def supervise(command, directory, env, timeout):
                    monitor = directory.parent
                    (monitor / 'monitor-result.json').write_text(json.dumps({'status': 'failed' if mode == 'bad-monitor' else 'passed'}))
                    gpu = [dict(phase=phase, monotonicSeconds=tick, busyPercent=0,
                                totalBytes=10*m.telemetry.GIB, usedBytes=m.telemetry.GIB,
                                freeBytes=9*m.telemetry.GIB) for phase, tick in
                           [*[("baseline", tick) for tick in range(1, 32)], ('hybrid', 33), ('after-hybrid', 35)]]
                    disk = [dict(phase=phase, monotonicSeconds=tick, freeBytes=40*m.telemetry.GIB)
                            for phase, tick in [('pre-baseline', 0), ('post-baseline', 32), ('hybrid', 34), ('after-hybrid', 36)]]
                    if mode == 'missing-baseline': gpu = gpu[1:]
                    if mode == 'missing-final': gpu = gpu[:-1]
                    if mode == 'low-gpu': gpu[-2]['freeBytes'] = 0
                    if mode == 'missing-middle': del gpu[5:7]
                    if mode == 'active-gap': gpu[-2]['monotonicSeconds'] = 34
                    if mode == 'final-gap': gpu[-1]['monotonicSeconds'] = 36; disk[-1]['monotonicSeconds'] = 37
                    if mode == 'disk-before-gpu': disk[2]['monotonicSeconds'] = 32.5
                    if mode == 'baseline-disk-after-active': disk[1]['monotonicSeconds'] = 33.5
                    if mode == 'low-disk': disk[2]['freeBytes'] = 0
                    if mode == 'empty-log': gpu = []
                    (monitor / 'telemetry.jsonl').write_text('broken json\n' if mode == 'malformed-log' else ''.join(json.dumps(x)+'\n' for x in gpu))
                    (monitor / 'disk.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in disk))
                    (trial / 'audit-monitor').mkdir(parents=True)
                    (trial / 'launch.json').write_text(json.dumps({'arm': 'treatment' if mode == 'wrong-arm' else 'control', 'weightsSHA256': 'weights', 'policySHA256': 'policy', 'sourcePins': base_pins}))
                    (trial / 'outcome.json').write_text(json.dumps(outcome))
                    (trial / 'audit-monitor/client.log').write_text(json.dumps({'status': 'censored'} if mode == 'wrong-audit' else outcome))
                    status = dict(clean)
                    if mode == 'bad-audit-status': status['timedOut'] = True
                    (trial / 'audit-monitor/supervisor-result.json').write_text(json.dumps(status))
                    if mode == 'bad-outer-status': return dict(clean, processGroup=True)
                    return clean
                base_pins = {str(m.hybrid.PACKAGE / 'control/weights.bin'): 'weights', str(m.hybrid.PACKAGE / 'control/policy'): 'policy'}
                pins = [base_pins, dict(base_pins, marker='changed') if mode == 'changed-pin' else base_pins]
                with mock.patch.object(m.hybrid, 'P', root), mock.patch.object(m.hybrid.guard, 'require_dedicated_process'), \
                     mock.patch.object(m, 'require_disk'), mock.patch.object(m.hybrid, 'pins', side_effect=pins), \
                     mock.patch.object(m.hybrid.hidden, 'sha', return_value='sha'), \
                     mock.patch.object(m.hybrid.hidden, 'supervise', side_effect=supervise):
                    if mode == 'ok':
                        self.assertEqual(m.launch('control'), outcome)
                        self.assertTrue((root / 'hybrid-physical-eval-monitored-v1-control/completion.json').is_file())
                    else:
                        with self.assertRaises((RuntimeError, ValueError)): m.launch('control')
                        self.assertFalse((root / 'hybrid-physical-eval-monitored-v1-control/completion.json').exists())

    def test_command_and_no_overwrite(self):
        self.assertEqual(m.worker_command('control')[-2:], [str(HERE / 'run.py'), 'control'])
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(m.hybrid, 'P', Path(tmp)), \
             mock.patch.object(m.hybrid.guard, 'require_dedicated_process'), mock.patch.object(m, 'require_disk'):
            (Path(tmp) / 'hybrid-physical-eval-v1-control').mkdir()
            with self.assertRaises(FileExistsError): m.launch('control')

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
                return {'freeBytes':(8 if mode=='timeout' else 1)*m.telemetry.GIB}
            original_pidfd=os.pidfd_open
            def pidfd(pid):
                if mode=='pidfd': ready();raise OSError('fixture pidfd failure')
                return original_pidfd(pid)
            # The fixture worker ignores SIGTERM; shorten only the wait passed to Popen.wait.
            original_wait=subprocess.Popen.wait
            def wait(self,timeout=None): return original_wait(self,timeout=min(timeout,.1) if timeout is not None else None)
            subprocess.Popen.wait=wait;m.require_disk=lambda gib:None;m.sample_disk=lambda stream,phase,gib: (_ for _ in ()).throw(RuntimeError('disk unavailable')) if mode=='disk' and phase=='hybrid' else None;m.baseline=lambda log:None;m.WORKER_SECONDS=.1
            m.telemetry.sample=sample;m.subprocess.Popen=spawn;m.os.pidfd_open=pidfd
            m.monitor_worker(output,'control')
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
