#!/usr/bin/env python3
"""CPU tests for copied build, monitored wiring and matched saved audit."""
import hashlib
import importlib.util
import json
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


runner = load('matched_test_runner', HERE / 'run.py')
auditor = load('matched_test_auditor', HERE / 'audit.py')
monitor = load('matched_test_monitor', HERE / 'monitor.py')
build_supervisor = load('matched_test_supervisor', HERE / 'build-supervisor.py')
fixture = load('matched_test_fixtures', ROOT / 'experiments/physical-search-fallback-trial-v1/fixture_support.py')


def early_search(run):
    """Four policy actions and an early transfer, with a terminal poll."""
    rows, requests, result = fixture.build_protocol(run, 'search', polls=1)
    rows = rows[:5]; requests = requests[:5]
    rows += [fixture.observation(6, 142, 1, 8, [0, 0, 90]),
             fixture.observation(7, 162, 2, 5, [0, 0, 90]),
             fixture.observation(8, 162, 2, 7, [0, 0, 90])]
    requests += [{'sequence': 6, 'command': 8, 'steering': 0, 'speed': 0, 'hold': 0},
                 {'sequence': 7, 'command': 7, 'steering': 0, 'speed': 0, 'hold': 20},
                 {'sequence': 8, 'command': 3, 'steering': 0, 'speed': 0, 'hold': 0}]
    actors = Path(run) / 'actors'
    for path in actors.iterdir():
        if int(path.stem.split('-')[1]) > 4: path.unlink()
    (Path(run) / 'visual-trigger.rgb').write_bytes(fixture.RGB)
    result.update({'policyActions': 4, 'collectorTerminal': True, 'searchFallbackStarted': True,
                   'visualRecoveryReason': 1, 'visualRecoveryTriggerAction': 4,
                   'visualRecoveryOutcome': 'search_started_unverified'})
    fixture.write_protocol(run, rows, requests, result, True)
    return rows


