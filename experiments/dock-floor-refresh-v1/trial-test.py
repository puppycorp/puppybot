#!/usr/bin/env python3
"""CPU-only checks for the staged same-binary retry trial and clock audit."""
import importlib.util
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


build = load('retry_build_test', HERE / 'build.py')
runner = load('retry_runner_test', HERE / 'run.py')
monitor = load('retry_monitor_test', HERE / 'monitor.py')
barrier = load('retry_barrier_test', HERE / 'barrier.py')
audit = load('retry_audit_test', HERE / 'audit.py')
fixture = load('retry_fixture', ROOT / 'experiments/physical-search-fallback-trial-v1/fixture_support.py')


def row(step, wait, frame, last, local=False, mapping=False, attempted=False, refreshes=0):
    state = {'waits': wait, 'lastFrameId': last, 'lastWorkerCompleteTick': step if wait else -1,
             'lastWallMs': 1000 if wait else -1, 'failures': 0}
    return {'step': step, 'totalSteps': step, 'timeMs': 1280 + step * 20,
            'case': {'boxSearch': {'floorRetry': {'attempted': attempted, 'mapping': mapping},
                                   'mapRefreshes': refreshes}},
            'discovery': {'workerBarrier': state, 'mapFrameId': frame,
                          'pickup': {'localDockMap': local, 'mappingHeldFloor': mapping}}}


class TrialTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='puppy-floor-retry-build-')
        cls.root = Path(cls.temp.name); cls.output = cls.root / 'build'
        cls.report = build.build(cls.output)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def trace(self, name, records):
        path = self.root / name
        path.write_text(''.join(json.dumps(item) + '\n' for item in records))
        return path

    def test_same_binary_build_and_option_guard(self):
        self.assertEqual(build.verify(self.output), self.report)
        for value, expected in (('0', 0), ('1', 0), ('bad', 2)):
            env = dict(os.environ, PUPPYBOT_SIM_DOCK_FLOOR_RETRY=value)
            done = subprocess.run([str(self.output / 'simulator'), '--help'], cwd=ROOT,
                                  env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(done.returncode, expected, done.stderr)
        with self.assertRaises(FileExistsError): build.build(self.output)

    def test_arm_environments_and_source_pins(self):
        for arm in runner.ARMS:
            env = runner.env_for('/tmp/trial', arm)
            self.assertEqual(env['PUPPYBOT_SIM_WORKER_BARRIER'], '1')
            self.assertEqual(env['PUPPYBOT_DOCK_HIGH_SURVEY'], '1')
            self.assertEqual(env['PUPPYBOT_SIM_OBSERVED_FOOTPRINT_V2'], '1')
            self.assertEqual(env[build.FLAG], '1' if arm == 'candidate-search' else '0')
        for path in (HERE / 'barrier.py', HERE / 'transform.py', HERE / 'audit.py',
                     ROOT / 'experiments/observed-footprint-matched-v1/audit.py',
                     ROOT / 'experiments/dock-barrier-rendered-v1/monitor.py'):
            self.assertIn(str(path), monitor.source_pins())
        self.assertIs(audit.prior.original.barrier, audit.barrier.barrier)

    def test_real_manifest_and_wrong_arm_flag_rejected(self):
        root = self.root / 'trial'; root.mkdir(); inputs = root / 'inputs'; inputs.mkdir()
        reference = runner.prior.base.base.REFERENCE / 'inputs'
        for name in ('case.json', 'environment.bin'): shutil.copyfile(reference / name, inputs / name)
        shutil.copytree(reference / 'model', inputs / 'model')
        worker = runner.hidden.supervisor.worker_snapshot(runner.env_for(root, 'baseline'))
        (root / 'worker-inputs.json').write_text(json.dumps(worker))
        manifest = {'schema': 'puppybot.physical-search-fallback-trial.v1', 'build': str(self.output),
                    'case': str(inputs / 'case.json'), 'environment': str(inputs / 'environment.bin'),
                    'model': str(inputs / 'model'), 'navigationLimit': 90, 'collectorPollLimit': 1499,
                    'wallSecondsPerArm': 300, 'files': runner.prior.base.base.pins(root, self.output)}
        for path in (HERE / 'barrier.py', HERE / 'transform.py',
                     ROOT / 'experiments/observed-footprint-matched-v1/audit.py',
                     ROOT / 'experiments/dock-barrier-rendered-v1/monitor.py'):
            self.assertIn(str(path), manifest['files'])
        runner.check_manifest(root, manifest)
        for arm in runner.ARMS:
            parent = root / arm; parent.mkdir()
            command = runner.prior.base.base.command_for(root, manifest, arm)
            (parent / 'command.json').write_text(json.dumps(command))
            (parent / 'environment.json').write_text(json.dumps(runner.env_for(root, arm)))
            runner.check_invocation(root, manifest, arm)
        env = runner.env_for(root, 'candidate-search'); env[build.FLAG] = '0'
        (root / 'candidate-search/environment.json').write_text(json.dumps(env))
        with self.assertRaises(ValueError): runner.check_invocation(root, manifest, 'candidate-search')

    def test_evidenced_local_map_reset_and_restore(self):
        a = row(0, 0, 0, -1)
        b = row(1, 1, 1, 1)
        c = row(2, 1, 0, 1, local=True, mapping=True, attempted=True, refreshes=1)
        c['discovery']['workerBarrier'] = dict(b['discovery']['workerBarrier'])
        d = row(3, 2, 3, 3, local=True, mapping=True, attempted=True, refreshes=1)
        e = row(4, 2, 1, 3, local=False, mapping=False, attempted=True, refreshes=1)
        e['discovery']['workerBarrier'] = dict(d['discovery']['workerBarrier'])
        report = barrier.barrier(self.trace('valid.jsonl', [a, b, c, d, e]))
        self.assertEqual(report['status'], 'complete', report)
        self.assertEqual([v['kind'] for v in report['mapSwitches']], ['enter_retry_local_map', 'restore_transit_map'])
        c['case']['boxSearch']['floorRetry']['attempted'] = False
        report = barrier.barrier(self.trace('forged-reset.jsonl', [a, b, c, d, e]))
        self.assertEqual(report['censorReason'], 'map_changed_without_observed_wait')
        c['case']['boxSearch']['floorRetry']['attempted'] = True
        e['discovery']['mapFrameId'] = 2
        report = barrier.barrier(self.trace('forged-restore.jsonl', [a, b, c, d, e]))
        self.assertEqual(report['censorReason'], 'map_changed_without_observed_wait')

    def test_unknown_clock_and_counter_changes_censor(self):
        a = row(0, 0, 0, -1); b = row(1, 1, 1, 1); b['timeMs'] += 1
        self.assertEqual(barrier.barrier(self.trace('bad-time.jsonl', [a, b]))['censorReason'], 'invalid_clock_offset_or_reversal')
        b['timeMs'] -= 1; c = row(2, 1, 0, 1)
        c['discovery']['workerBarrier'] = dict(b['discovery']['workerBarrier'])
        self.assertEqual(barrier.barrier(self.trace('unknown-reset.jsonl', [a, b, c]))['censorReason'], 'map_changed_without_observed_wait')

    def test_retry_metadata_tracks_one_bounded_attempt(self):
        records = [row(0, 0, 0, -1), row(1, 1, 1, 1),
                   row(2, 1, 0, 1, local=True, mapping=True, attempted=True, refreshes=1),
                   row(3, 1, 0, 1, local=True, mapping=False, attempted=True, refreshes=1)]
        path = self.trace('retry.jsonl', records)
        result = audit.retry_report(path, True)
        self.assertEqual((result['attemptTick'], result['mappingStartTick'], result['mappingEndTick']), (2, 2, 3))
        self.assertFalse(result['mappingActiveAtEnd'])
        with self.assertRaises(ValueError): audit.retry_report(path, False)
        records[-1]['case']['boxSearch']['floorRetry']['attempted'] = False
        with self.assertRaises(ValueError): audit.retry_report(self.trace('bad-retry.jsonl', records), True)

    def test_previous_control_trace_still_passes(self):
        path = ROOT / 'build/flex/sim/levels-v2/pitch82/observed-footprint-matched-monitored-v2/trial/baseline/run/trace.jsonl'
        result = barrier.barrier(path)
        self.assertEqual(result['status'], 'complete', result)
        self.assertEqual(len(result['waits']), 17)
        self.assertEqual(result['mapSwitches'], [])

    def test_synthetic_complete_audit_with_retry_reset(self):
        root = self.root / 'synthetic'; root.mkdir(); case = root / 'case.json'; case.write_text('{}')
        case_hash = hashlib.sha256(case.read_bytes()).hexdigest()
        binary, model, environment = root / 'build', root / 'model', root / 'environment.bin'
        environment.write_bytes(b'PBENV001' + bytes(112))
        files = {str(case): case_hash, str(environment): 'environment', str(audit.prior.original.base.hidden.ASSET): 'asset'}
        files.update({str(binary / name): name for name in ('simulator', 'baseline-simulator')})
        files.update({str(model / name): name for name in ('policy', 'weights.bin', 'receipt.json')})
        fixture.write_json(root / 'inputs.json', {'schema': 'puppybot.physical-search-fallback-trial.v1',
            'navigationLimit': 90, 'collectorPollLimit': 1499, 'case': str(case), 'environment': str(environment),
            'build': str(binary), 'model': str(model), 'files': files})
        keys = audit.prior.original.clearance.KEYS
        for arm in runner.ARMS:
            run = root / arm / 'run'; journal, intents, result = fixture.build_protocol(run, 'search', polls=1)
            journal[-2].update(owner=2, ack=5); result['collectorTerminal'] = True
            client = json.loads((run / 'inputs.json').read_text())
            client.update({'simulatorSHA256': 'baseline-simulator' if arm == 'baseline' else 'simulator',
                'caseSHA256': case_hash, 'environmentSHA256': 'environment', 'weightsSHA256': 'weights.bin',
                'policySHA256': 'policy', 'receiptSHA256': 'receipt.json', 'robotAssetSHA256': 'asset',
                'cameraPitch': 82, 'contactFeedback': 'unavailable-forced-zero'})
            fixture.write_json(run / 'inputs.json', client)
            diagnostic = run.parent / 'diagnostic'; diagnostic.mkdir()
            high = {'attempts': 0, 'accepted': 0, 'ikRejected': 0, 'moveRejected': 0, 'requestId': 0,
                    'settledStep': -1, 'armStillMatching': False, 'targetTicks': None}
            dock = {'frameId': -1, 'valid': False, 'surveyDiagnostic': {'count': 0, 'planCount': 0, 'writeErrors': 0},
                    'clearanceDiagnostic': dict.fromkeys(keys, 0)}
            trace = []
            for tick in range(100, journal[-1]['step'] + 1):
                active = arm == 'candidate-search' and tick >= 104
                state = {'waits': 0, 'lastFrameId': -1, 'lastWorkerCompleteTick': -1, 'lastWallMs': -1, 'failures': 0}
                if tick >= 102:
                    state = {'waits': 1, 'lastFrameId': 101, 'lastWorkerCompleteTick': 102, 'lastWallMs': 500, 'failures': 0}
                if active and tick >= 105:
                    state = {'waits': 2, 'lastFrameId': 104, 'lastWorkerCompleteTick': 105, 'lastWallMs': 600, 'failures': 0}
                frame = (0 if tick < 102 else 101) if not active else (0 if tick == 104 else 104)
                box = {'mapRefreshes': int(active)}
                if arm == 'candidate-search':
                    box['floorRetry'] = {'attempted': active, 'mapping': active and tick < 106}
                pickup = {'localDockMap': active, 'mappingHeldFloor': active and tick < 106}
                trace.append({'step': tick, 'totalSteps': tick, 'timeMs': tick * 20 + 1280, 'pose': [0, 0, 0],
                    'case': {'objects': [{'id': 'brick'}], 'container': {'position': [1, 2, 0]},
                             'dockVision': dock, 'surveyHigh': high, 'boxSearch': box},
                    'discovery': {'workerBarrier': state, 'mapFrameId': frame, 'pickup': pickup}})
            (run / 'trace.jsonl').write_text(''.join(json.dumps(item) + '\n' for item in trace))
            result['traceSHA256'] = audit.prior.original.base.sha(run / 'trace.jsonl')
            fixture.write_protocol(run, journal, intents, result, True)
            receipt = run.parent / 'monitor'; receipt.mkdir()
            fixture.write_json(receipt / 'supervisor-result.json', {'clientExit': 0, 'timedOut': False,
                'signal': None, 'remainingWorkersTerminated': False, 'processGroup': 123})
        fake_runner = type('FixtureRunner', (), {'check_manifest': lambda *args: None,
                                                'check_invocation': lambda *args: None})()
        manipulation = {'caseSHA256': case_hash, 'captures': [], 'releases': [], 'settledDeliveries': [],
                        'settledAtEnd': False, 'traceMeetsManipulationCriteria': False}
        done = subprocess.CompletedProcess([], 0, json.dumps(manipulation), '')
        base = audit.prior.original.base
        with mock.patch.object(base, 'load', return_value=fake_runner), mock.patch.object(base.subprocess, 'run', return_value=done):
            report = audit.audit(root)
        self.assertTrue(report['comparisonEligible'])
        self.assertEqual(report['floorRetry']['candidate-search']['attemptTick'], 104)
        self.assertEqual(report['floorRetry']['candidate-search']['mappingEndTick'], 106)
        self.assertEqual(report['workerBarrierDiagnostic']['arms']['candidate-search']['mapSwitches'][0]['kind'], 'enter_retry_local_map')
        self.assertFalse(report['mechanismEligible'])


if __name__ == '__main__': unittest.main()
