#!/usr/bin/env python3
"""CPU-only tests for the disabled heading-trainer monitor."""
import importlib.util
import hashlib
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

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('trainer_monitor', ROOT / 'flex/tests/monitored-heading-trainer.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


class TrainerMonitorTest(unittest.TestCase):
    def test_disk_guard_and_disabled_entrypoint(self):
        with mock.patch.object(m.shutil, 'disk_usage', return_value=SimpleNamespace(free=40 * m.telemetry.GIB - 1)):
            with self.assertRaisesRegex(RuntimeError, '40 GiB'): m.require_disk()
        result = subprocess.run([sys.executable, '-I', str(ROOT / 'flex/tests/monitored-heading-trainer.py')], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Disabled pending independent review', result.stderr)

    def test_disk_rechecked_after_baseline_before_spawn(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(m, 'require_disk', side_effect=[None, RuntimeError('disk fell')]), \
                 mock.patch.object(m.telemetry, 'baseline'), mock.patch.object(m.subprocess, 'Popen') as popen:
                with self.assertRaisesRegex(RuntimeError, 'disk fell'): m.monitor_worker(tmp)
                popen.assert_not_called()
            self.assertEqual(json.loads((Path(tmp) / 'monitor-result.json').read_text())['status'], 'failed')

    def test_preflight_rejects_missing_inputs_and_existing_outputs(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(m, 'P', Path(tmp)):
            with self.assertRaisesRegex(ValueError, 'pilot report is missing'): m.require_trainer_inputs()
            pilot = Path(tmp) / 'search-dagger-heading-pilot'; pilot.mkdir()
            (pilot / 'pilot-report.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'build receipt is missing'): m.require_trainer_inputs()
            build = Path(tmp) / 'search-dagger-heading-trainer-build'; build.mkdir()
            (build / 'inputs.json').write_text('{}')
            m.require_trainer_inputs()
            (Path(tmp) / 'search-dagger-heading-trainer-pilot').mkdir()
            with self.assertRaises(FileExistsError): m.require_trainer_inputs()

    def test_success_worker_uses_original_supervisor_command(self):
        process = SimpleNamespace(pid=123, returncode=0, poll=lambda: 0)
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(m, 'require_disk'), mock.patch.object(m.telemetry, 'baseline'), \
                 mock.patch.object(m.telemetry, 'sample', return_value={'freeBytes': 8 * m.telemetry.GIB}), \
                 mock.patch.object(m.subprocess, 'Popen', return_value=process) as popen, \
                 mock.patch.object(m.os, 'pidfd_open', return_value=456), mock.patch.object(m.os, 'close'):
                m.monitor_worker(tmp)
            self.assertEqual(popen.call_args.args[0], [m.sys.executable, '-I', str(m.TRAINER)])
            self.assertEqual(json.loads((Path(tmp) / 'monitor-result.json').read_text())['status'], 'passed')

    def test_outer_success_requires_passing_pilot_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); pilot = base / 'search-dagger-heading-trainer-pilot'; pilot.mkdir()
            def supervise(command, monitor, env, timeout):
                (monitor.parent / 'monitor-result.json').write_text('{"status":"passed"}')
                (monitor.parent / 'telemetry.jsonl').write_text('{}\n')
                (monitor / 'supervisor-result.json').write_text('{}')
                return {'signal': None, 'timedOut': False, 'clientExit': 0, 'remainingWorkersTerminated': False}
            def load(name, path):
                if name == 'hidden_supervisor': return SimpleNamespace(supervise=supervise)
                sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
                return SimpleNamespace(base=SimpleNamespace(sha=sha),
                                       verify_small_pilot=lambda require_monitor: json.loads((pilot / 'comparison.json').read_text()))
            with mock.patch.object(m, 'P', base), mock.patch.object(m, 'require_disk'), \
                 mock.patch.object(m, 'require_trainer_inputs'), mock.patch.object(m, 'load', side_effect=load):
                with mock.patch.object(m, 'MONITORED', base / 'first'):
                    with self.assertRaises(FileNotFoundError): m.launch(base / 'first')
                self.assertFalse((base / 'first/completion.json').exists())
                (pilot / 'comparison.json').write_text('{"status":"failed","differences":[]}')
                with mock.patch.object(m, 'MONITORED', base / 'second'):
                    with self.assertRaisesRegex(RuntimeError, 'evidence did not pass'): m.launch(base / 'second')
                self.assertFalse((base / 'second/completion.json').exists())
                (pilot / 'comparison.json').write_text('{"status":"passed","differences":[]}')
                with mock.patch.object(m, 'MONITORED', base / 'third'): m.launch(base / 'third')
                self.assertEqual(json.loads((base / 'third/completion.json').read_text())['status'], 'passed')

    def test_after_training_telemetry_failure_blocks_completion(self):
        process = SimpleNamespace(pid=123, returncode=0, poll=lambda: 0)
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(m, 'require_disk'), mock.patch.object(m.telemetry, 'baseline'), \
                 mock.patch.object(m.telemetry, 'sample', side_effect=RuntimeError('telemetry unavailable')), \
                 mock.patch.object(m.subprocess, 'Popen', return_value=process), \
                 mock.patch.object(m.os, 'pidfd_open', return_value=456), mock.patch.object(m.os, 'close'):
                with self.assertRaisesRegex(RuntimeError, 'telemetry unavailable'): m.monitor_worker(tmp)
            self.assertEqual(json.loads((Path(tmp) / 'monitor-result.json').read_text())['status'], 'failed')
            self.assertFalse((Path(tmp) / 'completion.json').exists())

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
                return {'freeBytes':m.telemetry.GIB}
            original_pidfd=os.pidfd_open
            def pidfd(pid):
                if mode=='pidfd': ready();raise OSError('fixture pidfd failure')
                return original_pidfd(pid)
            # The fixture worker ignores SIGTERM; shorten only the wait passed to Popen.wait.
            original_wait=subprocess.Popen.wait
            def wait(self,timeout=None): return original_wait(self,timeout=min(timeout,.1) if timeout is not None else None)
            subprocess.Popen.wait=wait;m.require_disk=lambda:None;m.telemetry.baseline=lambda log:None
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
            for mode in ('low', 'telemetry', 'kill-monitor', 'pidfd'):
                with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                    args = [sys.executable, '-c', outer_code, str(ROOT / 'flex/tests/run-physical-hidden-trial.py'),
                            tmp, monitor_code, str(ROOT / 'flex/tests/monitored-heading-trainer.py'), mode, worker_code, child_code]
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
