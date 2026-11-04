#!/usr/bin/env python3
"""CPU-only build, diagnostic audit and process-routing checks."""
import importlib.util
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import types
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


runner = load('test_survey_trial', HERE / 'run.py')
audit = load('test_survey_audit', HERE / 'audit.py')
monitor = load('test_survey_monitor', HERE / 'monitor.py')
build_supervisor = load('test_survey_build_supervisor', HERE / 'build-supervisor.py')
fixture = load('test_survey_fixture', ROOT / 'experiments/physical-search-fallback-trial-v1/fixture_support.py')


class TestSurveyTrial(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='puppy-survey-trial-')
        cls.root = Path(cls.tmp.name); cls.build = cls.root / 'build'
        cls.receipt = runner.builder.build(cls.build)

    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def test_real_build_and_tamper(self):
        self.assertEqual(runner.check_build(self.build), self.receipt)
        path = self.build / 'baseline-client'; original = path.read_bytes()
        try:
            path.write_bytes(original + b'x')
            with self.assertRaises(ValueError): runner.check_build(self.build)
        finally: path.write_bytes(original)

    def test_supervised_build_worker_refuses_existing_output(self):
        with tempfile.TemporaryDirectory(dir=self.root) as temp:
            root = Path(temp); output = root / 'build'; receipt = root / 'monitor'; receipt.mkdir()
            real_run = subprocess.run
            def run(argv, **kwargs):
                if argv[0] == str(build_supervisor.base.IONICE):
                    return subprocess.CompletedProcess(argv, 0, 'idle\n', '')
                return real_run(argv, **kwargs)
            with mock.patch.object(build_supervisor, 'BUILD', output), mock.patch.object(build_supervisor, 'MONITOR', receipt), \
                    mock.patch.object(build_supervisor.os, 'getpriority', return_value=15), \
                    mock.patch.object(subprocess, 'run', side_effect=run):
                build_supervisor.worker()
                result = json.loads((receipt / 'worker-result.json').read_text())
                self.assertEqual(result['status'], 'isolated_build_only')
                self.assertEqual(result['simulatorSHA256'], runner.sha(output / 'simulator'))
                with self.assertRaises(ValueError): build_supervisor.worker()

    def test_arm_environment_isolated(self):
        root = self.root / 'trial'
        for name in ('baseline', 'candidate-disabled'):
            env = runner.env_for(root, name)
            self.assertEqual(env['PUPPYBOT_DOCK_CONFIRM'], '1')
            self.assertNotIn('PUPPYBOT_DOCK_DIAG_DIRECTORY', env)
        env = runner.env_for(root, 'candidate-search')
        self.assertEqual(env['PUPPYBOT_DOCK_DIAG_DIRECTORY'], str(root / 'candidate-search/diagnostic'))

    def test_diagnostic_inventory_and_rejections(self):
        with tempfile.TemporaryDirectory(dir=self.root) as temp:
            path = Path(temp); (path / 'survey-7.rgb').write_bytes(bytes(640 * 480 * 3))
            camera = {'schema': 'puppybot.camera.v1', 'view': 'tcp', 'capturedMs': 1400,
                      'frameId': 70, 'width': 640, 'height': 480,
                      'intrinsics': {'fx': 416, 'fy': 416, 'cx': 320, 'cy': 240},
                      'eyeM': [0, 0, 1], 'forward': [1, 0, 0], 'right': [0, 1, 0], 'down': [0, 0, -1]}
            (path / 'survey-7.sensor.camera.json').write_text(json.dumps(camera))
            plan = {'schema': 'puppybot.dock-viewpoint-diagnostic.v1', 'step': 71, 'search': 2,
                    'index': 4, 'planned': False, 'reason': 3, 'expanded': 17, 'goal': [0, 0, 0]}
            (path / 'search-2-candidate-4.json').write_text(json.dumps(plan))
            trace = path / 'trace.fixture'
            trace.write_text('\n'.join(json.dumps({'step': step, 'case': {'dockVision': {'surveyDiagnostic':
                {'count': 1, 'planCount': 1, 'writeErrors': 0}}}}) for step in (70, 71)) + '\n')
            # The trace lives outside the diagnostic directory in real runs.
            outside = self.root / 'trace.fixture'; outside.write_text(trace.read_text()); trace.unlink()
            result = audit.diagnostic(path, outside)
            self.assertEqual((result['surveyImages'], result['frameIds'], result['viewpointPlans']), (1, [70], 1))
            self.assertEqual(result['reasonCounts']['3'], 1)
            candidate = path / 'search-2-candidate-4.json'
            data = candidate.read_bytes(); candidate.unlink()
            with self.assertRaises(ValueError): audit.diagnostic(path, outside)
            candidate.write_bytes(data)
            duplicate = path / 'search-02-candidate-04.json'; duplicate.write_bytes(data)
            with self.assertRaises(ValueError): audit.diagnostic(path, outside)
            duplicate.unlink()
            invalid = dict(plan, reason=0); candidate.write_text(json.dumps(invalid))
            with self.assertRaises(ValueError): audit.diagnostic(path, outside)
            candidate.write_bytes(data)
            (path / 'survey-7.rgb').unlink()
            with self.assertRaises(ValueError): audit.diagnostic(path, outside)

    def test_monitor_reimports_this_adapter(self):
        command = monitor.base.worker_command('/tmp/out', '/tmp/build', '/tmp/case', '/tmp/env', '/tmp/model')
        self.assertEqual(command[-6], str(HERE / 'monitor.py'))
        code = ('import importlib.util,sys; s=importlib.util.spec_from_file_location("m",sys.argv[1]);'
                'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);'
                'print(m.base.TRIAL);print(m.base.runner.__file__)')
        result = subprocess.run([sys.executable, '-I', '-c', code, str(HERE / 'monitor.py')],
                                capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.splitlines(), [str(HERE), str(HERE / 'run.py')])

    def test_complete_three_arm_saved_audit_and_prefix_mismatch(self):
        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            root = Path(temporary); case = root / 'case.json'; case.write_text('{}')
            case_hash = hashlib.sha256(case.read_bytes()).hexdigest()
            build = root / 'build'; model = root / 'model'; environment = root / 'environment.bin'
            environment.write_bytes(b'PBENV001' + bytes(112))
            files = {str(case): case_hash, str(environment): 'environment', str(audit.base.hidden.ASSET): 'asset'}
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
                journal = audit.base.rows(run / 'physical-agent.jsonl')
                trace = []
                for step in (journal[0]['step'], journal[-1]['step']):
                    dock = {'frameId': -1, 'valid': False}
                    if arm == 'candidate-search': dock['surveyDiagnostic'] = {'count': 0, 'planCount': 0, 'writeErrors': 0}
                    trace.append({'step': step, 'pose': [0, 0, 0],
                        'case': {'objects': [{'id': 'brick'}], 'container': {'position': [1, 2, 0]}, 'dockVision': dock}})
                (run / 'trace.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in trace))
                result = json.loads((run / 'result.json').read_text())
                result['traceSHA256'] = audit.base.sha(run / 'trace.jsonl'); fixture.write_json(run / 'result.json', result)
                directory = run.parent / 'monitor'; directory.mkdir()
                fixture.write_json(directory / 'supervisor-result.json', {'clientExit': 0, 'timedOut': False,
                    'signal': None, 'remainingWorkersTerminated': False, 'processGroup': 123})
            (root / 'candidate-search/diagnostic').mkdir()
            fake_runner = types.SimpleNamespace(check_manifest=lambda *args: None, check_invocation=lambda *args: None)
            manipulation = {'caseSHA256': case_hash, 'captures': [], 'releases': []}
            completed = subprocess.CompletedProcess([], 0, json.dumps(manipulation), '')
            with mock.patch.object(audit.base, 'load', return_value=fake_runner), \
                    mock.patch.object(audit.base.subprocess, 'run', return_value=completed):
                result = audit.audit(root)
                self.assertTrue(result['comparisonEligible'], result)
                self.assertFalse(result['surveyDiagnostic']['observationEligible'])
                path = root / 'candidate-search/run/actors/actor-1.rgb'
                contents = bytearray(path.read_bytes()); contents[0] ^= 1; path.write_bytes(contents)
                result = audit.audit(root)
                self.assertFalse(result['comparisonEligible'])
                self.assertEqual(result['censorReason'], 'saved_prefix_or_initial_truth_mismatch')


if __name__ == '__main__': unittest.main()
