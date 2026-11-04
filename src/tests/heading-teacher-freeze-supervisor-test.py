#!/usr/bin/env python3
"""CPU-only controls for the disabled teacher-freeze watchdog."""
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
SOURCE = ROOT / 'flex/tests/supervise-heading-teacher-freeze.py'
spec = importlib.util.spec_from_file_location('freeze_watchdog', SOURCE)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


class FreezeWatchdogTest(unittest.TestCase):
    def test_disabled_entrypoint_and_three_hour_limit(self):
        result = subprocess.run([sys.executable, '-I', str(SOURCE)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Disabled pending independent review', result.stderr)
        self.assertEqual(m.WALL_SECONDS, 10800)

    def test_dedicated_native_thread_and_child_guard(self):
        for task_count, children in ((2, []), (1, [(123, 'S')])):
            with self.subTest(task_count=task_count), mock.patch.object(m.watch, 'native_task_count', return_value=task_count), \
                 mock.patch.object(m.watch.hidden.supervisor, 'children', return_value=children), \
                 mock.patch.object(m.base, 'require_capacity') as capacity:
                with self.assertRaisesRegex(RuntimeError, 'dedicated process'): m.launch()
                capacity.assert_not_called()

    def test_no_overwrite_exit_and_published_metadata(self):
        clean = {'signal': None, 'timedOut': False, 'clientExit': 0,
                 'remainingWorkersTerminated': False, 'processGroup': 123}
        for case in ('success', 'bad-plan', 'child-23', 'existing-plan'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); output = root / 'heading'; (output / 'models').mkdir(parents=True)
                selection = root / 'selection.json'; selection.write_text('{"status":"passed"}')
                source = root / 'freeze.py'; source.write_text('fixture')
                plan = output / 'models/heading-teacher-plan-v1.json'; monitor = root / 'monitor'
                if case == 'existing-plan': plan.write_text('preserve')
                def fake(directory, command, env, limit):
                    self.assertEqual(command[:3], [sys.executable, '-I', '-c'])
                    self.assertEqual(command[-1], str(source)); self.assertIn('m.freeze()', command[3])
                    self.assertEqual(limit, 10800)
                    if case != 'child-23':
                        result = {'schema': 'puppybot.heading-teacher-selection-plan.v1',
                                  'status': 'wrong' if case == 'bad-plan' else 'frozen_before_teacher',
                                  'draft': {'tasks': [{'name': x} for x in ('standard','L1','L2','L3','L4','L5')]},
                                  'studentCompletionSHA256': m.base.sha(selection), 'sourcePins': {str(source): m.base.sha(source)}}
                        plan.write_text(json.dumps(result))
                    status = dict(clean, clientExit=23 if case == 'child-23' else 0)
                    return status, m.watch.exit_code(status)
                patches = [mock.patch.object(m, 'P', root), mock.patch.object(m, 'OUTPUT', output),
                           mock.patch.object(m, 'PLAN', plan), mock.patch.object(m, 'MONITOR', monitor),
                           mock.patch.object(m, 'TEACHER', output / 'teacher-selection-v1'),
                           mock.patch.object(m, 'TEACHER_MONITOR', root / 'teacher-monitor'),
                           mock.patch.object(m, 'STUDENT_RECEIPT', selection), mock.patch.object(m, 'FREEZE', source),
                           mock.patch.object(m.base, 'require_capacity'), mock.patch.object(m.watch, 'native_task_count', return_value=1),
                           mock.patch.object(m.watch.hidden.supervisor, 'children', return_value=[]),
                           mock.patch.object(m.watch, 'supervise', side_effect=fake)]
                import contextlib
                with contextlib.ExitStack() as stack:
                    for patch in patches: stack.enter_context(patch)
                    if case == 'existing-plan':
                        with self.assertRaises(ValueError): m.launch()
                        self.assertEqual(plan.read_text(), 'preserve'); self.assertFalse(monitor.exists())
                        continue
                    self.assertEqual(m.launch(), {'success': 0, 'bad-plan': 1, 'child-23': 23}[case])
                result = json.loads((monitor / 'result.json').read_text())
                self.assertEqual(result['childExit'], 23 if case == 'child-23' else 0)
                self.assertEqual(result['wrapperExit'], {'success': 0, 'bad-plan': 1, 'child-23': 23}[case])

    def test_timeout_cleans_detached_descendant_and_spares_sibling(self):
        grandchild = 'import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)'
        child = ('import os,signal,subprocess,sys,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);'
                 'p=subprocess.Popen([sys.executable,"-c",sys.argv[2]],start_new_session=True);'
                 'open(sys.argv[1],"w").write(str(os.getpid())+" "+str(p.pid));time.sleep(30)')
        code = textwrap.dedent('''
            import importlib.util,json,os,sys
            from pathlib import Path
            s=importlib.util.spec_from_file_location('w',sys.argv[1]);w=importlib.util.module_from_spec(s);s.loader.exec_module(w)
            status,result=w.watch.supervise(Path(sys.argv[2]),[sys.executable,'-c',sys.argv[4],sys.argv[3],sys.argv[5]],os.environ.copy(),.5)
            print(json.dumps({'status':status,'result':result}))
        ''')
        other = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(30)'])
        try:
            with tempfile.TemporaryDirectory() as tmp:
                pidfile = Path(tmp) / 'workers.pid'
                result = subprocess.run([sys.executable, '-c', code, str(SOURCE), tmp, str(pidfile), child, grandchild],
                                        capture_output=True, text=True, timeout=20, check=True)
                row = json.loads(result.stdout); self.assertEqual(row['result'], 124); self.assertTrue(row['status']['timedOut'])
                self.assertIsNone(other.poll())
                for pid in map(int, pidfile.read_text().split()): self.assertFalse(Path(f'/proc/{pid}').exists())
        finally:
            other.terminate(); other.wait(timeout=5)


if __name__ == '__main__': unittest.main()
