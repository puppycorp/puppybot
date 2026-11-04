#!/usr/bin/env python3
"""CPU-only watchdog controls; never launches overlay preparation."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
source = ROOT / 'flex/tests/supervise-heading-overlays.py'
spec = importlib.util.spec_from_file_location('overlay_supervisor', source)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


class SupervisorTest(unittest.TestCase):
    def test_exit_code_semantics(self):
        clean = {'signal': None, 'timedOut': False, 'clientExit': 0, 'remainingWorkersTerminated': False, 'processGroup': 123}
        self.assertEqual(m.exit_code(clean), 0)
        for field, value, expected in (('clientExit', 23, 23), ('clientExit', -9, 137),
                                       ('signal', 15, 143), ('timedOut', True, 124),
                                       ('remainingWorkersTerminated', True, 1)):
            status = dict(clean); status[field] = value
            self.assertEqual(m.exit_code(status), expected)
        self.assertEqual(m.exit_code(dict(clean, clientExit=23, timedOut=True)), 124)
        self.assertEqual(m.exit_code(dict(clean, clientExit=23, signal=15)), 143)
        for key in ('signal', 'timedOut', 'remainingWorkersTerminated', 'processGroup'):
            missing = dict(clean); del missing[key]
            self.assertEqual(m.exit_code(missing), 1)
        for key, value in (('signal', True), ('timedOut', 0), ('remainingWorkersTerminated', 0), ('processGroup', True)):
            invalid = dict(clean); invalid[key] = value
            self.assertEqual(m.exit_code(invalid), 1)

    def test_dedicated_process_guard(self):
        with mock.patch.object(m.hidden.supervisor, 'children', return_value=[(123, 'S')]), \
             mock.patch.object(m.base, 'require_capacity') as capacity:
            with self.assertRaisesRegex(RuntimeError, 'without other children'): m.launch()
            capacity.assert_not_called()
        with mock.patch.object(m, 'native_task_count', return_value=2), \
             mock.patch.object(m.base, 'require_capacity') as capacity:
            with self.assertRaisesRegex(RuntimeError, 'dedicated process'): m.launch()
            capacity.assert_not_called()

    def test_child_status_and_pair_ready_gate(self):
        clean = {'signal': None, 'timedOut': False, 'clientExit': 0, 'remainingWorkersTerminated': False, 'processGroup': 123}
        for child, report, expected in ((23, None, 23), (0, None, 1),
                                        (0, {'status': 'paired_inputs_only', 'aggregateValidation': {'validationGames': 96}}, 0)):
            with self.subTest(child=child, report=report), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); output = root / 'output'; output.mkdir(); receipt = root / 'completion'; receipt.touch()
                if report is not None: (output / 'pair-ready.json').write_text(json.dumps(report))
                status = dict(clean, clientExit=child)
                # Pair-ready may exist only after the child runs; emulate that timing.
                pair = output / 'pair-ready.json'
                if pair.exists(): pair.unlink()
                def fake(*args):
                    if report is not None: pair.write_text(json.dumps(report))
                    return status, m.exit_code(status)
                with mock.patch.object(m, 'P', root), mock.patch.object(m, 'OUTPUT', output), \
                     mock.patch.object(m, 'MONITOR', root / 'monitor'), mock.patch.object(m, 'COLLECTION_RECEIPT', receipt), \
                     mock.patch.object(m.base, 'require_capacity'), mock.patch.object(m.hidden.supervisor, 'children', return_value=[]), \
                     mock.patch.object(m, 'supervise', side_effect=fake):
                    self.assertEqual(m.launch(), expected)
                saved = json.loads((root / 'monitor/result.json').read_text())
                self.assertEqual(saved['childExit'], child); self.assertEqual(saved['wrapperExit'], expected)

    def test_timeout_reaps_detached_child_and_preserves_unrelated_sibling(self):
        grandchild = 'import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)'
        child = ('import os,signal,subprocess,sys,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);'
                 'p=subprocess.Popen([sys.executable,"-c",sys.argv[2]],start_new_session=True);'
                 'open(sys.argv[1],"w").write(str(os.getpid())+" "+str(p.pid));time.sleep(30)')
        outer = textwrap.dedent('''
            import importlib.util,json,os,sys
            from pathlib import Path
            s=importlib.util.spec_from_file_location('w',sys.argv[1]);w=importlib.util.module_from_spec(s);s.loader.exec_module(w)
            result,code=w.supervise(Path(sys.argv[2]),[sys.executable,'-c',sys.argv[4],sys.argv[3],sys.argv[5]],os.environ.copy(),.5)
            print(json.dumps({'status':result,'exit':code}))
        ''')
        other = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(30)'])
        try:
            with tempfile.TemporaryDirectory() as tmp:
                pidfile = Path(tmp) / 'workers.pid'
                result = subprocess.run([sys.executable, '-c', outer, str(source), tmp, str(pidfile), child, grandchild],
                                        capture_output=True, text=True, timeout=20, check=True)
                saved = json.loads(result.stdout)
                self.assertEqual(saved['exit'], 124); self.assertTrue(saved['status']['timedOut'])
                self.assertIsNone(other.poll(), 'unrelated sibling was signaled')
                for pid in map(int, pidfile.read_text().split()): self.assertFalse(Path(f'/proc/{pid}').exists())
        finally:
            other.terminate(); other.wait(timeout=5)

    def test_real_nonzero_child_code_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            status, code = m.supervise(Path(tmp), [sys.executable, '-I', '-c', 'raise SystemExit(23)'],
                                       {'PATH': '/usr/bin:/bin'}, 3)
            self.assertEqual(status['clientExit'], 23)
            self.assertEqual(code, 23)
            self.assertEqual(json.loads((Path(tmp) / 'supervisor-result.json').read_text())['clientExit'], 23)

    def test_timed_out_child_can_trap_term_and_exit_nonzero(self):
        code = 'import signal,sys,time;signal.signal(signal.SIGTERM,lambda *_:sys.exit(23));time.sleep(30)'
        with tempfile.TemporaryDirectory() as tmp:
            status, wrapper = m.supervise(Path(tmp), [sys.executable, '-I', '-c', code], {'PATH': '/usr/bin:/bin'}, .3)
            self.assertTrue(status['timedOut']); self.assertEqual(status['clientExit'], 23)
            self.assertEqual(wrapper, 124)

    def test_entrypoint_disabled(self):
        result = subprocess.run([sys.executable, '-I', str(source)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Disabled pending independent review', result.stderr)


if __name__ == '__main__': unittest.main()
