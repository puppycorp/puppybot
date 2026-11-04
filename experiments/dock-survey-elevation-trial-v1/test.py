#!/usr/bin/env python3
"""CPU-only copied build, symmetric recording and saved audit checks."""
import hashlib
import importlib.util
import json
import subprocess
import sys
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


runner = load('test_elevation_runner', HERE / 'run.py')
audit = load('test_elevation_audit', HERE / 'audit.py')
monitor = load('test_elevation_monitor', HERE / 'monitor.py')
supervisor = load('test_elevation_supervisor', HERE / 'build-supervisor.py')
fixture = load('test_elevation_fixture', ROOT / 'experiments/physical-search-fallback-trial-v1/fixture_support.py')


class TestElevationTrial(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='puppy-elevation-trial-')
        cls.root = Path(cls.tmp.name); cls.build = cls.root / 'build'
        cls.receipt = runner.builder.build(cls.build)

    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def test_real_build_and_tamper(self):
        self.assertEqual(runner.check_build(self.build), self.receipt)
        path = self.build / 'baseline-simulator'; original = path.read_bytes()
        try:
            path.write_bytes(original + b'x')
            with self.assertRaises(ValueError): runner.check_build(self.build)
        finally: path.write_bytes(original)
        with self.assertRaises(FileExistsError): runner.builder.build(self.build)

    def test_symmetric_recording_and_flags(self):
        root = self.root / 'trial'
        for name in runner.ARMS:
            env = runner.env_for(root, name)
            self.assertEqual(env['PUPPYBOT_DOCK_HIGH_SURVEY'], '1' if name == 'candidate-search' else '0')
            self.assertEqual(env['PUPPYBOT_DOCK_DIAG_DIRECTORY'], str(root / name / 'diagnostic'))
            self.assertEqual(env['PUPPYBOT_DOCK_CONFIRM'], '1')

    def test_supervised_build_worker_and_overwrite_refusal(self):
        with tempfile.TemporaryDirectory(dir=self.root) as temp:
            root = Path(temp); output = root / 'build'; receipt = root / 'monitor'; receipt.mkdir()
            real_run = subprocess.run
            def run(argv, **kwargs):
                if argv[0] == str(supervisor.base.base.IONICE):
                    return subprocess.CompletedProcess(argv, 0, 'idle\n', '')
                return real_run(argv, **kwargs)
            with mock.patch.object(supervisor.base, 'BUILD', output), mock.patch.object(supervisor.base, 'MONITOR', receipt), \
                    mock.patch.object(supervisor.base.os, 'getpriority', return_value=15), \
                    mock.patch.object(subprocess, 'run', side_effect=run):
                supervisor.worker()
                result = json.loads((receipt / 'worker-result.json').read_text())
                self.assertEqual(result['status'], 'isolated_build_only')
                self.assertEqual(result['simulatorSHA256'], runner.sha(output / 'simulator'))
                with self.assertRaises(FileExistsError): supervisor.worker()

    def test_monitor_and_build_worker_reimport_adapters(self):
        command = monitor.base.base.worker_command('/tmp/o', '/tmp/b', '/tmp/c', '/tmp/e', '/tmp/m')
        self.assertIn(str(HERE / 'monitor.py'), command)
        self.assertIn(str(HERE / 'build-supervisor.py'), supervisor.base.command())
        code = ('import importlib.util,sys;s=importlib.util.spec_from_file_location("m",sys.argv[1]);'
                'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);'
                'print(m.base.base.TRIAL);print(m.base.base.runner.__file__)')
        result = subprocess.run([sys.executable, '-I', '-c', code, str(HERE / 'monitor.py')],
                                capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.splitlines(), [str(HERE), str(HERE / 'run.py')])

    def test_high_counters_require_unambiguous_latest_accepted_attempt(self):
        trace = self.root / 'high-counters.jsonl'
        zero = {'attempts': 0, 'accepted': 0, 'ikRejected': 0, 'moveRejected': 0,
                'requestId': 0, 'settledStep': -1, 'armStillMatching': False, 'targetTicks': None}
        accepted = dict(zero, attempts=1, accepted=1, requestId=1, targetTicks=[200, 300, 400, 500])
        rejected = dict(accepted, attempts=2, ikRejected=1, requestId=0, targetTicks=None)
        trace.write_text(''.join(json.dumps({'step': step, 'timeMs': step * 20, 'case': {'surveyHigh': state}}) + '\n'
                                 for step, state in ((1, zero), (2, accepted), (3, accepted), (4, rejected))))
        result = audit.high_summary(trace, True, {2: 40, 3: 60, 4: 80})
        self.assertEqual(result['framesAfterAcceptance'], [3])
        self.assertEqual(result['settledFrames'], [])
        with self.assertRaises(ValueError): audit.high_summary(trace, False, {})
        trace.write_text(json.dumps({'step': 1, 'case': {'surveyHigh': dict(zero, accepted=1)}}) + '\n')
        with self.assertRaises(ValueError): audit.high_summary(trace, True, {})
        changed = dict(accepted, targetTicks=[201, 300, 400, 500])
        trace.write_text(''.join(json.dumps({'step': step, 'case': {'surveyHigh': state}}) + '\n'
                                 for step, state in ((1, zero), (2, accepted), (3, changed))))
        with self.assertRaisesRegex(ValueError, 'target changed'): audit.high_summary(trace, True, {})
        trace.write_text(''.join(json.dumps({'step': step, 'case': {'surveyHigh': state}}) + '\n'
            for step, state in ((1, zero), (2, accepted), (3, dict(accepted, settledStep=4, armStillMatching=True)))))
        with self.assertRaises(ValueError): audit.high_summary(trace, True, {})
        # A reset association cannot later reuse the prior accepted request to
        # credit a frame, even if forged state claims the arm is settled.
        inactive = dict(accepted, requestId=0, targetTicks=None)
        claimed = dict(accepted, settledStep=3, armStillMatching=True)
        rows = [{'step': 1, 'timeMs': 20, 'case': {'surveyHigh': zero}},
                {'step': 2, 'timeMs': 40, 'case': {'surveyHigh': accepted, 'phase': 'aiming TCP camera'}},
                {'step': 3, 'timeMs': 60, 'case': {'surveyHigh': inactive}},
                {'step': 4, 'timeMs': 80, 'case': {'surveyHigh': claimed, 'phase': 'finding box'},
                 'camera': {'armSettled': True}, 'gripper': {'held': True}, 'ticks': [200, 300, 400, 500]}]
        trace.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        self.assertEqual(audit.high_summary(trace, True, {4: 80})['settledFrames'], [])
        rows.pop(2)
        trace.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        self.assertEqual(len(audit.high_summary(trace, True, {4: 80})['settledFrames']), 1)
        with self.assertRaisesRegex(ValueError, 'capture time'): audit.high_summary(trace, True, {4: 81})
        rows[-1]['case']['surveyHigh'] = dict(claimed, settledStep=4)
        trace.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        self.assertEqual(audit.high_summary(trace, True, {4: 80})['settledFrames'], [])
        rows[-1]['case']['surveyHigh'] = dict(claimed, settledStep=2)
        trace.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        self.assertEqual(audit.high_summary(trace, True, {4: 80})['settledFrames'], [])
        rows[-1]['case']['surveyHigh'] = claimed
        for field, bad in (('ticks', [209, 300, 400, 500]),
                           ('camera', {'armSettled': False}), ('gripper', {'held': False})):
            original = rows[-1][field]; rows[-1][field] = bad
            trace.write_text(''.join(json.dumps(row) + '\n' for row in rows))
            with self.assertRaises(ValueError): audit.high_summary(trace, True, {4: 80})
            rows[-1][field] = original

    def test_complete_matched_saved_audit(self):
        with tempfile.TemporaryDirectory(dir=self.root) as temp:
            root = Path(temp); case = root / 'case.json'; case.write_text('{}')
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
                run = root / arm / 'run'; journal = fixture.build_protocol(run, 'search')[0]
                client = json.loads((run / 'inputs.json').read_text())
                client.update({'simulatorSHA256': 'baseline-simulator' if arm == 'baseline' else 'simulator',
                    'caseSHA256': case_hash, 'environmentSHA256': 'environment', 'weightsSHA256': 'weights.bin',
                    'policySHA256': 'policy', 'receiptSHA256': 'receipt.json', 'robotAssetSHA256': 'asset',
                    'cameraPitch': 82, 'contactFeedback': 'unavailable-forced-zero'})
                fixture.write_json(run / 'inputs.json', client)
                final_step = journal[-1]['step']; diag = run.parent / 'diagnostic'; diag.mkdir()
                trace = []
                for index, step in enumerate((journal[0]['step'], final_step - 2, final_step)):
                    n = int(arm == 'candidate-search' and index > 0)
                    captured = int(arm == 'candidate-search' and index == 2)
                    dock = {'frameId': -1, 'valid': False,
                            'surveyDiagnostic': {'count': captured, 'planCount': 0, 'writeErrors': 0}}
                    state = {'objects': [{'id': 'brick'}], 'container': {'position': [1, 2, 0]}, 'dockVision': dock}
                    if arm == 'candidate-search':
                        state['surveyHigh'] = {'attempts': n, 'accepted': n, 'ikRejected': 0, 'moveRejected': 0,
                            'requestId': n, 'settledStep': final_step - 1 if captured else -1,
                            'armStillMatching': bool(captured), 'targetTicks': [200, 300, 400, 500] if n else None}
                    if captured: state['phase'] = 'finding box'
                    elif n: state['phase'] = 'aiming TCP camera'
                    row = {'step': step, 'timeMs': step * 20, 'pose': [0, 0, 0], 'case': state}
                    if captured: row.update({'ticks': [200, 300, 400, 500], 'camera': {'armSettled': True}, 'gripper': {'held': True}})
                    trace.append(row)
                (run / 'trace.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in trace))
                if arm == 'candidate-search':
                    (diag / 'survey-1.rgb').write_bytes(bytes(640 * 480 * 3))
                    camera = {'schema': 'puppybot.camera.v1', 'view': 'tcp', 'capturedMs': final_step * 20,
                              'frameId': final_step, 'width': 640, 'height': 480,
                              'intrinsics': {'fx': 416, 'fy': 416, 'cx': 320, 'cy': 240},
                              'eyeM': [0, 0, 1], 'forward': [1, 0, 0], 'right': [0, 1, 0], 'down': [0, 0, -1]}
                    (diag / 'survey-1.sensor.camera.json').write_text(json.dumps(camera))
                result = json.loads((run / 'result.json').read_text())
                result['traceSHA256'] = audit.base.sha(run / 'trace.jsonl'); fixture.write_json(run / 'result.json', result)
                receipt = run.parent / 'monitor'; receipt.mkdir()
                fixture.write_json(receipt / 'supervisor-result.json', {'clientExit': 0, 'timedOut': False,
                    'signal': None, 'remainingWorkersTerminated': False, 'processGroup': 123})
            fake_runner = types.SimpleNamespace(check_manifest=lambda *args: None, check_invocation=lambda *args: None)
            manipulation = {'caseSHA256': case_hash, 'captures': [], 'releases': [], 'traceMeetsManipulationCriteria': False}
            done = subprocess.CompletedProcess([], 0, json.dumps(manipulation), '')
            with mock.patch.object(audit.base, 'load', return_value=fake_runner), \
                    mock.patch.object(audit.base.subprocess, 'run', return_value=done):
                result = audit.audit(root)
                self.assertTrue(result['comparisonEligible']); self.assertTrue(result['mechanismEligible'])
                self.assertTrue(result['acceptedCommandAndLaterFrameObserved'])
                self.assertEqual(result['highSurvey']['candidate-search']['settledFrames'][0]['requestId'], 1)
                self.assertEqual(result['highSurvey']['candidate-search']['framesAfterAcceptance'], [final_step])
                (root / 'candidate-search/diagnostic/survey-1.rgb').unlink()
                with self.assertRaises(ValueError): audit.audit(root)


if __name__ == '__main__': unittest.main()