class MatchedTest(unittest.TestCase):
    def test_build_worker_retains_receipt_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); build = root / 'build'; receipt = root / 'monitor'; receipt.mkdir()
            real_run = subprocess.run
            def run(args, **kwargs):
                if args[0] == str(build_supervisor.base.base.IONICE):
                    return subprocess.CompletedProcess(args, 0, 'idle\n', '')
                return real_run(args, **kwargs)
            with mock.patch.object(build_supervisor.base, 'BUILD', build), \
                    mock.patch.object(build_supervisor.base, 'MONITOR', receipt), \
                    mock.patch.object(build_supervisor.base.os, 'getpriority', return_value=15), \
                    mock.patch.object(subprocess, 'run', side_effect=run):
                build_supervisor.worker()
                result = json.loads((receipt / 'worker-result.json').read_text())
                self.assertEqual(result['status'], 'isolated_build_only')
                self.assertEqual(result['clientSHA256'], runner.sha(build / 'client'))
                with self.assertRaises(FileExistsError): build_supervisor.worker()

    def test_full_build_verification_and_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'build'; report = runner.builder.build(path)
            self.assertEqual(runner.check_build(path), report)
            self.assertEqual((path / 'client').read_bytes(), (path / 'baseline-client').read_bytes())
            with (path / 'source/control/physical-client.flex').open('a') as stream: stream.write('\n// changed\n')
            with self.assertRaises(ValueError): runner.check_build(path)
            with self.assertRaises(FileExistsError): runner.builder.build(path)

    def test_arm_flags_and_monitor_subprocess_routing(self):
        for arm in runner.ARMS:
            env = runner.base.env_for('1' if arm == 'candidate-search' else '0')
            self.assertEqual(env['PUPPYBOT_PHYSICAL_SEARCH_FALLBACK'], '1')
            self.assertEqual(env['PUPPYBOT_VISUAL_SEARCH_RECOVERY'], '1' if arm == 'candidate-search' else '0')
        self.assertIn(str(HERE / 'monitor.py'), monitor.base.worker_command('/tmp/o', '/tmp/b', '/tmp/c', '/tmp/e', '/tmp/m'))
        self.assertIn(str(HERE / 'build-supervisor.py'), build_supervisor.base.command())
        pins = monitor.source_pins()
        for path in (HERE / 'run.py', HERE / 'audit.py', HERE / 'monitor.py', HERE / 'build.py',
                     ROOT / 'experiments/visual-search-recovery-v1/audit.py',
                     ROOT / 'experiments/physical-search-fallback-trial-v1/audit.py'):
            self.assertIn(str(path), pins)

    def test_early_transfer_and_matched_comparison(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); case = root / 'case.json'; case.write_text('{}')
            case_hash = hashlib.sha256(case.read_bytes()).hexdigest()
            build = root / 'build'; model = root / 'model'; environment = root / 'environment.bin'
            environment.write_bytes(b'PBENV001' + bytes(112))
            files = {str(case): case_hash, str(environment): 'environment', str(auditor.base.hidden.ASSET): 'asset'}
            files.update({str(build / name): name for name in ('simulator', 'baseline-simulator')})
            files.update({str(model / name): name for name in ('policy', 'weights.bin', 'receipt.json')})
            fixture.write_json(root / 'inputs.json', {'schema': 'puppybot.physical-search-fallback-trial.v1',
                'navigationLimit': 90, 'collectorPollLimit': 1499, 'case': str(case), 'environment': str(environment),
                'build': str(build), 'model': str(model), 'files': files})
            for arm in runner.ARMS:
                run = root / arm / 'run'
                journal = early_search(run) if arm == 'candidate-search' else fixture.build_protocol(run, 'search')[0]
                client = json.loads((run / 'inputs.json').read_text())
                client.update({'simulatorSHA256': 'baseline-simulator' if arm == 'baseline' else 'simulator',
                    'caseSHA256': case_hash, 'environmentSHA256': 'environment', 'weightsSHA256': 'weights.bin',
                    'policySHA256': 'policy', 'receiptSHA256': 'receipt.json', 'robotAssetSHA256': 'asset',
                    'cameraPitch': 82, 'contactFeedback': 'unavailable-forced-zero'})
                fixture.write_json(run / 'inputs.json', client)
                trace = [{'step': journal[0]['step'], 'pose': [0, 0, 0],
                          'case': {'objects': [{'id': 'brick'}], 'container': {'position': [1, 2, 0]}}},
                         {'step': journal[-1]['step'], 'pose': [0, 0, 0],
                          'case': {'objects': [{'id': 'brick'}], 'container': {'position': [1, 2, 0]}}}]
                (run / 'trace.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in trace))
                result = json.loads((run / 'result.json').read_text())
                result['traceSHA256'] = auditor.base.sha(run / 'trace.jsonl'); fixture.write_json(run / 'result.json', result)
                directory = run.parent / 'monitor'; directory.mkdir()
                fixture.write_json(directory / 'supervisor-result.json', {'clientExit': 0, 'timedOut': False,
                    'signal': None, 'remainingWorkersTerminated': False, 'processGroup': 123})
            fake_runner = types.SimpleNamespace(check_manifest=lambda *args: None, check_invocation=lambda *args: None)
            manipulation = {'caseSHA256': case_hash, 'captures': [], 'releases': [], 'traceMeetsManipulationCriteria': False}
            completed = subprocess.CompletedProcess([], 0, json.dumps(manipulation), '')
            with mock.patch.object(auditor.base, 'load', return_value=fake_runner), \
                    mock.patch.object(auditor.base.subprocess, 'run', return_value=completed):
                result = auditor.audit(root)
                self.assertTrue(result['comparisonEligible'])
                self.assertTrue(result['mechanismEligible'])
                self.assertTrue(result['matchedTriggerFrame'])
                self.assertEqual(result['visualRuns']['candidate-search']['visualTriggerAction'], 4)
                self.assertFalse(result['outcomes']['candidate-search']['completedSimulatedManipulation'])
                with mock.patch.object(auditor.base.subprocess, 'run', return_value=subprocess.CompletedProcess(
                        [], 0, json.dumps({'caseSHA256': case_hash, 'captures': [], 'releases': []}), '')):
                    with self.assertRaisesRegex(ValueError, 'incomplete manipulation audit'): auditor.audit(root)
                controls = [root / arm / 'run/actors/actor-5.rgb' for arm in ('baseline', 'candidate-disabled')]
                for path in controls: path.write_bytes(b'x' * len(fixture.RGB))
                result = auditor.audit(root)
                self.assertTrue(result['matchedSavedPrefix'])
                self.assertFalse(result['matchedTriggerFrame'])
                self.assertFalse(result['comparisonEligible'])
                self.assertFalse(result['mechanismEligible'])
                self.assertEqual(result['censorReason'], 'trigger_frame_mismatch_or_missing')
                for path in controls: path.write_bytes(fixture.RGB)
                controls[0].unlink()
                # An absent control actor input fails closed in the underlying
                # actor audit before any matched comparison can be accepted.
                with self.assertRaises((ValueError, OSError)): auditor.audit(root)
                controls[0].write_bytes(fixture.RGB)
                image = root / 'candidate-search/run/visual-trigger.rgb'; image.write_bytes(b'x' * len(fixture.RGB))
                with self.assertRaises(ValueError): auditor.audit(root)
                image.write_bytes(fixture.RGB)
                (root / 'candidate-search/run/actors/actor-2.hidden').write_bytes(bytes([1]) + bytes(511))
                result = auditor.audit(root)
                self.assertFalse(result['comparisonEligible'])
                self.assertFalse(result['mechanismEligible'])


if __name__ == '__main__': unittest.main()
