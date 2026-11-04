#!/usr/bin/env python3
"""CPU controls for the heading pilot's outer wall-clock supervisor."""
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import json
import signal

ROOT = Path(__file__).resolve().parents[2]
p = ROOT / 'datasets/visual-control/chase-v1/levels/supervise-heading-pilot.py'
s = importlib.util.spec_from_file_location('heading_supervisor', p); m = importlib.util.module_from_spec(s); s.loader.exec_module(m)


class SupervisorTest(unittest.TestCase):
    def test_expected_success_and_bad_reports(self):
        good = {'signal': None, 'timedOut': False, 'clientExit': 0, 'remainingWorkersTerminated': False}
        m.require_terminal(good, {'status': 'passed', 'mode': 'pilot'})
        for report in ({'status': 'failed', 'mode': 'pilot'}, {'status': 'passed', 'mode': 'full'}, {}):
            with self.subTest(report=report), self.assertRaises(ValueError): m.require_terminal(good, report)
        for key, value in [('signal', 15), ('timedOut', True), ('clientExit', 1), ('remainingWorkersTerminated', True)]:
            status = dict(good); status[key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError): m.require_terminal(status, {'status': 'passed', 'mode': 'pilot'})

    def test_actual_watchdog_terminates_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            status = m.base.hidden.supervise([sys.executable, '-c', 'import time;time.sleep(30)'], output, os.environ.copy(), .1)
            self.assertTrue(status['timedOut'])
            self.assertFalse(Path(f"/proc/{status['processGroup']}").exists())
            self.assertTrue((output / 'supervisor-result.json').is_file())

    def test_watchdog_reaps_detached_descendant(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp); pidfile = output / 'child.pid'
            child = 'import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)'
            runner = ('import signal,subprocess,sys,time;'
                      'p=subprocess.Popen([sys.executable,"-c",sys.argv[2]],start_new_session=True);'
                      'open(sys.argv[1],"w").write(str(p.pid));'
                      'signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)')
            status = m.base.hidden.supervise([sys.executable, '-c', runner, str(pidfile), child], output, os.environ.copy(), .3)
            self.assertTrue(status['timedOut']); self.assertTrue(pidfile.exists())
            self.assertFalse(Path(f'/proc/{int(pidfile.read_text())}').exists())

    def test_nested_watchdog_and_repeated_cleanup_signals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); inner = root / 'inner'; inner.mkdir(); pidfile = root / 'workers.pid'
            child = 'import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)'
            worker = ('import os,signal,subprocess,sys,time;'
                      'p=subprocess.Popen([sys.executable,"-c",sys.argv[2]],start_new_session=True);'
                      'open(sys.argv[1],"w").write(str(os.getpid())+" "+str(p.pid));'
                      'signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)')
            inner_source = str(ROOT / 'flex/tests/run-physical-hidden-trial.py')
            code = ('import importlib.util,os,sys;from pathlib import Path;'
                    's=importlib.util.spec_from_file_location("inner",sys.argv[1]);'
                    'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);'
                    'm.supervise([sys.executable,"-c",sys.argv[4],sys.argv[3],sys.argv[5]],Path(sys.argv[2]),os.environ.copy(),30)')
            cleanup = m.base.hidden.supervisor.cleanup_descendants
            def signaled_cleanup():
                os.kill(os.getpid(), signal.SIGTERM); os.kill(os.getpid(), signal.SIGTERM)
                return cleanup()
            with mock.patch.object(m.base.hidden.supervisor, 'cleanup_descendants', side_effect=signaled_cleanup):
                status = m.base.hidden.supervise([sys.executable, '-c', code, inner_source, str(inner), str(pidfile), worker, child],
                                                 root, os.environ.copy(), 1)
            self.assertTrue(status['timedOut']); self.assertEqual(status['signal'], signal.SIGTERM)
            self.assertTrue(pidfile.exists())
            for pid in [status['processGroup'], *map(int, pidfile.read_text().split())]:
                self.assertFalse(Path(f'/proc/{pid}').exists(), f'process {pid} survived cleanup')
            recorded = json.loads((root / 'supervisor-result.json').read_text())
            self.assertTrue(recorded['timedOut']); self.assertEqual(recorded['signal'], signal.SIGTERM)


if __name__ == '__main__': unittest.main()
