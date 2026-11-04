#!/usr/bin/env python3
"""CPU-only adapter tests; never launch the simulator or GPU monitor."""
import contextlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('debug_replay', HERE / 'replay.py')
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)


class ReplayTest(unittest.TestCase):
    def test_every_monitor_process_gets_debug_paths(self):
        replay.configure_monitor()
        self.assertEqual(replay.monitor.OUTPUT, replay.plan.OUTPUT)
        self.assertEqual(replay.monitor.REGISTER, HERE / 'replay.py')
        self.assertIs(replay.monitor.verify_saved, replay.verify_saved)
        self.assertIn('run', replay.monitor.worker_command())
        self.assertIn('final_check', replay.python_call('final_check', 'dir', 'hash'))

    def test_fresh_subprocess_reimports_debug_configuration(self):
        process = subprocess.run(replay.python_call('describe_configuration'), capture_output=True,
                                 text=True, check=True, timeout=15)
        actual = json.loads(process.stdout)
        self.assertEqual(actual['output'], str(replay.plan.OUTPUT))
        self.assertEqual(actual['registration'], str(HERE / 'replay.py'))
        self.assertIn('run', actual['worker'])

    def test_failed_outer_monitor_never_publishes_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); output = root / 'out'; monitor_dir = root / 'monitor'
            status = {'clientExit': 1, 'signal': None, 'timedOut': False,
                      'remainingWorkersTerminated': False, 'processGroup': 123}
            def fail(argv, receipt, env, seconds):
                (receipt / 'supervisor-result.json').write_text(json.dumps(status))
                return status
            with mock.patch.object(replay.plan, 'OUTPUT', output), mock.patch.object(replay, 'MONITOR', monitor_dir), \
                 mock.patch.object(replay.guard, 'require_dedicated_process'), \
                 mock.patch.object(replay.monitor, 'require_disk'), \
                 mock.patch.object(replay, 'verify', return_value={'files': {}}), \
                 mock.patch.object(replay.base.hidden, 'supervise', side_effect=fail):
                with self.assertRaisesRegex(RuntimeError, 'monitor failed'):
                    replay.launch()
            self.assertFalse((monitor_dir / 'completion.json').exists())

    def test_six_statuses_and_saved_game_audit_are_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'out'; output.mkdir()
            rows = replay.plan.design()['conditions']
            scenes = [{**row, 'files': {'case.json': 'case', 'environment.bin': 'env'}} for row in rows]
            frozen = {'design': replay.plan.design(), 'scenes': scenes, 'weightsSHA256': 'weights'}
            (output / 'inputs.json').write_text(json.dumps(frozen))
            status = {'clientExit': 0, 'signal': None, 'timedOut': False,
                      'remainingWorkersTerminated': False, 'processGroup': 123}
            with mock.patch.object(replay.plan, 'OUTPUT', output), \
                 mock.patch.object(replay.selection, 'snapshot', return_value='weights'), \
                 mock.patch.object(replay, 'compare_prior', return_value={'firstActorDifference': None}), \
                 mock.patch.object(replay.saved, 'saved_three', side_effect=lambda a, b, c, seed, expected: {'seed': seed}) as saved:
                for row in rows:
                    for arm in replay.plan.design()['arms']:
                        directory = output / 'monitors' / str(row['index']) / arm
                        directory.mkdir(parents=True)
                        (directory / 'invocation.json').write_text(json.dumps({
                            'argv': replay.plan.command(row, arm), 'environment': replay.environment(),
                            'wallSeconds': replay.ARM_SECONDS}))
                        (directory / 'supervisor-result.json').write_text(json.dumps(status))
                self.assertEqual(len(replay.reaudit(frozen)['pairs']), 2)
                self.assertEqual(saved.call_count, 2)
                bad = output / 'monitors/1/kick-hysteresis/supervisor-result.json'
                bad.write_text(json.dumps({**status, 'clientExit': 1}))
                with self.assertRaisesRegex(ValueError, 'unclean arm'):
                    replay.reaudit(frozen)

    def test_prior_actor_comparison_reports_first_changed_action(self):
        row = replay.plan.design()['conditions'][0]
        probe = {'proposed': [0, 0], 'applied': [0, 0], 'feedback': [], 'imageSHA256': 'a',
                 'hiddenBeforeSHA256': 'b', 'hiddenAfterSHA256': 'c'}
        old = {'probe': [probe, probe], 'initialBytes': b'one', 'startBytes': b'start',
               'backForthSteps': 70, 'metrics': {}}
        changed = {**probe, 'applied': [0, 1]}
        new = {**old, 'probe': [probe, changed], 'backForthSteps': 40}
        with mock.patch.object(replay.saved.kick, 'saved_game', side_effect=[old, new]):
            result = replay.compare_prior(row, Path('/unused'), {})
        self.assertEqual(result['firstActorDifference'], 2)
        self.assertEqual((result['priorBackForthSteps'], result['currentBackForthSteps']), (70, 40))
        self.assertTrue(result['sameInitialBytes'])

    def test_failed_arm_is_censored_and_never_publishes_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'out'
            status = {'clientExit': 1, 'signal': None, 'timedOut': False,
                      'remainingWorkersTerminated': False, 'processGroup': 123}
            def fail(argv, receipt, env, seconds):
                (receipt / 'supervisor-result.json').write_text(json.dumps(status))
                return status
            with mock.patch.object(replay.plan, 'OUTPUT', output), \
                 mock.patch.object(replay.guard, 'require_dedicated_process'), \
                 mock.patch.object(replay.base, 'acquire_lock', return_value=contextlib.nullcontext()), \
                 mock.patch.object(replay.base, 'require_capacity'), \
                 mock.patch.object(replay, 'verify', return_value={'frozen': True}), \
                 mock.patch.object(replay.base.hidden, 'supervise', side_effect=fail):
                with self.assertRaisesRegex(ValueError, 'supervisor failed'):
                    replay.run()
            partial = json.loads((output / 'partial.json').read_text())
            self.assertEqual(partial['status'], 'censored')
            self.assertEqual(partial['finished'], [])
            self.assertFalse((output / 'report.json').exists())

    def test_existing_output_prevents_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'out'; output.mkdir()
            with mock.patch.object(replay.plan, 'OUTPUT', output), \
                 mock.patch.object(replay.guard, 'require_dedicated_process'), \
                 mock.patch.object(replay.base, 'acquire_lock', return_value=contextlib.nullcontext()), \
                 mock.patch.object(replay, 'verify') as verify:
                with self.assertRaises((FileExistsError, ValueError)):
                    replay.run()
                verify.assert_not_called()


if __name__ == '__main__':
    unittest.main()
