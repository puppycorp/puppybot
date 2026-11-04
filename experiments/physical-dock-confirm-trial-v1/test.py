#!/usr/bin/env python3
"""CPU checks for matched-arm wiring and build provenance."""
import importlib.util
import hashlib
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


runner = load('dock_test_runner', HERE / 'run.py')
auditor = load('dock_test_audit', HERE / 'audit.py')
monitor = load('dock_test_monitor', HERE / 'monitor.py')
build_supervisor = load('dock_test_build_supervisor', HERE / 'build-supervisor.py')
fixture = load('dock_search_fixture', ROOT / 'experiments/physical-search-fallback-trial-v1/fixture_support.py')


class TrialTest(unittest.TestCase):
    def test_supervised_build_worker_checks_priority_and_creates_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); build = root / 'build'; receipt = root / 'monitor'; receipt.mkdir()
            real_run = subprocess.run
            def run(args, **kwargs):
                if args[0] == str(build_supervisor.base.IONICE):
                    return subprocess.CompletedProcess(args, 0, 'idle\n', '')
                return real_run(args, **kwargs)
            with mock.patch.object(build_supervisor, 'BUILD', build), mock.patch.object(build_supervisor, 'MONITOR', receipt), \
                    mock.patch.object(build_supervisor.os, 'getpriority', return_value=15), \
                    mock.patch.object(subprocess, 'run', side_effect=run):
                build_supervisor.worker()
                result = json.loads((receipt / 'worker-result.json').read_text())
                self.assertEqual(result['status'], 'isolated_build_only')
                self.assertEqual(result['simulatorSHA256'], runner.sha(build / 'simulator'))
                with self.assertRaises(ValueError): build_supervisor.worker()

    def test_all_arms_search_and_only_treatment_enables_confirmation(self):
        for arm in runner.ARMS:
            flag = '1' if arm == 'candidate-search' else '0'
            env = runner.base.env_for(flag)
            self.assertEqual(env['PUPPYBOT_PHYSICAL_SEARCH_FALLBACK'], '1')
            self.assertEqual(env['PUPPYBOT_DOCK_CONFIRM'], flag)
        with tempfile.TemporaryDirectory() as temporary:
            for arm in runner.ARMS:
                run = Path(temporary) / arm
                fixture.build_protocol(run, 'search')
                self.assertIsNotNone(auditor.protocol(run, arm == 'candidate-search')['searchStep'])

    def test_build_source_identity_and_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            build = Path(temporary) / 'candidate'; runner.builder.build(build)
            runner.check_build(build)
            with (build / 'source/sim/collect.flex').open('a') as stream: stream.write('\n// changed\n')
            with self.assertRaises(ValueError): runner.check_build(build)

    def test_workers_load_this_trial_and_all_reused_sources_are_pinned(self):
        command = monitor.base.worker_command('/tmp/o', '/tmp/b', '/tmp/c', '/tmp/e', '/tmp/m')
        self.assertIn(str(HERE / 'monitor.py'), command)
        pins = monitor.source_pins()
        for path in (HERE / 'run.py', HERE / 'audit.py', HERE / 'monitor.py',
                     ROOT / 'experiments/physical-search-fallback-trial-v1/run.py',
                     ROOT / 'experiments/physical-search-fallback-trial-v1/audit.py',
                     ROOT / 'experiments/physical-search-fallback-monitor-v1/monitor.py'):
            self.assertIn(str(path), pins)
        with mock.patch.object(auditor.base, 'audit', return_value={'status': 'diagnostic_only', 'arms': [{'status': 'censored'}]}):
            self.assertIn('same simulator binary', auditor.audit('/unused')['scope'])

    def test_complete_matched_audit_and_prefix_censoring(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); case = root / 'case.json'; case.write_text('{}')
            case_hash = hashlib.sha256(case.read_bytes()).hexdigest()
            build = root / 'build'; model = root / 'model'; environment = root / 'environment.bin'
            environment.write_bytes(b'PBENV001' + bytes(112))
            files = {str(case): case_hash, str(environment): 'environment', str(auditor.base.hidden.ASSET): 'asset'}
            files.update({str(build / name): name for name in ('simulator', 'baseline-simulator')})
            files.update({str(model / name): name for name in ('policy', 'weights.bin', 'receipt.json')})
            fixture.write_json(root / 'inputs.json', {'schema': 'puppybot.physical-search-fallback-trial.v1',
                'navigationLimit': 90, 'collectorPollLimit': 1499, 'case': str(case),
                'environment': str(environment), 'build': str(build), 'model': str(model), 'files': files})
            for arm in runner.ARMS:
                run = root / arm / 'run'; fixture.build_protocol(run, 'search')
                client = json.loads((run / 'inputs.json').read_text())
                client.update({'simulatorSHA256': 'baseline-simulator' if arm == 'baseline' else 'simulator',
                    'caseSHA256': case_hash, 'environmentSHA256': 'environment', 'weightsSHA256': 'weights.bin',
                    'policySHA256': 'policy', 'receiptSHA256': 'receipt.json', 'robotAssetSHA256': 'asset',
                    'cameraPitch': 82, 'contactFeedback': 'unavailable-forced-zero'})
                fixture.write_json(run / 'inputs.json', client)
                journal = auditor.base.rows(run / 'physical-agent.jsonl')
                trace = [{'step': journal[0]['step'], 'pose': [0, 0, 0],
                          'case': {'objects': [{'id': 'brick'}], 'container': {'position': [1, 2, 0]}}},
                         {'step': journal[-1]['step'], 'pose': [0, 0, 0],
                          'case': {'objects': [{'id': 'brick'}], 'container': {'position': [1, 2, 0]}}}]
                for row in trace:
                    row['case']['dockVision'] = {'frameId': -1, 'valid': False}
                    row['discovery'] = {'pickup': {'boxLearned': False}}
                    if arm == 'candidate-search':
                        row['discovery']['dockConfirm'] = {'active': False, 'runs': 0, 'attempts': 0, 'reason': 0}
                (run / 'trace.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in trace))
                result = json.loads((run / 'result.json').read_text())
                result['traceSHA256'] = auditor.base.sha(run / 'trace.jsonl'); fixture.write_json(run / 'result.json', result)
                directory = run.parent / 'monitor'; directory.mkdir()
                fixture.write_json(directory / 'supervisor-result.json', {'clientExit': 0, 'timedOut': False,
                    'signal': None, 'remainingWorkersTerminated': False, 'processGroup': 123})
            fake_runner = types.SimpleNamespace(check_manifest=lambda *args: None, check_invocation=lambda *args: None)
            manipulation = {'caseSHA256': case_hash, 'captures': [], 'releases': []}
            completed = subprocess.CompletedProcess([], 0, json.dumps(manipulation), '')
            with mock.patch.object(auditor.base, 'load', return_value=fake_runner), \
                    mock.patch.object(auditor.base.subprocess, 'run', return_value=completed):
                result = auditor.audit(root)
                self.assertTrue(result['comparisonEligible'])
                self.assertFalse(result['mechanismEligible'])
                self.assertEqual(result['mechanismCensorReason'], 'confirmation_not_observed_active')
                self.assertTrue(all(arm['searchStarted'] for arm in result['arms']))
                path = root / 'candidate-search/run/actors/actor-1.rgb'
                contents = bytearray(path.read_bytes()); contents[0] ^= 1; path.write_bytes(contents)
                result = auditor.audit(root)
                self.assertFalse(result['comparisonEligible'])
                self.assertEqual(result['censorReason'], 'saved_prefix_or_initial_truth_mismatch')

    def test_dock_trace_activation_frames_and_rejections(self):
        def row(step, active, runs, attempts, reason, box=False, speed=0):
            return {'step': step, 'discovery': {'dockConfirm': {'active': active, 'runs': runs,
                    'attempts': attempts, 'reason': reason}, 'pickup': {'boxLearned': box}},
                    'case': {'dockVision': {'frameId': step, 'valid': True}},
                    'controller': {'drive': {'leftSpeed': speed, 'rightSpeed': speed}}}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'trace.jsonl'
            data = [row(1, False, 0, 0, 0), row(2, True, 1, 0, 0), row(3, True, 1, 1, 0),
                    row(4, False, 1, 2, 4, True), row(5, False, 1, 2, 4, True)]
            def write(): path.write_text(''.join(json.dumps(item) + '\n' for item in data))
            write(); result = auditor.dock_trace(path, True)
            self.assertEqual(result['firstBoxLearnedStep'], 4)
            self.assertEqual(result['runs'][0]['observedFreshValidFrames'], [2, 3, 4])
            self.assertEqual(result['runs'][0]['activeSteps'], 2)
            self.assertEqual(result['runs'][0]['lastStep'], 4)
            self.assertEqual(result['runs'][0]['lastReason'], 4)
            with self.assertRaises(ValueError): auditor.dock_trace(path, False)
            data[1]['controller']['drive']['leftSpeed'] = 30; write()
            with self.assertRaisesRegex(ValueError, 'nonzero commanded'): auditor.dock_trace(path, True)
            del data[1]['discovery']['dockConfirm']; write()
            with self.assertRaisesRegex(ValueError, 'missing confirmation'): auditor.dock_trace(path, True)
            data[:] = [row(1, False, 0, 0, 0), row(2, False, 0, 0, 5)]
            write(); result = auditor.dock_trace(path, True)
            self.assertEqual(result['preactivationFailures'], [{'step': 2, 'reason': 5}])
            self.assertEqual(result['runs'], [])


if __name__ == '__main__': unittest.main()
