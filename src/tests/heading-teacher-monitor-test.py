#!/usr/bin/env python3
"""CPU-only lifecycle checks for the disabled teacher monitor."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('teacher_monitor_fixture', ROOT / 'flex/tests/monitored-heading-teacher-v1.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


class MonitorTests(unittest.TestCase):
    def test_preflight_and_snapshot_use_bounded_subreaper(self):
        def fake(argv, directory, env, wall_seconds):
            self.assertEqual(wall_seconds, 1800)
            (directory / 'client.log').write_text('{"status":"fixture"}')
            return {'clientExit': 0, 'signal': None, 'timedOut': False, 'remainingWorkersTerminated': False}
        with mock.patch.object(m.frozen.base.hidden, 'supervise', side_effect=fake) as supervised:
            self.assertEqual(m.verify_plan(), {'status': 'fixture'})
            self.assertEqual(m.snapshot_evidence(), {'status': 'fixture'})
        self.assertEqual(supervised.call_count, 2)
        bad = {'clientExit': -15, 'signal': None, 'timedOut': True, 'remainingWorkersTerminated': False}
        def timeout(argv, directory, env, wall_seconds):
            (directory / 'client.log').write_text('timed out'); return bad
        with mock.patch.object(m.frozen.base.hidden, 'supervise', side_effect=timeout):
            with self.assertRaisesRegex(RuntimeError, 'bounded teacher verification failed'): m.verify_plan()

    def test_baseline_and_disk_guards(self):
        with mock.patch.object(m.shutil, 'disk_usage', return_value=SimpleNamespace(free=34 * m.frozen.GIB - 1)):
            import io
            with self.assertRaisesRegex(RuntimeError, '34 GiB'): m.disk_sample(io.StringIO(), 'selection')
        with mock.patch.object(m.shutil, 'disk_usage', side_effect=OSError('unavailable')):
            import io
            with self.assertRaisesRegex(RuntimeError, 'telemetry unavailable'): m.disk_sample(io.StringIO(), 'selection')

    def test_exact_inner_worker_and_final_sample(self):
        process = SimpleNamespace(pid=123, returncode=0, poll=lambda: 0)
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(m.frozen.base, 'require_capacity'), mock.patch.object(m, 'baseline'), \
                 mock.patch.object(m, 'disk_sample') as disk, \
                 mock.patch.object(m.telemetry, 'sample', return_value={'freeBytes': 8 * m.frozen.GIB}), \
                 mock.patch.object(m.subprocess, 'Popen', return_value=process) as popen, \
                 mock.patch.object(m.os, 'pidfd_open', return_value=456), mock.patch.object(m.os, 'close'):
                m.monitor_worker(tmp)
            command = popen.call_args.args[0]
            self.assertEqual(command[:3], [sys.executable, '-I', '-c'])
            self.assertEqual(command[-1], str(m.frozen.RUNNER)); self.assertIn('m.run()', command[3])
            self.assertEqual([call.args[1] for call in disk.call_args_list],
                             ['pre-baseline', 'post-baseline', 'selection', 'after-selection'])
            self.assertEqual(json.loads((Path(tmp) / 'monitor-result.json').read_text())['status'], 'passed')

    def test_nested_monitor_abort_reaps_detached_children(self):
        child = 'import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)'
        worker = ('import os,signal,subprocess,sys,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);'
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
                if mode=='gpu-loss': raise RuntimeError('GPU telemetry unavailable')
                return {'freeBytes':m.frozen.GIB if mode=='gpu-low' else 8*m.frozen.GIB}
            def disk(stream,phase):
                if phase=='selection':
                    ready()
                    if mode=='disk-loss': raise RuntimeError('disk telemetry unavailable')
                    if mode=='disk-low': raise RuntimeError('free disk below 34 GiB')
            original_pidfd=os.pidfd_open
            def pidfd(pid):
                if mode=='pidfd': ready();raise OSError('fixture pidfd failure')
                return original_pidfd(pid)
            original_wait=subprocess.Popen.wait
            def wait(self,timeout=None): return original_wait(self,timeout=min(timeout,.1) if timeout is not None else None)
            subprocess.Popen.wait=wait;m.frozen.base.require_capacity=lambda *a:None;m.baseline=lambda log:None
            m.telemetry.sample=sample;m.disk_sample=disk;m.subprocess.Popen=spawn;m.os.pidfd_open=pidfd
            m.monitor_worker(output)
        ''')
        outer_code = textwrap.dedent('''
            import importlib.util,json,os,sys
            from pathlib import Path
            s=importlib.util.spec_from_file_location('h',sys.argv[1]);h=importlib.util.module_from_spec(s);s.loader.exec_module(h)
            result=h.supervise([sys.executable,'-c',sys.argv[3],sys.argv[4],sys.argv[2],sys.argv[5],sys.argv[6],sys.argv[7]],Path(sys.argv[2]),os.environ.copy(),15)
            print(json.dumps(result))
        ''')
        other = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(60)'])
        try:
            for mode in ('gpu-low', 'gpu-loss', 'disk-low', 'disk-loss', 'kill-monitor', 'pidfd'):
                with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                    args = [sys.executable, '-c', outer_code, str(ROOT / 'flex/tests/run-physical-hidden-trial.py'),
                            tmp, monitor_code, str(ROOT / 'flex/tests/monitored-heading-teacher-v1.py'), mode, worker, child]
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
