#!/usr/bin/env python3
"""CPU fixtures for the diagnostic ptrace experiment."""
import base64
import importlib.util
import os
import signal
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('exec_probe', ROOT / 'datasets/visual-control/chase-v1/levels/probe-exec-events.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


@unittest.skip('probe disabled pending fork-event cleanup fix')
class ProbeTest(unittest.TestCase):
    def test_rapid_fork_exec_preserves_binary_and_empty_arguments(self):
        program = ('import os\n'
                   'children=[]\n'
                   'for i in range(12):\n'
                   ' p=os.fork()\n'
                   ' if p==0: os.execve(b"/bin/true",[b"probe",b"",b"\\xff"],{})\n'
                   ' children.append(p)\n'
                   'for p in children:\n'
                   ' _,status=os.waitpid(p,0)\n'
                   ' if status: raise SystemExit(1)\n')
        result = probe.trace([os.fsencode(sys.executable), b'-c', program.encode()], timeout=10)
        self.assertEqual(result['status'], 'diagnostic_only')
        events = result['execEvents']
        self.assertEqual(len(events), 13)
        expected = [base64.b64encode(a).decode() for a in (b'probe', b'', b'\xff')]
        self.assertEqual(sum(event['argvBase64'] == expected for event in events), 12)

    def test_permission_denial_fails_closed(self):
        original = probe.ptrace
        def denied(request, pid, data=0):
            if request == probe.SETOPTIONS:
                raise PermissionError('synthetic denial')
            return original(request, pid, data)
        with mock.patch.object(probe, 'ptrace', side_effect=denied):
            with self.assertRaises(PermissionError):
                probe.trace([b'/bin/true'])

    def test_timeout_fails_closed(self):
        with self.assertRaises(TimeoutError):
            probe.trace([os.fsencode(sys.executable), b'-c', b'import time;time.sleep(30)'], timeout=.2)

    def test_unrelated_child_is_not_reaped(self):
        other = subprocess.Popen([sys.executable, '-c', 'pass'])
        try:
            probe.trace([b'/bin/true'])
            self.assertEqual(other.wait(timeout=2), 0)
        finally:
            if other.poll() is None:
                other.kill(); other.wait()

    def test_real_sigtrap_is_delivered(self):
        with self.assertRaises(RuntimeError):
            probe.trace([os.fsencode(sys.executable), b'-c', b'import os,signal;os.kill(os.getpid(),signal.SIGTRAP)'])

    def test_thread_clone_is_rejected(self):
        script = b'import threading,time;t=threading.Thread(target=lambda: time.sleep(5));t.start();t.join()'
        with self.assertRaisesRegex(RuntimeError, 'clone/thread tracing is unsupported'):
            probe.trace([os.fsencode(sys.executable), b'-c', script])

    def test_interrupt_after_fork_and_repeated_cleanup_signals(self):
        fork = os.fork; kill = os.kill; created = []
        def interrupted_fork():
            child = fork()
            if child:
                created.append(child)
                kill(os.getpid(), signal.SIGTERM)
            return child
        def repeated_kill(pid, sig):
            if sig == signal.SIGKILL:
                kill(os.getpid(), signal.SIGTERM)
                kill(os.getpid(), signal.SIGTERM)
            return kill(pid, sig)
        with mock.patch.object(probe.os, 'fork', side_effect=interrupted_fork), mock.patch.object(probe.os, 'kill', side_effect=repeated_kill):
            with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                probe.trace([b'/bin/true'])
        self.assertEqual(len(created), 1)
        self.assertFalse(Path(f'/proc/{created[0]}').exists())


class DisabledTest(unittest.TestCase):
    def test_probe_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, 'pending fork-event cleanup race'):
            probe.trace([b'/bin/true'])


if __name__ == '__main__':
    unittest.main()
