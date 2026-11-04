#!/usr/bin/env python3
"""CPU fixtures for ordering, cleanup status, provenance and resource floors."""
import importlib.util
import fcntl
import json
import os
import sys
import time
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


runner = load('turn_runner_fixture', HERE / 'run.py')
monitor = load('turn_monitor_fixture', HERE / 'monitor.py')


class RunnerTest(unittest.TestCase):
    def test_command_rejects_unregistered_arm(self):
        with self.assertRaises(ValueError):
            runner.command_for('/tmp', {}, 'candidate-60')

    def run_fixture(self, fail_first):
        with tempfile.TemporaryDirectory(prefix='turn-runner-fixture-') as temp:
            root = Path(temp); build = root / 'build'; build.mkdir(); model = root / 'model'; model.mkdir()
            files = {}
            for key in ('case', 'environment', 'client'):
                files[key] = root / key; files[key].write_text(key)
            for key, name in (('model', 'weights.bin'), ('policy', 'policy'), ('receipt', 'receipt.json')):
                files[key] = model / name; files[key].write_text(key)
            reference = {'caseSHA256': runner.sha(files['case']), 'environmentSHA256': runner.sha(files['environment']),
                         'weightsSHA256': runner.sha(files['model']), 'policySHA256': runner.sha(files['policy']),
                         'receiptSHA256': runner.sha(files['receipt']), 'simulatorSHA256': 'historical',
                         'cameraPitch': 82, 'contactFeedback': 'unavailable-forced-zero', 'robotAssetSHA256': 'robot'}
            files['supervisor'] = root / 'reference.json'
            files['supervisor'].write_text(json.dumps({'referenceInputs': reference}))
            for name in runner.ARMS:
                arm = build / name; arm.mkdir(); (arm / 'simulator').write_text(name)
            calls = []

            def supervise(command, folder, env, timeout):
                name = Path(folder).parent.name; calls.append(name)
                self.assertEqual(timeout, 300); self.assertEqual(env, runner.env_for())
                arm = Path(folder).parent; run = arm / 'run'; run.mkdir()
                (run / 'inputs.json').write_text(json.dumps(dict(reference, simulatorSHA256=runner.sha(build / name / 'simulator'))))
                (run / 'trace.jsonl').write_text('{}\n')
                status = {'clientExit': 0, 'timedOut': bool(fail_first), 'remainingWorkersTerminated': False,
                          'signal': None, 'processGroup': 123, 'wallSeconds': 0.1}
                (Path(folder) / 'supervisor-result.json').write_text(json.dumps(status))
                return status

            audit_result = {'status': 'diagnostic_only', 'comparisonEligible': False, 'censorReason': 'fixture'}
            with mock.patch.dict(runner.os.environ, {'PUPPYBOT_SEARCH_TRIAL_REVIEWED_WORKER': '1'}), \
                 mock.patch.object(runner, 'LOCK', root / 'lock'), \
                 mock.patch.object(runner, 'require_guardian'), \
                 mock.patch.object(runner.base, 'load', return_value=SimpleNamespace(require_dedicated_process=lambda: None)), \
                 mock.patch.object(runner.builder, 'INPUTS', files), \
                 mock.patch.object(runner.builder, 'verify'), \
                 mock.patch.object(runner.hidden.rescan, 'verify_model'), \
                 mock.patch.object(runner.hidden.supervisor, 'worker_snapshot', return_value={'files': {}}), \
                 mock.patch.object(runner.hidden, 'supervise', side_effect=supervise), \
                 mock.patch.object(runner, 'check_manifest'), \
                 mock.patch.object(runner, 'pins', return_value={}), \
                 mock.patch.object(runner.auditor, 'audit', return_value=audit_result), \
                 mock.patch.object(runner.shutil, 'disk_usage', return_value=SimpleNamespace(free=100 * 1024**3)), \
                 mock.patch.object(runner.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='{}', stderr='')):
                output = root / 'output'
                if fail_first:
                    with self.assertRaises(RuntimeError):
                        runner.launch(output, build, files['case'], files['environment'], model)
                    self.assertEqual(calls, ['control-10'])
                    self.assertTrue((output / 'control-10/monitor/supervisor-result.json').exists())
                    self.assertFalse((output / 'candidate-10').exists())
                else:
                    self.assertEqual(runner.launch(output, build, files['case'], files['environment'], model), audit_result)
                    self.assertEqual(calls, list(runner.ARMS))
                    self.assertEqual(json.loads((output / 'audit.json').read_text()), audit_result)
                    manifest = json.loads((output / 'inputs.json').read_text())
                    for name in runner.ARMS:
                        runner.check_invocation(output, manifest, name)
                        runner.check_run_inputs(output / name, manifest, name)

    def test_serial_pair_and_retained_failure(self):
        self.run_fixture(False)
        self.run_fixture(True)

    def test_monitor_tightens_prelaunch_floor(self):
        with mock.patch.object(monitor, 'original_sample_disk') as sample:
            monitor.sample_disk(None, 'pre-baseline', {}, 36)
            self.assertEqual(sample.call_args.args[-1], 38)
            monitor.sample_disk(None, 'trial', {}, 34)
            self.assertEqual(sample.call_args.args[-1], 34)
            with tempfile.TemporaryDirectory(prefix='turn-baseline-marker-') as temp:
                with mock.patch.dict(os.environ, {'PUPPY_TURN_GUARD_OUTPUT': temp}):
                    monitor.sample_disk(None, 'post-baseline', {}, 36)
                self.assertEqual(sample.call_args.args[-1], 38)
                self.assertEqual(json.loads((Path(temp) / 'baseline-passed.json').read_text())['status'], 'passed')
                self.assertFalse((Path(temp) / 'baseline-passed.tmp').exists())

    def test_runner_requires_live_lock_owner(self):
        with tempfile.TemporaryDirectory(prefix='turn-lock-fixture-') as temp:
            path = Path(temp) / 'lock'; path.write_text('')
            with mock.patch.object(runner, 'LOCK', path):
                with path.open('a') as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    with mock.patch.dict(os.environ, {'PUPPY_TURN_GUARD_PID': str(os.getpid()),
                                                       'PUPPY_TURN_GUARD_FD': str(lock.fileno())}):
                        runner.require_guardian()
                with self.assertRaises(RuntimeError): runner.require_guardian()

    def test_guardian_coverage_rejects_final_audit_disk_breach(self):
        with tempfile.TemporaryDirectory(prefix='turn-coverage-fixture-') as temp:
            output = Path(temp); code = ('import importlib.util,sys;'
                's=importlib.util.spec_from_file_location("turn_monitor",sys.argv[1]);'
                'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.coordinator(*sys.argv[2:])')
            outer_env = monitor.original_base_env()
            outer_args = [sys.executable, '-I', '-c', 'guardian', str(HERE / 'monitor.py'), str(output),
                          '/tmp/build', '/tmp/case', '/tmp/environment', '/tmp/model', '123']
            (output / 'launcher.json').write_text(json.dumps({'command': outer_args, 'environment': outer_env}))
            child_env = dict(outer_env, PUPPY_TURN_GUARD_PID='456', PUPPY_TURN_GUARD_FD='7',
                             PUPPY_TURN_GUARD_OUTPUT=str(output))
            command = [sys.executable, '-I', '-c', code, str(HERE / 'monitor.py'), str(output / 'coordinator'), *outer_args[6:10]]
            (output / 'guardian-launch.json').write_text(json.dumps({'parentPID': 123, 'guardianPID': 456,
                'coordinatorPID': 789, 'startedMonotonic': 9, 'wallSeconds': 4200, 'command': command, 'environment': child_env}))
            rows = []
            for phase, tick in (('active', 10), ('active', 11), ('cleanup', 12), ('cleanup', 12.1)):
                volumes = {'home': 40*monitor.base.GIB, 'workspace': 40*monitor.base.GIB, 'output': 40*monitor.base.GIB}
                rows.append({'phase': phase, 'monotonicSeconds': tick, 'volumes': volumes,
                    'freeBytes': min(volumes.values()), 'gpuFreeBytes': 8*monitor.base.GIB,
                    'gpuTotalBytes': 16*monitor.base.GIB, 'gpuUsedBytes': 8*monitor.base.GIB, 'gpuBusyPercent': 0,
                    'baselinePassed': tick >= 10.5})
            log = output / 'guardian-telemetry.jsonl'
            log.write_text(''.join(json.dumps(row) + '\n' for row in rows))
            (output / 'baseline-passed.json').write_text(json.dumps({'status': 'passed', 'monotonicSeconds': 10.5}))
            (output / 'guardian-result.json').write_text(json.dumps({'status': 'passed', 'reason': None,
                'coordinatorExit': 0, 'descendantsTerminated': False, 'diskEmergency': False, 'samples': 4,
                'observedDoneMonotonic': 11.5, 'endedMonotonic': 13}))
            self.assertEqual(monitor.verify_guardian(output)['status'], 'passed')
            rows[1]['volumes']['output'] = 33*monitor.base.GIB; rows[1]['freeBytes'] = 33*monitor.base.GIB
            log.write_text(''.join(json.dumps(row) + '\n' for row in rows))
            with self.assertRaises(ValueError): monitor.verify_guardian(output)
            rows[1]['volumes']['output'] = 40*monitor.base.GIB; rows[1]['freeBytes'] = 40*monitor.base.GIB
            rows[2]['baselinePassed'] = False
            log.write_text(''.join(json.dumps(row) + '\n' for row in rows))
            with self.assertRaises(ValueError): monitor.verify_guardian(output)

    def test_marker_created_during_disk_read_keeps_baseline_floor(self):
        with tempfile.TemporaryDirectory(prefix='turn-baseline-race-') as temp:
            output = Path(temp); marker = output / 'baseline-passed.json'
            def disk(_):
                if not marker.exists():
                    marker.write_text(json.dumps({'status': 'passed', 'monotonicSeconds': time.monotonic()}))
                return SimpleNamespace(free=37 * monitor.base.GIB)
            gpu = {'freeBytes': 8*monitor.base.GIB, 'totalBytes': 16*monitor.base.GIB,
                   'usedBytes': 8*monitor.base.GIB, 'busyPercent': 0}
            with mock.patch.object(monitor.base.telemetry, 'telemetry', return_value=gpu), \
                 mock.patch.object(monitor.shutil, 'disk_usage', side_effect=disk):
                self.assertIs(monitor.resource_read(output)['baselinePassed'], False)
                self.assertIs(monitor.resource_read(output)['baselinePassed'], True)


if __name__ == '__main__':
    unittest.main()
