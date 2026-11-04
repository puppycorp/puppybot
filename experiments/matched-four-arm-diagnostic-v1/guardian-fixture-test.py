#!/usr/bin/env python3
"""CPU-only guardian and final-supervisor evidence checks."""
import importlib.util
import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('matched_guard_fixture', HERE / 'runner.py')
runner = importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + '\n')


def row(tick, phase, passed, free=40):
    volumes = {name: free * runner.GIB for name in ('workspace', 'home', 'output')}
    return {'monotonicSeconds': tick, 'phase': phase, 'baselinePassed': passed,
            'volumes': volumes, 'freeBytes': free * runner.GIB,
            'gpuTotalBytes': 16 * runner.GIB, 'gpuUsedBytes': 4 * runner.GIB,
            'gpuFreeBytes': 12 * runner.GIB, 'gpuBusyPercent': 3}


class GuardianFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.monitor = self.root / 'monitor'; self.monitor.mkdir()
        self.plan = self.root / 'plan.json'; dump(self.plan, {'plan': 'fixture'})
        self.parent, self.guardian, self.coordinator = 400, 401, 402
        self.env = {'PATH': '/usr/bin:/bin', 'HOME': str(self.root)}
        self.guardenv = dict(self.env, PUPPY_TURN_GUARD_PID=str(self.guardian),
                             PUPPY_TURN_GUARD_FD='8', PUPPY_TURN_GUARD_OUTPUT=str(self.monitor))
        self.launcher = {'argv': runner.guardian_command(self.parent), 'environment': self.env,
                         'parentPID': self.parent, 'planSHA256': runner.sha(self.plan)}
        self.launch = {'guardianPID': self.guardian, 'coordinatorPID': self.coordinator,
                       'parentPID': self.parent, 'wallSeconds': runner.OUTER_SECONDS,
                       'command': runner.child_command('coordinator'), 'environment': self.guardenv,
                       'startedMonotonic': 99.9}
        self.result = {'status': 'passed', 'reason': None, 'coordinatorExit': 0,
                       'descendantsTerminated': False, 'diskEmergency': False, 'samples': 4,
                       'observedDoneMonotonic': 101.5, 'endedMonotonic': 103.1}
        self.rows = [row(100, 'active', False), row(101, 'active', True),
                     row(102, 'cleanup', True), row(103, 'cleanup', True)]
        self.marker = {'status': 'passed', 'monotonicSeconds': 100.5}
        self.save()
        self.baseline = mock.patch.object(runner.pair, 'check_baseline'); self.baseline.start()
        self.addCleanup(self.baseline.stop)
        self.patches = [mock.patch.object(runner, 'MONITOR', self.monitor),
                        mock.patch.object(runner, 'PLAN', self.plan),
                        mock.patch.object(runner, 'environment', return_value=self.env)]
        for patch in self.patches: patch.start(); self.addCleanup(patch.stop)

    def save(self):
        dump(self.monitor / 'launcher.json', self.launcher)
        dump(self.monitor / 'guardian-launch.json', self.launch)
        dump(self.monitor / 'guardian-result.json', self.result)
        dump(self.monitor / 'baseline-passed.json', self.marker)
        (self.monitor / 'guardian-telemetry.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in self.rows))
        (self.monitor / 'baseline.jsonl').write_text(json.dumps({'monotonicSeconds': 100.25}) + '\n')

    def test_valid_guardian_and_altered_invocation_or_environment(self):
        self.assertEqual(runner.verify_guardian(self.guardian)['status'], 'passed')
        self.launch['command'][-1] = 'wrong'; self.save()
        with self.assertRaisesRegex(ValueError, 'invocation or completion'): runner.verify_guardian(self.guardian)
        self.launch['command'] = runner.child_command('coordinator')
        self.launch['environment']['PUPPY_TURN_GUARD_FD'] = 'not-an-fd'; self.save()
        with self.assertRaisesRegex(ValueError, 'invocation or completion'): runner.verify_guardian(self.guardian)
        self.launch['environment']['PUPPY_TURN_GUARD_FD'] = '8'
        self.launch['environment']['HOME'] = '/different'; self.save()
        with self.assertRaisesRegex(ValueError, 'invocation or completion'): runner.verify_guardian(self.guardian)
        self.launch['environment']['HOME'] = self.env['HOME']
        self.launch['environment']['PUPPY_TURN_GUARD_OUTPUT'] = '/different'; self.save()
        with self.assertRaisesRegex(ValueError, 'invocation or completion'): runner.verify_guardian(self.guardian)

    def test_38_gib_before_marker_and_34_gib_after(self):
        self.rows[0] = row(100, 'active', False, 37); self.save()
        with self.assertRaisesRegex(ValueError, 'resource sample'): runner.verify_guardian(self.guardian)
        self.rows[0] = row(100, 'active', False, 38)
        self.rows[1] = row(101, 'active', True, 34); self.save()
        self.assertEqual(runner.verify_guardian(self.guardian)['status'], 'passed')
        self.rows[2] = row(102, 'cleanup', True, 33); self.save()
        with self.assertRaisesRegex(ValueError, 'resource sample'): runner.verify_guardian(self.guardian)

    def test_missing_sample_or_invalid_gpu_is_rejected(self):
        self.rows.pop(); self.result['samples'] = 3; self.save()
        with self.assertRaises(ValueError): runner.verify_guardian(self.guardian)
        self.rows = [row(100, 'active', False), row(101, 'active', True),
                     row(102, 'cleanup', True), row(103, 'cleanup', True)]
        self.result['samples'] = 4; self.rows[1]['gpuFreeBytes'] = 1; self.save()
        with self.assertRaisesRegex(ValueError, 'resource sample'): runner.verify_guardian(self.guardian)

    def test_marker_must_not_be_reversed_or_backdated(self):
        self.rows[1]['baselinePassed'] = False; self.rows[2]['baselinePassed'] = True
        self.rows[3]['baselinePassed'] = False; self.save()
        with self.assertRaisesRegex(ValueError, 'baseline phase'): runner.verify_guardian(self.guardian)
        self.rows[3]['baselinePassed'] = True; self.marker['monotonicSeconds'] = 102; self.save()
        with self.assertRaisesRegex(ValueError, 'baseline marker|baseline phase'): runner.verify_guardian(self.guardian)

    def test_baseline_outside_guardian_interval_is_rejected(self):
        for tick in (99, 100.6):
            with self.subTest(tick=tick):
                (self.monitor / 'baseline.jsonl').write_text(json.dumps({'monotonicSeconds': tick}) + '\n')
                with self.assertRaisesRegex(ValueError, 'baseline timing'): runner.verify_guardian(self.guardian)

    def test_resource_callback_keeps_prebaseline_state_when_marker_appears_mid_sample(self):
        marker = self.monitor / 'baseline-passed.json'; marker.unlink()
        def gpu(_device):
            dump(marker, {'status': 'passed', 'monotonicSeconds': 1})
            return {'freeBytes': 12 * runner.GIB, 'usedBytes': 4 * runner.GIB,
                    'totalBytes': 16 * runner.GIB, 'busyPercent': 3}
        with mock.patch.object(runner.base.monitor.telemetry, 'telemetry', side_effect=gpu), \
             mock.patch.object(runner.shutil, 'disk_usage', return_value=types.SimpleNamespace(free=40 * runner.GIB)):
            self.assertFalse(runner.resources()['baselinePassed'])
            self.assertTrue(runner.resources()['baselinePassed'])


class FinalSupervisorFixture(unittest.TestCase):
    def test_child_environment_and_supervisor_invocation_preserve_guardian_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            monitor = Path(temp); env = {'PATH': '/usr/bin:/bin', 'HOME': temp}
            identity = {'PUPPY_TURN_GUARD_PID': '501', 'PUPPY_TURN_GUARD_FD': '7',
                        'PUPPY_TURN_GUARD_OUTPUT': temp}
            status = {'clientExit': 0, 'timedOut': False, 'remainingWorkersTerminated': False,
                      'signal': None, 'processGroup': 678}
            def supervise(argv, directory, actual_env, seconds):
                self.assertEqual(argv, runner.child_command('final_check'))
                self.assertEqual(actual_env, {**env, **identity})
                self.assertEqual(seconds, runner.FINAL_SECONDS)
                dump(directory / 'supervisor-result.json', status)
                return status
            with mock.patch.object(runner, 'MONITOR', monitor), \
                 mock.patch.object(runner, 'environment', return_value=env), \
                 mock.patch.dict(os.environ, identity, clear=True), \
                 mock.patch.object(runner.base.base.hidden, 'supervise', side_effect=supervise):
                runner.supervisor('final-supervisor', 'final_check', runner.FINAL_SECONDS)
            invocation = json.loads((monitor / 'final-supervisor/invocation.json').read_text())
            self.assertEqual(invocation['environment'], {**env, **identity})
            self.assertEqual(invocation['argv'], runner.child_command('final_check'))

    def test_missing_guardian_identity_fails_closed(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, 'guardian identity missing'):
                runner.child_environment()


class FinalCheckFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.monitor = self.root / 'monitor'; self.monitor.mkdir()
        self.output = self.root / 'output'; self.output.mkdir()
        self.plan = self.root / 'plan.json'; dump(self.plan, {'plan': 'fixture'})
        self.report = {'status': 'diagnostic_only'}; dump(self.output / 'report.json', self.report)
        self.frozen = {'registered': 'fixture'}; self.inventory = {'file': 'digest'}
        self.events = []
        self.patches = [mock.patch.object(runner, 'MONITOR', self.monitor),
                        mock.patch.object(runner, 'OUTPUT', self.output),
                        mock.patch.object(runner, 'PLAN', self.plan),
                        mock.patch.object(runner.guard_owner, 'require_guardian'),
                        mock.patch.object(runner, 'verify', return_value=self.frozen),
                        mock.patch.object(runner, 'reaudit', return_value=self.report),
                        mock.patch.object(runner, 'output_inventory', return_value=self.inventory),
                        mock.patch.object(runner, 'deep_inputs', side_effect=self.deep),
                        mock.patch.object(runner, 'prior_inventory', side_effect=self.prior),
                        mock.patch.object(runner, 'training_inventory', side_effect=self.training, create=True)]
        for patch in self.patches: patch.start(); self.addCleanup(patch.stop)

    def deep(self, frozen):
        self.assertEqual(frozen, self.frozen); self.events.append('deep')
        return {'status': 'retained_inputs_consistent'}

    def prior(self):
        self.events.append('prior')

    def training(self):
        self.events.append('training')

    def test_boundary_rechecks_after_deep_review(self):
        runner.final_check()
        self.assertEqual(self.events, ['deep', 'prior', 'training'])
        result = json.loads((self.monitor / 'final-result.json').read_text())
        self.assertEqual(result['inventory'], self.inventory)
        self.assertEqual(result['reportSHA256'], runner.sha(self.output / 'report.json'))
        self.assertEqual(runner.guard_owner.require_guardian.call_count, 2)

    def test_after_deep_inventory_changes_fail_without_completion(self):
        for boundary in ('prior_inventory', 'training_inventory'):
            with self.subTest(boundary=boundary):
                checker = getattr(runner, boundary)
                original = checker.side_effect
                checker.side_effect = ValueError('retained inventory changed')
                with self.assertRaisesRegex(ValueError, 'inventory changed'): runner.final_check()
                self.assertFalse((self.monitor / 'final-result.json').exists())
                checker.side_effect = original

    def test_changed_new_output_inventory_fails_without_completion(self):
        runner.output_inventory.side_effect = [self.inventory, {'file': 'tampered'}]
        with self.assertRaisesRegex(ValueError, 'changed during final review'): runner.final_check()
        self.assertFalse((self.monitor / 'final-result.json').exists())


class LaunchClosureFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.monitor = self.root / 'monitor'; self.output = self.root / 'output'
        self.plan = self.root / 'plan.json'; dump(self.plan, {'plan': 'fixture'})
        self.frozen = {'registered': 'fixture'}; self.inventory = {'file': 'digest'}
        self.events = []; self.tamper_log = False
        self.patches = [mock.patch.object(runner, 'MONITOR', self.monitor),
                        mock.patch.object(runner, 'OUTPUT', self.output),
                        mock.patch.object(runner, 'PLAN', self.plan),
                        mock.patch.object(runner.base.guard, 'require_dedicated_process'),
                        mock.patch.object(runner, 'disk'), mock.patch.object(runner, 'verify', return_value=self.frozen),
                        mock.patch.object(runner, 'output_inventory', return_value=self.inventory),
                        mock.patch.object(runner, 'verify_guardian'),
                        mock.patch.object(runner, 'environment', return_value={'PATH': '/usr/bin'}),
                        mock.patch.object(runner, 'prior_inventory', side_effect=lambda: self.events.append('prior')),
                        mock.patch.object(runner, 'training_inventory', side_effect=lambda: self.events.append('training')),
                        mock.patch.object(runner.subprocess, 'Popen', side_effect=self.process)]
        for patch in self.patches: patch.start(); self.addCleanup(patch.stop)

    def process(self, *args, **kwargs):
        self.output.mkdir(); dump(self.output / 'report.json', {'status': 'fixture'})
        guardian_env = {'PUPPY_TURN_GUARD_PID': '501'}
        dump(self.monitor / 'guardian-launch.json', {'environment': guardian_env})
        dump(self.monitor / 'guardian-result.json', {'status': 'passed'})
        (self.monitor / 'guardian-telemetry.jsonl').write_text('{}\n')
        (self.monitor / 'baseline.jsonl').write_text('{}\n')
        supervisor = self.monitor / 'final-supervisor'
        dump(supervisor / 'invocation.json', {'argv': runner.child_command('final_check'),
             'environment': guardian_env, 'wallSeconds': runner.FINAL_SECONDS})
        dump(supervisor / 'supervisor-result.json', {'clientExit': 0, 'timedOut': False,
             'remainingWorkersTerminated': False, 'signal': None, 'processGroup': 678})
        (supervisor / 'client.log').write_text('final log\n')
        dump(self.monitor / 'final-result.json', {'status': 'diagnostic_only', 'planSHA256': runner.sha(self.plan),
             'reportSHA256': runner.sha(self.output / 'report.json'), 'inventory': self.inventory})
        dump(self.monitor / 'coordinator-result.json', {'status': 'diagnostic_only', 'planSHA256': runner.sha(self.plan),
             'finalSHA256': runner.sha(self.monitor / 'final-result.json'),
             'finalInvocationSHA256': runner.sha(supervisor / 'invocation.json'),
             'finalStatusSHA256': runner.sha(supervisor / 'supervisor-result.json'),
             'finalLogSHA256': runner.sha(supervisor / 'client.log')})
        if self.tamper_log: (supervisor / 'client.log').write_text('tampered\n')
        return types.SimpleNamespace(pid=501, wait=lambda: 0)

    def test_completion_rechecks_both_retained_inventories(self):
        self.assertEqual(runner.launch()['status'], 'diagnostic_only')
        self.assertEqual(self.events, ['prior', 'training'])
        self.assertTrue((self.monitor / 'completion.json').exists())

    def test_tampered_final_log_prevents_completion(self):
        self.tamper_log = True
        with self.assertRaisesRegex(ValueError, 'final evidence changed'): runner.launch()
        self.assertFalse((self.monitor / 'completion.json').exists())


if __name__ == '__main__':
    unittest.main()
