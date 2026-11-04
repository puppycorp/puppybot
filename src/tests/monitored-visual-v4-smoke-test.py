#!/usr/bin/env python3
"""CPU-only tests for the disabled GPU telemetry supervisor."""
import importlib.util
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('monitored_smoke', ROOT / 'flex/tests/monitored-visual-v4-smoke.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def row(busy=3, free=8):
    return {'busyPercent': busy, 'totalBytes': 16 * m.GIB, 'usedBytes': (16 - free) * m.GIB, 'freeBytes': free * m.GIB}


class FakeTime:
    def __init__(self): self.value = 0
    def clock(self): return self.value
    def sleep(self, seconds): self.value += seconds


class FakeProcess:
    pid = 123
    returncode = None
    def poll(self): return self.returncode
    def wait(self, timeout=None):
        self.returncode = -signal.SIGTERM
        return self.returncode


class MonitorTest(unittest.TestCase):
    def test_baseline_duration_and_rejection(self):
        clock = FakeTime(); log = io.StringIO()
        m.baseline(log, lambda _: row(), clock.sleep, clock.clock)
        self.assertEqual(clock.value, 30)
        self.assertEqual(len(log.getvalue().splitlines()), 31)
        with self.assertRaisesRegex(RuntimeError, 'below 6 GiB'):
            m.baseline(io.StringIO(), lambda _: row(free=5), clock.sleep, clock.clock)
        with self.assertRaisesRegex(RuntimeError, 'five consecutive'):
            m.baseline(io.StringIO(), lambda _: row(busy=11), clock.sleep, clock.clock)

    def test_telemetry_validation_and_error_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            device = Path(tmp) / m.EXPECTED_PCI; device.mkdir()
            (device / 'gpu_busy_percent').write_text('3')
            (device / 'mem_info_vram_total').write_text('100')
            (device / 'mem_info_vram_used').write_text('101')
            with self.assertRaises(ValueError): m.telemetry(device)
        log = io.StringIO()
        with self.assertRaisesRegex(RuntimeError, 'unavailable'):
            m.sample(log, 'smoke', lambda _: (_ for _ in ()).throw(OSError('disconnected')))
        self.assertEqual(json.loads(log.getvalue())['error'], 'disconnected')

    def test_low_vram_and_telemetry_failure_signal_only_pidfd(self):
        for failure in ('low', 'unavailable'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                process = FakeProcess(); sent = []
                def observe(stream, phase):
                    if failure == 'low': return row(free=1)
                    raise RuntimeError('GPU telemetry unavailable')
                with mock.patch.object(m, 'baseline'), mock.patch.object(m, 'sample', side_effect=observe), \
                     mock.patch.object(m.subprocess, 'Popen', return_value=process), \
                     mock.patch.object(m.os, 'pidfd_open', return_value=456), mock.patch.object(m.os, 'close'), \
                     mock.patch.object(m.signal, 'pidfd_send_signal', side_effect=lambda fd, sig: sent.append((fd, sig))):
                    with self.assertRaises(RuntimeError): m.monitor_worker('/pilot', '/matrix', tmp)
                self.assertEqual(sent, [(456, signal.SIGTERM)])

    def test_main_entrypoint_remains_disabled(self):
        result = m.subprocess.run([m.sys.executable, '-I', str(ROOT / 'flex/tests/monitored-visual-v4-smoke.py')],
                                  capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Disabled pending independent review', result.stderr)

    def test_real_nested_cleanup_preserves_unrelated_process(self):
        child_code = 'import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)'
        worker_code = ('import os,signal,subprocess,sys,time;'
                       'signal.signal(signal.SIGTERM,signal.SIG_IGN);'
                       'p=subprocess.Popen([sys.executable,"-c",sys.argv[2]],start_new_session=True);'
                       'open(sys.argv[1],"w").write(str(os.getpid())+" "+str(p.pid));time.sleep(30)')
        monitor_code = textwrap.dedent('''
            import importlib.util,os,signal,subprocess,sys,time
            from pathlib import Path
            s=importlib.util.spec_from_file_location('m',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
            output=Path(sys.argv[2]);mode=sys.argv[3];pidfile=output/'workers.pid'
            original=m.subprocess.Popen
            def spawn(*args,**kwargs):
                return original([sys.executable,'-c',sys.argv[4],str(pidfile),sys.argv[5]],**kwargs)
            def wait_ready():
                until=time.monotonic()+4
                while not pidfile.exists() and time.monotonic()<until: time.sleep(.01)
                if not pidfile.exists(): raise RuntimeError('fixture worker did not start')
            def sample(stream,phase):
                wait_ready()
                if mode=='kill-monitor': os.kill(os.getpid(),signal.SIGKILL)
                if mode=='telemetry': raise RuntimeError('GPU telemetry unavailable')
                return {'freeBytes':m.GIB}
            original_pidfd=os.pidfd_open
            def pidfd(pid):
                if mode=='pidfd':
                    wait_ready()
                    raise OSError('fixture pidfd failure')
                return original_pidfd(pid)
            m.baseline=lambda log:None;m.sample=sample;m.subprocess.Popen=spawn;m.os.pidfd_open=pidfd;m.STOP_GRACE_SECONDS=.1
            m.monitor_worker('/pilot','/matrix',output)
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
                            tmp, monitor_code, str(ROOT / 'flex/tests/monitored-visual-v4-smoke.py'), mode, worker_code, child_code]
                    completed = subprocess.run(args, capture_output=True, text=True, timeout=25, check=True)
                    status = json.loads(completed.stdout)
                    self.assertNotEqual(status['clientExit'], 0)
                    self.assertIsNone(other.poll(), 'unrelated process was signaled')
                    for pid in map(int, (Path(tmp) / 'workers.pid').read_text().split()):
                        self.assertFalse(Path(f'/proc/{pid}').exists(), f'fixture process {pid} survived')
                    self.assertFalse((Path(tmp) / 'smoke/report.json').exists())
                    if mode != 'kill-monitor':
                        self.assertEqual(json.loads((Path(tmp) / 'monitor-result.json').read_text())['status'], 'failed')
        finally:
            other.terminate(); other.wait(timeout=5)


if __name__ == '__main__': unittest.main()
