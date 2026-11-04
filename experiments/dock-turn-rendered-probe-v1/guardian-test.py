#!/usr/bin/env python3
"""CPU-only process tests: dead coordinators, escaped children and disk floors."""
import fcntl
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
GIB = 1024**3


def wait_for(predicate, seconds=8):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            value = predicate()
            if value: return value
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        time.sleep(.02)
    raise AssertionError('timed out waiting for fixture')


class GuardianTest(unittest.TestCase):
    def test_normal_coordinator_completion_releases_lock(self):
        with tempfile.TemporaryDirectory(prefix='turn-guardian-normal-') as temp:
            root = Path(temp); lock = root / 'lock'; lock.write_text(''); marker = root / 'ready'
            child_code = 'import pathlib,sys,time;time.sleep(.12);pathlib.Path(sys.argv[1]).write_text("ok");time.sleep(.12)'
            guard_code = ('''import importlib.util,json,os,sys
s=importlib.util.spec_from_file_location('guard',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
out,lock,marker,parent,argv=sys.argv[2],sys.argv[3],sys.argv[4],int(sys.argv[5]),json.loads(sys.argv[6])
def resources(): return {'freeBytes':40*1024**3,'gpuFreeBytes':4*1024**3,'baselinePassed':os.path.exists(marker)}
m.run(out,lock,argv,{'PATH':'/usr/bin:/bin'},parent,resources,interval=.03,grace=.1)
''')
            command = [sys.executable, '-c', child_code, str(marker)]
            process = subprocess.Popen([sys.executable, '-I', '-c', guard_code, str(HERE / 'guardian.py'),
                str(root), str(lock), str(marker), str(os.getpid()), json.dumps(command)],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True)
            try:
                self.assertEqual(process.wait(timeout=8), 0, process.stderr.read().decode())
                result = json.loads((root / 'guardian-result.json').read_text())
                self.assertEqual(result['status'], 'passed'); self.assertFalse(result['descendantsTerminated'])
                rows = [json.loads(line) for line in (root / 'guardian-telemetry.jsonl').read_text().splitlines()]
                self.assertTrue(any(not row['baselinePassed'] for row in rows))
                self.assertTrue(any(row['baselinePassed'] for row in rows))
                with lock.open('a') as probe: fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                if process.poll() is None: process.kill(); process.wait()
                if process.stderr: process.stderr.close()

    def start(self, root, intermediate_parent=False):
        state = root / 'free'; state.write_text(str(40 * GIB))
        lock = root / 'lock'; lock.write_text('')
        escaped = root / 'escaped.pid'; coordinator = root / 'coordinator.pid'
        child_code = ('import os,signal,sys,time;'
                      'signal.signal(signal.SIGTERM,signal.SIG_IGN);'
                      'open(sys.argv[1],"w").write(str(os.getpid()));'
                      'time.sleep(60)')
        coordinator_code = ('import os,subprocess,sys,time;'
                            'subprocess.Popen([sys.executable,"-c",sys.argv[2],sys.argv[1]],start_new_session=True);'
                            'open(sys.argv[3],"w").write(str(os.getpid()));'
                            'time.sleep(60)')
        command = [sys.executable, '-c', coordinator_code, str(escaped), child_code, str(coordinator)]
        guard_code = ('''import importlib.util,json,os,sys
s=importlib.util.spec_from_file_location('guard',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
out,lock,state,parent,argv=sys.argv[2],sys.argv[3],sys.argv[4],int(sys.argv[5]),json.loads(sys.argv[6])
def resources(): return {'freeBytes':int(open(state).read()),'gpuFreeBytes':4*1024**3,'baselinePassed':False}
m.run(out,lock,argv,{'PATH':'/usr/bin:/bin'},parent,resources,interval=.03,grace=1.0)
''')
        guard_prefix = [sys.executable, '-I', '-c', guard_code, str(HERE / 'guardian.py'), str(root), str(lock), str(state)]
        if intermediate_parent:
            wrapper_code = ('''import json,os,subprocess,sys,time
args=json.loads(sys.argv[1]);args.extend([str(os.getpid()),sys.argv[2]])
subprocess.Popen(args,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
time.sleep(60)
''')
            argv = [sys.executable, '-I', '-c', wrapper_code, json.dumps(guard_prefix), json.dumps(command)]
        else:
            argv = guard_prefix + [str(os.getpid()), json.dumps(command)]
        process = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True)
        wait_for(lambda: escaped.is_file() and coordinator.is_file() and (root / 'guardian-launch.json').is_file())
        return process, lock, state, int(escaped.read_text()), int(coordinator.read_text())

    def assert_locked(self, lock):
        with lock.open('a') as probe:
            with self.assertRaises(BlockingIOError):
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_killed_coordinator_keeps_lock_until_escaped_child_reaped(self):
        with tempfile.TemporaryDirectory(prefix='turn-guardian-test-') as temp:
            root = Path(temp); process, lock, _, escaped, coordinator = self.start(root)
            try:
                self.assert_locked(lock)
                os.kill(coordinator, signal.SIGKILL)
                wait_for(lambda: any(json.loads(line)['phase'] == 'cleanup' for line in
                    (root / 'guardian-telemetry.jsonl').read_text().splitlines()))
                self.assert_locked(lock)
                self.assertEqual(process.wait(timeout=8), 0, process.stderr.read().decode())
                result = json.loads((root / 'guardian-result.json').read_text())
                self.assertEqual(result['status'], 'failed'); self.assertTrue(result['descendantsTerminated'])
                with self.assertRaises(ProcessLookupError): os.kill(escaped, 0)
                with lock.open('a') as probe: fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                if process.poll() is None: process.kill(); process.wait()
                if process.stderr: process.stderr.close()

    def test_emergency_floor_is_sampled_during_abort_and_escalates(self):
        with tempfile.TemporaryDirectory(prefix='turn-guardian-floor-') as temp:
            root = Path(temp); process, _, state, escaped, _ = self.start(root)
            try:
                state.write_text(str(33 * GIB))
                wait_for(lambda: any(json.loads(line)['phase'] == 'cleanup' for line in
                    (root / 'guardian-telemetry.jsonl').read_text().splitlines()))
                state.write_text(str(31 * GIB))
                self.assertEqual(process.wait(timeout=8), 0, process.stderr.read().decode())
                result = json.loads((root / 'guardian-result.json').read_text())
                self.assertEqual(result['status'], 'failed'); self.assertTrue(result['diskEmergency'])
                rows = [json.loads(line) for line in (root / 'guardian-telemetry.jsonl').read_text().splitlines()]
                self.assertTrue(any(row['phase'] == 'cleanup' and row['freeBytes'] < 32 * GIB for row in rows))
                with self.assertRaises(ProcessLookupError): os.kill(escaped, 0)
            finally:
                if process.poll() is None: process.kill(); process.wait()
                if process.stderr: process.stderr.close()

    def test_transient_baseline_drop_cannot_be_recovered_into_a_pass(self):
        with tempfile.TemporaryDirectory(prefix='turn-guardian-baseline-') as temp:
            root = Path(temp); process, _, state, escaped, _ = self.start(root)
            try:
                state.write_text(str(37 * GIB))
                wait_for(lambda: any(json.loads(line)['phase'] == 'active' and
                    json.loads(line)['freeBytes'] < 38 * GIB for line in
                    (root / 'guardian-telemetry.jsonl').read_text().splitlines()))
                state.write_text(str(40 * GIB))
                self.assertEqual(process.wait(timeout=8), 0, process.stderr.read().decode())
                result = json.loads((root / 'guardian-result.json').read_text())
                self.assertEqual(result['status'], 'failed')
                self.assertIn('floor breached', result['reason'])
                with self.assertRaises(ProcessLookupError): os.kill(escaped, 0)
            finally:
                if process.poll() is None: process.kill(); process.wait()
                if process.stderr: process.stderr.close()

    def test_parent_death_stops_coordinator_and_escaped_child(self):
        with tempfile.TemporaryDirectory(prefix='turn-guardian-parent-') as temp:
            root = Path(temp); process, lock, _, escaped, coordinator = self.start(root, intermediate_parent=True)
            try:
                self.assert_locked(lock); process.kill(); process.wait(timeout=3)
                wait_for(lambda: any(json.loads(line)['phase'] == 'cleanup' for line in
                    (root / 'guardian-telemetry.jsonl').read_text().splitlines()))
                self.assert_locked(lock)
                wait_for(lambda: (root / 'guardian-result.json').is_file())
                result = json.loads((root / 'guardian-result.json').read_text())
                self.assertEqual(result['status'], 'failed'); self.assertEqual(result['reason'], 'parent exited')
                self.assertTrue(result['descendantsTerminated'])
                with self.assertRaises(ProcessLookupError): os.kill(escaped, 0)
                with self.assertRaises(ProcessLookupError): os.kill(coordinator, 0)
                def lock_released():
                    with lock.open('a') as probe:
                        try: fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        except BlockingIOError: return False
                        return True
                wait_for(lock_released)
            finally:
                if process.poll() is None: process.kill(); process.wait()
                if process.stderr: process.stderr.close()


if __name__ == '__main__':
    unittest.main()
