#!/usr/bin/env python3
"""CPU tests for the matched, explicitly censored contact diagnostic."""
import importlib.util
import json
import shutil
import subprocess
import sys
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


build = load('contact_trial_build', HERE / 'build.py')
audit = load('contact_trial_audit', HERE / 'audit.py')
trial = load('contact_trial_runner', HERE / 'trial.py')
PRIOR = ROOT / 'build/flex/sim/levels-v2/pitch82/l5-steering-hysteresis-debug-v1/games/1/kick-hysteresis/6800107'


class ContactTrialTests(unittest.TestCase):
    def test_fresh_process_uses_contact_paths_and_commands(self):
        command = trial.python_call('describe_configuration')
        output = subprocess.check_output(command, cwd=ROOT, text=True, timeout=10)
        config = json.loads(output)
        self.assertEqual(config['output'], str(trial.OUTPUT))
        self.assertEqual(config['registration'], str(HERE / 'trial.py'))
        self.assertEqual(config['worker'], trial.python_call('run'))
        for row in trial.debug.plan.design()['conditions']:
            disabled = trial.command(row, 'disabled'); enabled = trial.command(row, 'enabled')
            self.assertEqual(enabled[:-1], disabled[:disabled.index('--output') + 1] +
                             [enabled[enabled.index('--output') + 1]] + disabled[disabled.index('--output') + 2:])
            self.assertEqual(enabled[-1], '--contact-stop')
            self.assertIn('--steer-hysteresis', enabled)

    def test_disposable_build_and_tamper(self):
        with tempfile.TemporaryDirectory(prefix='contact-build-test-') as temp:
            output = Path(temp) / 'build'
            receipt = build.build(output)
            self.assertEqual(receipt, build.verify(output))
            with (output / 'control').open('ab') as stream: stream.write(b'changed')
            with self.assertRaises(ValueError): build.verify(output)

    def test_current_rechecks_prior_plan_and_candidate_build(self):
        with tempfile.TemporaryDirectory(prefix='contact-plan-test-') as temp:
            output = Path(temp) / 'build'; trial.build.build(output)
            original = trial.build.BUILD
            try:
                trial.build.BUILD = output
                plan = trial.current()
                self.assertEqual(plan['status'], 'frozen_before_play')
                self.assertEqual(len(plan['commands']), 4)
                self.assertEqual([r['seed'] for r in plan['conditions']], [6800102, 6800107])
                self.assertEqual(plan['buildSHA256'], trial.base.sha(output / 'control'))
            finally:
                trial.build.BUILD = original

    def test_real_launch_preflight_keeps_prior_receipt_after_rebinding(self):
        class StopBeforeWorker(Exception):
            pass

        with tempfile.TemporaryDirectory(prefix='contact-launch-test-') as temp:
            root = Path(temp); candidate = root / 'build'
            trial.build.build(candidate)
            with ExitStack() as patches:
                patches.enter_context(mock.patch.object(trial.build, 'BUILD', candidate))
                patches.enter_context(mock.patch.object(trial, 'OUTPUT', root / 'games'))
                patches.enter_context(mock.patch.object(trial, 'MONITOR', root / 'monitor'))
                patches.enter_context(mock.patch.object(trial, 'MANIFEST', root / 'plan.json'))
                # launch() changes these module bindings in place; restore them
                # after the test so other CPU tests remain independent.
                for name in ('MONITOR', 'verify', 'verify_saved', 'configure_monitor', 'python_call'):
                    patches.enter_context(mock.patch.object(trial.debug, name, getattr(trial.debug, name)))
                patches.enter_context(mock.patch.object(trial.debug.plan, 'OUTPUT', trial.debug.plan.OUTPUT))
                for name in ('OUTPUT', 'MONITOR', 'MANIFEST', 'REGISTER', 'verify_saved', 'worker_command'):
                    patches.enter_context(mock.patch.object(trial.monitor, name, getattr(trial.monitor, name)))
                patches.enter_context(mock.patch.object(trial.monitor, 'require_disk'))
                patches.enter_context(mock.patch.object(trial.monitor.guard, 'require_dedicated_process'))
                supervisor = patches.enter_context(mock.patch.object(trial.base.hidden, 'supervise', side_effect=StopBeforeWorker))
                frozen = trial.current()
                trial.MANIFEST.write_text(json.dumps(frozen))
                with self.assertRaises(StopBeforeWorker): trial.launch()
                self.assertEqual(supervisor.call_count, 1)
                launch = json.loads((trial.MONITOR / 'launch.json').read_text())
                self.assertEqual(launch['command'], trial.python_call('monitor_worker', trial.MONITOR))
                self.assertIn(str(trial.PRIOR_MONITOR / 'completion.json'), launch['sourcePins'])
                self.assertEqual(trial.current(), frozen)

    def test_stopped_game_and_prefix_mismatch(self):
        with tempfile.TemporaryDirectory(prefix='contact-audit-test-') as temp:
            enabled = Path(temp) / 'enabled'; shutil.copytree(PRIOR, enabled)
            trigger = 146
            for name in ('steer-probe.jsonl', 'hysteresis.jsonl'):
                path = enabled / name; path.write_text(''.join(path.read_text().splitlines(keepends=True)[:trigger]))
            path = enabled / 'decisions.jsonl'; lines = path.read_text().splitlines()[:trigger]
            zero = json.loads(lines[-1]); zero['sequence'] += 1; zero['step'] += 10; zero['action'] = [0.0, 0.0]
            zero['state']['controller']['drive']['leftSpeed'] = 0; zero['state']['controller']['drive']['rightSpeed'] = 0
            path.write_text('\n'.join(lines + [json.dumps(zero)]) + '\n')
            path = enabled / 'result.json'; result = json.loads(path.read_text())
            result.update(steps=trigger + 1, contactStopReason='sustained_contact', countAsFailedGame=True,
                          fullHorizonCompleted=False); path.write_text(json.dumps(result))
            (enabled / 'contact-stop.json').write_text(json.dumps({'schema': 'puppybot.sim-contact-stop.v1',
                'reason': 'sustained_contact', 'triggerAfterActions': trigger, 'observedActions': trigger + 1,
                'zeroStopActions': 1, 'consecutiveContactSamples': 3, 'zeroCommandEchoObserved': True,
                'stopCommandAcknowledged': False, 'goalGameCompleted': False}))
            outcome = audit.audit_pair(PRIOR, enabled, PRIOR)
            self.assertEqual(outcome['triggerAfterActions'], trigger)
            self.assertTrue(outcome['countAsFailedGame'])
            path.write_text(path.read_text().replace('"countAsFailedGame": true', '"countAsFailedGame": false'))
            with self.assertRaises(ValueError): audit.audit_pair(PRIOR, enabled, PRIOR)


if __name__ == '__main__': unittest.main()
