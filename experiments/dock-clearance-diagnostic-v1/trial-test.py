#!/usr/bin/env python3
"""CPU-only checks for the staged clearance trial and separate audit."""
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import types
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


runner = load('clearance_test_runner', HERE / 'run.py')
audit = load('clearance_test_audit', HERE / 'audit.py')
monitor = load('clearance_test_monitor', HERE / 'monitor.py')
supervisor = load('clearance_test_supervisor', HERE / 'build-supervisor.py')
fixture = load('clearance_fixture', HERE.parents[1] / 'experiments/physical-search-fallback-trial-v1/fixture_support.py')


class TrialTests(unittest.TestCase):
    def test_disposable_build_and_tamper(self):
        with tempfile.TemporaryDirectory(prefix='clearance-trial-build-') as temp:
            build = Path(temp) / 'build'; receipt = runner.builder.build(build)
            self.assertEqual(runner.check_build(build), receipt)
            path = build / 'source/sim/navigation.flex'; original = path.read_text()
            path.write_text(original + '\n// tampered\n')
            with self.assertRaises(ValueError): runner.check_build(build)
            path.write_text(original)
            path = build / 'baseline-simulator'; path.write_bytes(path.read_bytes() + b'x')
            with self.assertRaises(ValueError): runner.check_build(build)
            with self.assertRaises(FileExistsError): runner.builder.build(build)

    def test_symmetric_recording_and_reimports(self):
        for arm in runner.ARMS:
            env = runner.env_for('/tmp/trial', arm)
            self.assertEqual(env['PUPPYBOT_DOCK_DIAG_DIRECTORY'], '/tmp/trial/' + arm + '/diagnostic')
            self.assertEqual(env['PUPPYBOT_DOCK_HIGH_SURVEY'], '1' if arm == 'candidate-search' else '0')
        command = monitor.base.base.worker_command('/tmp/o', '/tmp/b', '/tmp/c', '/tmp/e', '/tmp/m')
        self.assertIn(str(HERE / 'monitor.py'), command)
        self.assertIn(str(HERE / 'build-supervisor.py'), supervisor.base.command())
        code = ('import importlib.util,sys;s=importlib.util.spec_from_file_location("m",sys.argv[1]);'
                'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);'
                'print(m.base.base.TRIAL);print(m.base.base.runner.__file__)')
        result = subprocess.run([sys.executable, '-I', '-c', code, str(HERE / 'monitor.py')],
                                capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.splitlines(), [str(HERE), str(HERE / 'run.py')])

    def test_separate_accounting_and_reject_bad_counts(self):
        with tempfile.TemporaryDirectory(prefix='clearance-audit-') as temp:
            root = Path(temp); trace = root / 'trace.jsonl'; diagnostic = root / 'diagnostic'; diagnostic.mkdir()
            state = dict.fromkeys(audit.KEYS, 0)
            state.update(stageRuns=1, stageCandidates=2304, stageFloorObstacle=2000,
                         stageObservedFloor=200, stageBoxMargin=4, stageClear=100,
                         dropClearancePass=10, dropClearanceFail=90, routeFail=10)
            def write_state():
                trace.write_text(json.dumps({'case': {'dockVision': {'clearanceDiagnostic': state}}}) + '\n')
            write_state()
            path = diagnostic / 'search-1-candidate-2.json'
            path.write_text(json.dumps({'reason': 3, 'clearanceDetail': 2}))
            report = audit.clearance(trace, diagnostic)
            self.assertEqual(report['stage']['stageObservedFloor'], 200)
            self.assertEqual(report['circularViewpointClearanceDetailCounts']['2'], 1)
            state['stageObservedFloor'] += 1; write_state()
            with self.assertRaises(ValueError): audit.clearance(trace, diagnostic)
            state['stageObservedFloor'] -= 1; state['routeFail'] = 11; write_state()
            with self.assertRaises(ValueError): audit.clearance(trace, diagnostic)
            state['routeFail'] = 10; write_state(); path.write_text(json.dumps({'reason': 3, 'clearanceDetail': 0}))
            with self.assertRaises(ValueError): audit.clearance(trace, diagnostic)


    def test_complete_matched_saved_audit(self):
        with tempfile.TemporaryDirectory(prefix='clearance-full-audit-') as temp:
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
                            'surveyDiagnostic': {'count': captured, 'planCount': 0, 'writeErrors': 0},
                            'clearanceDiagnostic': dict.fromkeys(audit.KEYS, 0)}
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
                self.assertEqual(result['clearanceDiagnostic']['candidate-search']['stage']['stageRuns'], 0)
                trace_path = root / 'candidate-search/run/trace.jsonl'
                result_path = root / 'candidate-search/run/result.json'
                original_trace = trace_path.read_text()
                original_result = result_path.read_text()
                def replace_last_trace(edit):
                    records = [json.loads(line) for line in original_trace.splitlines()]
                    edit(records[-1])
                    trace_path.write_text(''.join(json.dumps(row) + '\n' for row in records))
                    output = json.loads(original_result); output['traceSHA256'] = audit.base.sha(trace_path)
                    fixture.write_json(result_path, output)
                replace_last_trace(lambda row: row['case']['dockVision']['clearanceDiagnostic'].update(stageCandidates=1))
                with self.assertRaises(ValueError): audit.audit(root)
                replace_last_trace(lambda row: row['case'].update(phase='aiming TCP camera'))
                with self.assertRaises(ValueError): audit.audit(root)
                trace_path.write_text(original_trace); result_path.write_text(original_result)
                (root / 'candidate-search/diagnostic/survey-1.rgb').unlink()
                with self.assertRaises(ValueError): audit.audit(root)


if __name__ == '__main__': unittest.main()
