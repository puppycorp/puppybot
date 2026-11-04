#!/usr/bin/env python3
"""CPU checks for the opt-in same-binary footprint comparison build."""
import importlib.util
import json
import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location('matched_footprint_builder', HERE / 'build.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)
spec = importlib.util.spec_from_file_location('matched_footprint_runner', HERE / 'run.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
spec = importlib.util.spec_from_file_location('matched_footprint_monitor', HERE / 'monitor.py')
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)
spec = importlib.util.spec_from_file_location('matched_footprint_audit', HERE / 'audit.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
spec = importlib.util.spec_from_file_location('matched_footprint_build_supervisor', HERE / 'build-supervisor.py')
supervisor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(supervisor)
spec = importlib.util.spec_from_file_location('matched_footprint_fixture', ROOT / 'experiments/physical-search-fallback-trial-v1/fixture_support.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class MatchedFootprintBuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='puppy-footprint-matched-')
        cls.root = Path(cls.temp.name)
        cls.output = cls.root / 'build'
        cls.report = build.build(cls.output)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_option_dispatch_is_bounded_and_invalid_is_rejected(self):
        binary = self.output / 'simulator'
        for value, expected in (('0', 0), ('1', 0), ('invalid', 2)):
            with self.subTest(option=value):
                env = dict(os.environ, PUPPYBOT_SIM_OBSERVED_FOOTPRINT_V2=value)
                result = subprocess.run([str(binary), '--help'], cwd=ROOT, env=env,
                                        text=True, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, expected, result.stderr)
        self.assertEqual(build.verify(self.output), self.report)

    def test_native_dispatch_changes_the_known_missed_overlap(self):
        probe_root = self.root / 'probe-root'; probe_root.mkdir()
        source = probe_root / 'source'; shutil.copytree(self.output / 'source', source)
        shutil.copytree(self.output / 'build', probe_root / 'build')
        library = probe_root / 'build/flex/sim/library'
        adapter = library / 'lib/f64.flex'
        adapter.write_text(build.once(adapter.read_text(),
            f'import "{self.output / "source/core/words.flex"}";',
            f'import "{source / "core/words.flex"}";'))
        deps = library.parent / 'dependencies.flex'
        deps.write_text(f'import "{library / "libs/render.flex"}";\nimport "{library / "libs/physics/physics.flex"}";\n')
        main = source / 'sim/main.flex'; text = main.read_text()
        probe = '''\nfn main(argc, argv) {
    if !pl_init() { return 1; }
    ps_nav_observed_v2 = argc == 2; ps_discovery_enabled = 1; ps_nav_columns = 200; ps_nav_rows = 200;
    ps_discovery_observed = alloc(40000); pb_zero(ps_discovery_observed, 40000);
    store8(ps_discovery_observed + 102 * 200 + 99, 1);
    return ps_nav_observed_clear(ps_number(15,1000), ps_number(85,1000), f64_mul(PB_PI,ps_number(5,180)));
}\n'''
        main.write_text(build.once(text, 'fn main(argc, argv) {', 'fn original_main(argc, argv) {') + probe)
        binary = self.root / 'probe'
        compiled = subprocess.run([str(build.COMPILER), str(main), '-o', str(binary)], cwd=ROOT,
                                  capture_output=True, text=True, timeout=120)
        self.assertEqual(compiled.returncode, 0, compiled.stderr)
        # Returning 1 means legacy incorrectly accepted the blocked footprint.
        self.assertEqual(subprocess.run([str(binary)], cwd=ROOT, timeout=10).returncode, 1)
        self.assertEqual(subprocess.run([str(binary), 'v2'], cwd=ROOT, timeout=10).returncode, 0)
        self.assertEqual(build.verify(self.output), self.report)

    def test_tampered_source_rejected_and_original_restored(self):
        nav = self.output / 'source/sim/navigation.flex'
        original = nav.read_bytes()
        try:
            nav.write_bytes(original + b'\n// tampered\n')
            with self.assertRaises(ValueError): build.verify(self.output)
        finally:
            nav.write_bytes(original)
        self.assertEqual(build.verify(self.output), self.report)

    def test_existing_output_refused(self):
        with self.assertRaises(FileExistsError): build.build(self.output)
        self.assertEqual(build.verify(self.output), self.report)

    def test_monitor_reimport_and_arm_environments(self):
        for arm in runner.ARMS:
            env = runner.env_for('/tmp/trial', arm)
            self.assertEqual(env['PUPPYBOT_SIM_WORKER_BARRIER'], '1')
            self.assertEqual(env['PUPPYBOT_DOCK_HIGH_SURVEY'], '1')
            self.assertEqual(env[build.FLAG], '1' if arm == 'candidate-search' else '0')
            self.assertEqual(env['PUPPYBOT_DOCK_DIAG_DIRECTORY'], '/tmp/trial/' + arm + '/diagnostic')
        self.assertIn(str(HERE / 'monitor.py'), monitor.base.worker_command('/tmp/o', '/tmp/b', '/tmp/c', '/tmp/e', '/tmp/m'))
        pins = monitor.source_pins()
        for path in (HERE / 'run.py', HERE / 'audit.py', HERE / 'build.py', build.CURRENT,
                     ROOT / 'experiments/dock-barrier-postrun-v1/audit.py',
                     ROOT / 'experiments/dock-barrier-rendered-v1/monitor.py'):
            self.assertIn(str(path), pins)
        self.assertIn(str(HERE / 'build-supervisor.py'), supervisor.base.command())
        for path in (HERE / 'build.py', HERE / 'run.py', build.CURRENT):
            self.assertIn(str(path), supervisor.sources())

    def test_actual_frozen_manifest_and_invocation_reject_wrong_flag(self):
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
        self.assertIn(str(ROOT / 'experiments/dock-barrier-rendered-v1/monitor.py'), manifest['files'])
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

    def test_offset_parser_is_the_corrected_one(self):
        self.assertIs(audit.original.barrier, audit.clock.barrier)
        trace = self.root / 'clock.jsonl'
        empty = {'waits': 0, 'lastFrameId': -1, 'lastWorkerCompleteTick': -1, 'lastWallMs': -1, 'failures': 0}
        complete = {'waits': 1, 'lastFrameId': 1, 'lastWorkerCompleteTick': 2, 'lastWallMs': 500, 'failures': 0}
        records = [{'step': 0, 'totalSteps': 0, 'timeMs': 1280},
                   {'step': 1, 'totalSteps': 1, 'timeMs': 1300, 'discovery': {'workerBarrier': empty, 'mapFrameId': 0}},
                   {'step': 2, 'totalSteps': 2, 'timeMs': 1320, 'discovery': {'workerBarrier': complete, 'mapFrameId': 1}}]
        trace.write_text(''.join(json.dumps(row) + '\n' for row in records))
        self.assertEqual(audit.original.barrier(trace)['status'], 'complete')
        records[-1]['timeMs'] += 1
        trace.write_text(''.join(json.dumps(row) + '\n' for row in records))
        self.assertEqual(audit.original.barrier(trace)['censorReason'], 'invalid_clock_offset_or_reversal')

    def test_complete_synthetic_audit_uses_same_survey_and_censors_mechanism(self):
        root = self.root / 'synthetic-trial'; root.mkdir()
        case = root / 'case.json'; case.write_text('{}')
        case_hash = hashlib.sha256(case.read_bytes()).hexdigest()
        binary = root / 'fake-build'; model = root / 'fake-model'; environment = root / 'environment.bin'
        environment.write_bytes(b'PBENV001' + bytes(112))
        files = {str(case): case_hash, str(environment): 'environment', str(audit.original.base.hidden.ASSET): 'asset'}
        files.update({str(binary / name): name for name in ('simulator', 'baseline-simulator')})
        files.update({str(model / name): name for name in ('policy', 'weights.bin', 'receipt.json')})
        fixture.write_json(root / 'inputs.json', {'schema': 'puppybot.physical-search-fallback-trial.v1',
            'navigationLimit': 90, 'collectorPollLimit': 1499, 'case': str(case), 'environment': str(environment),
            'build': str(binary), 'model': str(model), 'files': files})
        keys = audit.original.clearance.KEYS
        for arm in runner.ARMS:
            run = root / arm / 'run'
            journal, intents, result = fixture.build_protocol(run, 'search', polls=1)
            journal[-2].update(owner=2, ack=5)
            result['collectorTerminal'] = True
            client = json.loads((run / 'inputs.json').read_text())
            client.update({'simulatorSHA256': 'baseline-simulator' if arm == 'baseline' else 'simulator',
                'caseSHA256': case_hash, 'environmentSHA256': 'environment', 'weightsSHA256': 'weights.bin',
                'policySHA256': 'policy', 'receiptSHA256': 'receipt.json', 'robotAssetSHA256': 'asset',
                'cameraPitch': 82, 'contactFeedback': 'unavailable-forced-zero'})
            fixture.write_json(run / 'inputs.json', client)
            final = journal[-1]['step']; diagnostic = run.parent / 'diagnostic'; diagnostic.mkdir()
            empty = {'waits': 0, 'lastFrameId': -1, 'lastWorkerCompleteTick': -1, 'lastWallMs': -1, 'failures': 0}
            complete = {'waits': 1, 'lastFrameId': 101, 'lastWorkerCompleteTick': 102, 'lastWallMs': 500, 'failures': 0}
            high = {'attempts': 0, 'accepted': 0, 'ikRejected': 0, 'moveRejected': 0, 'requestId': 0,
                    'settledStep': -1, 'armStillMatching': False, 'targetTicks': None}
            dock = {'frameId': -1, 'valid': False, 'surveyDiagnostic': {'count': 0, 'planCount': 0, 'writeErrors': 0},
                    'clearanceDiagnostic': dict.fromkeys(keys, 0)}
            trace = []
            for tick in range(100, final + 1):
                row = {'step': tick, 'totalSteps': tick, 'timeMs': tick * 20 + 1280, 'pose': [0, 0, 0],
                    'case': {'objects': [{'id': 'brick'}], 'container': {'position': [1, 2, 0]},
                             'dockVision': dock, 'surveyHigh': high},
                    'discovery': {'workerBarrier': empty if tick < 102 else complete,
                                  'mapFrameId': 0 if tick < 102 else 101}}
                trace.append(row)
            (run / 'trace.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in trace))
            result['traceSHA256'] = audit.original.base.sha(run / 'trace.jsonl')
            fixture.write_protocol(run, journal, intents, result, True)
            receipt = run.parent / 'monitor'; receipt.mkdir()
            fixture.write_json(receipt / 'supervisor-result.json', {'clientExit': 0, 'timedOut': False,
                'signal': None, 'remainingWorkersTerminated': False, 'processGroup': 123})
        fake_runner = type('FixtureRunner', (), {'check_manifest': lambda *args: None,
                                                'check_invocation': lambda *args: None})()
        manipulation = {'caseSHA256': case_hash, 'captures': [], 'releases': [], 'settledDeliveries': [],
                        'settledAtEnd': False, 'traceMeetsManipulationCriteria': False}
        done = subprocess.CompletedProcess([], 0, json.dumps(manipulation), '')
        with mock.patch.object(audit.original.base, 'load', return_value=fake_runner), \
                mock.patch.object(audit.original.base.subprocess, 'run', return_value=done):
            report = audit.audit(root)
        self.assertTrue(report['comparisonEligible'])
        self.assertTrue(report['workerBarrierDiagnostic']['matchedControlMapApplications'])
        self.assertTrue(all(report['highSurvey'][arm]['enabled'] for arm in runner.ARMS))
        self.assertFalse(report['mechanismEligible'])
        self.assertEqual(report['mechanismCensorReason'], 'guard_effect_not_instrumented')


if __name__ == '__main__':
    unittest.main()
