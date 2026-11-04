#!/usr/bin/env python3
"""CPU-only tests of the disabled heading selection runner."""
import contextlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT = Path(__file__).resolve().parents[2]
SOURCE = PROJECT / 'datasets/visual-control/chase-v1/levels/run-heading-selection-v1.py'
spec = importlib.util.spec_from_file_location('heading_runner', SOURCE)
runner = importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)


class RunnerTests(unittest.TestCase):
    def test_fixed_commands_and_environment(self):
        tasks = runner.plan_tool.selection_design()
        self.assertEqual(len(tasks), 6)
        for task in tasks:
            for arm in ('control', 'treatment'):
                cmd = runner.command(task, arm); env = runner.environment(task)
                self.assertEqual(cmd[4:6], [str(runner.plan_tool.PACKAGE / arm), '--fetch'])
                self.assertEqual(cmd[6:-2], task['levelArgs'])
                self.assertEqual(cmd[-2:], ['--camera-pitch', '82'])
                self.assertEqual(env['PUPPYBOT_EVAL_TWO_ROOM'], '1' if task['level'] >= 4 else '0')
                self.assertEqual(env['PUPPYBOT_CHASE_PARTS'], '4')
                self.assertEqual(env['PUPPYBOT_CHASE_HORIZON'], '300')
                self.assertEqual(env['PUPPYBOT_CHASE_FULL'], '0')
                self.assertNotIn('DISPLAY', env)
        self.assertEqual(tasks[0]['levelArgs'], [])

    def exercise(self, fail_at=None, existing=False):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'selection'; plan_path = Path(temp) / 'plan.json'
            plan_path.write_text('{}')
            if existing: root.mkdir()
            tasks = runner.plan_tool.selection_design()
            plan = {'tasks': tasks, 'files': {}}
            seen = []
            def supervised(cmd, folder, env, limit):
                seen.append((cmd, limit)); folder.mkdir()
                if fail_at is not None and len(seen) == fail_at: raise RuntimeError('synthetic arm failure')
                if cmd[0] == sys.executable:
                    mode, name = cmd[-2:]
                    status = 'paired_selection_audit_only' if mode == 'pair' else 'saved_arm_audit_only'
                    (folder / 'client.log').write_text(json.dumps({'status': status, 'task': name, 'arm': mode}))
                else:
                    (folder / 'client.log').write_text('complete')
            patches = [mock.patch.object(runner.plan_tool, 'SELECTION_ROOT', root),
                       mock.patch.object(runner.plan_tool, 'PLAN', plan_path),
                       mock.patch.object(runner.plan_tool, 'OUTPUT', Path(temp)),
                       mock.patch.object(runner.base, 'acquire_lock', return_value=contextlib.nullcontext()),
                       mock.patch.object(runner.base, 'require_capacity'),
                       mock.patch.object(runner.base, 'sha', return_value='digest'),
                       mock.patch.object(runner, 'pins', return_value={'runner': 'digest'}),
                       mock.patch.object(runner.plan_tool, 'plan_inputs', return_value={}),
                       mock.patch.object(runner.audit, 'validate_plan', return_value=(plan, tasks[0])),
                       mock.patch.object(runner, 'supervised', side_effect=supervised)]
            with contextlib.ExitStack() as stack:
                for patch in patches: stack.enter_context(patch)
                if existing:
                    with self.assertRaises(ValueError): runner.run()
                    self.assertEqual(list(root.iterdir()), [])
                    return
                if fail_at:
                    with self.assertRaisesRegex(RuntimeError, 'synthetic'): runner.run()
                    partial = json.loads((root / 'selection.partial.json').read_text())
                    self.assertEqual(partial['status'], 'censored')
                    self.assertEqual(partial['tasks']['standard']['status'], 'censored')
                    self.assertEqual(partial['tasks']['L1']['status'], 'not_started')
                    self.assertFalse((root / 'selection-summary.json').exists())
                    self.assertEqual(len(seen), fail_at)
                else:
                    runner.run()
                    result = json.loads((root / 'selection-summary.json').read_text())
                    self.assertEqual(len(result['tasks']), 6)
                    self.assertTrue(all(t['status'] == 'paired_saved_audit' for t in result['tasks'].values()))
                    self.assertEqual(len(seen), 30)
                    self.assertEqual(sum(limit == runner.ARM_SECONDS for _, limit in seen), 12)
                    self.assertEqual(sum(limit == runner.AUDIT_SECONDS for _, limit in seen), 18)
                    self.assertIn('launch.json', result['inventory'])

    def test_completed_plan(self): self.exercise()
    def test_failed_arm_is_censored(self): self.exercise(fail_at=3)
    def test_existing_output_refused(self): self.exercise(existing=True)

    def test_cli_disabled(self):
        result = subprocess.run([sys.executable, '-I', str(SOURCE)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Disabled pending independent review', result.stderr)

    def test_real_cpu_supervision_and_timeout(self):
        env = {'PATH': '/usr/bin:/bin'}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runner.supervised([sys.executable, '-I', '-c', 'print("done")'], root / 'ok', env, 3)
            self.assertEqual((root / 'ok/client.log').read_text().strip(), 'done')
            with self.assertRaises(RuntimeError):
                runner.supervised([sys.executable, '-I', '-c', 'import time; time.sleep(10)'], root / 'timeout', env, .1)
            status = json.loads((root / 'timeout/supervisor-result.json').read_text())
            self.assertIs(status['timedOut'], True)

    def test_audit_worker_bad_json_and_wrong_identity(self):
        task = runner.plan_tool.selection_design()[0]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for index, response in enumerate(('not json', json.dumps({'status': 'saved_arm_audit_only',
                                              'task': 'L2', 'arm': 'control'}),
                                              json.dumps({'status': 'saved_arm_audit_only',
                                              'task': 'standard', 'arm': 'treatment'}))):
                evidence = root / str(index); evidence.mkdir()
                def fake(_cmd, folder, _env, _limit):
                    folder.mkdir(); (folder / 'client.log').write_text(response)
                with mock.patch.object(runner, 'supervised', side_effect=fake):
                    with self.assertRaises((ValueError, json.JSONDecodeError)):
                        runner.audit_saved(task, 'control', evidence, {})

    def test_failed_monitor_is_rejected(self):
        bad = {'signal': None, 'timedOut': False, 'clientExit': 1, 'remainingWorkersTerminated': False}
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch.object(runner.base.hidden, 'supervise', return_value=bad):
                with self.assertRaises(RuntimeError):
                    runner.supervised(['false'], Path(temp) / 'bad', {}, 1)


if __name__ == '__main__': unittest.main()
