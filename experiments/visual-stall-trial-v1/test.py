#!/usr/bin/env python3
"""CPU checks for the staged matched visual-stall simulator diagnostic."""
import importlib.util
import json
import subprocess
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


build = load('visual_trial_build', HERE / 'build.py')
trial = load('visual_trial_runner', HERE / 'trial.py')


class VisualTrialTests(unittest.TestCase):
    def test_disposable_build_and_tamper(self):
        with tempfile.TemporaryDirectory(prefix='visual-trial-build-') as temp:
            output = Path(temp) / 'build'; receipt = build.build(output)
            self.assertEqual(receipt, build.verify(output))
            source = output / 'flex-source/control/environment.flex'
            text = source.read_text()
            self.assertIn('if ve_visual_trial_zero_contact {ve_contact=0;}', text)
            self.assertLess(text.index('if ve_visual_trial_zero_contact {ve_contact=0;}'),
                            text.index('vc_feedback(', text.index('fn ve_receive()')))
            with (output / 'control').open('ab') as stream: stream.write(b'changed')
            with self.assertRaises(ValueError): build.verify(output)

    def test_fresh_process_uses_fixed_paths_and_paired_arms(self):
        output = subprocess.check_output(trial.python_call('describe_configuration'), cwd=ROOT, text=True, timeout=10)
        config = json.loads(output)
        self.assertEqual(config['output'], str(trial.OUTPUT))
        self.assertEqual(config['registration'], str(HERE / 'trial.py'))
        self.assertEqual(config['worker'], trial.python_call('run'))
        self.assertEqual(len(trial.ARMS), 4)
        for row in trial.debug.plan.design()['conditions']:
            for arm in trial.ARMS:
                argv = trial.command(row, arm)
                self.assertEqual('--visual-stall-stop' in argv, arm in ('enabled', 'zero-contact-enabled'))
                self.assertEqual('--visual-trial-zero-contact' in argv, arm.startswith('zero-contact-'))
                self.assertNotIn('--contact-stop', argv)
                self.assertIn('--steer-hysteresis', argv)

    def test_real_launch_preflight_keeps_prior_receipt_after_rebinding(self):
        class StopBeforeWorker(Exception):
            pass

        with tempfile.TemporaryDirectory(prefix='visual-launch-test-') as temp:
            root = Path(temp); candidate = root / 'build'; trial.build.build(candidate)
            with ExitStack() as patches:
                patches.enter_context(mock.patch.object(trial.build, 'BUILD', candidate))
                patches.enter_context(mock.patch.object(trial, 'OUTPUT', root / 'games'))
                patches.enter_context(mock.patch.object(trial, 'MONITOR', root / 'monitor'))
                patches.enter_context(mock.patch.object(trial, 'MANIFEST', root / 'plan.json'))
                for name in ('MONITOR', 'verify', 'verify_saved', 'configure_monitor', 'python_call'):
                    patches.enter_context(mock.patch.object(trial.debug, name, getattr(trial.debug, name)))
                patches.enter_context(mock.patch.object(trial.debug.plan, 'OUTPUT', trial.debug.plan.OUTPUT))
                for name in ('OUTPUT', 'MONITOR', 'MANIFEST', 'REGISTER', 'verify_saved', 'worker_command'):
                    patches.enter_context(mock.patch.object(trial.monitor, name, getattr(trial.monitor, name)))
                patches.enter_context(mock.patch.object(trial.monitor, 'require_disk'))
                patches.enter_context(mock.patch.object(trial.monitor.guard, 'require_dedicated_process'))
                supervisor = patches.enter_context(mock.patch.object(trial.base.hidden, 'supervise', side_effect=StopBeforeWorker))
                frozen = trial.current(); trial.MANIFEST.write_text(json.dumps(frozen))
                self.assertEqual(len(frozen['commands']), 8)
                with self.assertRaises(StopBeforeWorker): trial.launch()
                self.assertEqual(supervisor.call_count, 1)
                launch = json.loads((trial.MONITOR / 'launch.json').read_text())
                self.assertEqual(launch['command'], trial.python_call('monitor_worker', trial.MONITOR))
                self.assertIn(str(trial.PRIOR_MONITOR / 'completion.json'), launch['sourcePins'])
                self.assertEqual(trial.current(), frozen)


if __name__ == '__main__':
    unittest.main()
