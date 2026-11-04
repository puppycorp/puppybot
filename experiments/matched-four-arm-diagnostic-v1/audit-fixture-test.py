#!/usr/bin/env python3
"""Adversarial CPU-only checks for cross-root diagnostic inputs and pairing."""
import copy
import hashlib
import importlib.util
import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('matched_four_arm_fixture', HERE / 'runner.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def dump(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, sort_keys=True) + '\n')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clean_status():
    return {'clientExit': 0, 'timedOut': False, 'remainingWorkersTerminated': False,
            'signal': None, 'processGroup': 123}


def games(delivered=()):
    return [{'seed': 7820000 + i, 'completedDelivery': i in delivered} for i in range(32)]


def arms():
    values = {'parent': {0, 1}, 'control': {0, 2}, 'treatment': {0, 1, 3}, 'teacher': {0, 3}}
    return {name: {'games': 32, 'actions': 9600, 'deliveries': len(done),
                   'gamesWithDelivery': len(done), 'perGame': games(done)}
            for name, done in values.items()}


class PairTests(unittest.TestCase):
    def test_reference_wins_losses_are_paired_by_seed(self):
        result = runner.pairs(arms())['comparisons']
        self.assertEqual(result['control']['parent']['pairedGameWins'], 1)
        self.assertEqual(result['control']['parent']['pairedGameLosses'], 1)
        self.assertEqual(result['treatment']['parent']['pairedGameWins'], 1)
        self.assertEqual(result['treatment']['parent']['pairedGameLosses'], 0)
        self.assertTrue(result['treatment']['teacher']['deliveryRateAtLeastReference'])

    def test_rejects_missing_arm_wrong_horizon_and_unpaired_seed(self):
        values = arms(); del values['parent']
        with self.assertRaises(ValueError): runner.pairs(values)
        values = arms(); values['teacher']['actions'] = 9599
        with self.assertRaises(ValueError): runner.pairs(values)
        values = arms(); values['teacher']['perGame'][4]['seed'] += 1
        with self.assertRaises(ValueError): runner.pairs(values)

    def test_rejects_common_duplicate_or_wrong_seed_range(self):
        values = arms()
        for item in values.values(): item['perGame'][4]['seed'] = item['perGame'][3]['seed']
        with self.assertRaises(ValueError): runner.pairs(values)
        values = arms()
        for item in values.values():
            for game in item['perGame']: game['seed'] += 1000
        with self.assertRaises(ValueError): runner.pairs(values)


class CrossRootFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.old = self.root / 'prior'; self.new = self.root / 'new'
        self.tasks = [{'name': f'L{i}', 'level': i, 'rows': []} for i in range(1, 6)]
        self.frozen = {'plan': 'fixture'}; dump(self.new / 'inputs.json', self.frozen)
        original = {'gamesWithDelivery': 1, 'deliveries': 1, 'backForthShare': 0.0}
        dump(self.old / 'report.json', {'strictAudit': {'tasks': {
            t['name']: {'results': {'control': original, 'teacher': original}} for t in self.tasks}}})
        self.models = {'parent': self.root / 'parent', 'control': self.root / 'control',
                       'treatment': self.root / 'treatment'}
        self.calls = []
        def task_audit(name, teacher_root, student_root, models):
            self.calls.append((name, teacher_root, student_root, models))
            return {'status': 'complete_diagnostic', 'results': {'control': original, 'treatment': original}}
        def read_games(root, arm):
            if arm == 'teacher' and root.parent != self.old:
                raise ValueError('teacher must come from sealed prior root')
            return [{'root': root, 'arm': arm, 'result': {}} for _ in range(32)]
        def summarize(value, _level):
            return {'games': 32, 'actions': 9600, 'gamesWithDelivery': 1, 'deliveries': 1,
                    'legacyBackForthActions': 0, 'perGame': games({0})}
        for task in self.tasks:
            for arm in ('control', 'treatment'):
                receipt = self.new / 'supervisors' / task['name'] / arm
                dump(receipt / 'invocation.json', {'argv': ['cmd', task['name'], arm],
                     'environment': {'level': task['level']}, 'wallSeconds': runner.ARM_SECONDS})
                dump(receipt / 'supervisor-result.json', clean_status())
        self.patches = [mock.patch.object(runner, 'OUTPUT', self.new),
                        mock.patch.object(runner, 'PRIOR_OUTPUT', self.old),
                        mock.patch.object(runner, 'MODELS', self.models),
                        mock.patch.object(runner, 'design', return_value={'tasks': self.tasks}),
                        mock.patch.object(runner.base, 'command', side_effect=lambda task, arm: ['cmd', task['name'], arm]),
                        mock.patch.object(runner.base, 'environment', side_effect=lambda level: {'level': level}),
                        mock.patch.object(runner.base.auditor, 'audit_task', side_effect=task_audit),
                        mock.patch.object(runner.metric, 'load_games', side_effect=read_games),
                        mock.patch.object(runner.metric, 'summarize', side_effect=summarize)]
        for patch in self.patches: patch.start(); self.addCleanup(patch.stop)

    def test_new_students_are_matched_to_the_sealed_prior_teacher(self):
        result = runner.reaudit(self.frozen)
        self.assertEqual(result['status'], 'diagnostic_only')
        self.assertEqual(len(self.calls), 5)
        for name, teacher, student, models in self.calls:
            self.assertEqual(teacher, self.old / name)
            self.assertEqual(student, self.new / name)
            self.assertEqual(models, {a: self.models[a] for a in ('control', 'treatment')})
            self.assertEqual(set(result['inclusiveMetrics'][name]), set(runner.ARMS))

    def test_censored_cross_root_or_failed_supervisor_is_rejected(self):
        runner.base.auditor.audit_task.side_effect = lambda *args: {'status': 'censored', 'reason': 'placement differs'}
        with self.assertRaisesRegex(ValueError, 'cross-root'): runner.reaudit(self.frozen)
        runner.base.auditor.audit_task.side_effect = None
        dump(self.new / 'supervisors/L1/control/supervisor-result.json', {'clientExit': 1})
        with self.assertRaisesRegex(ValueError, 'supervisor differs'): runner.reaudit(self.frozen)

    def test_rejects_nonlegacy_score_marker(self):
        runner.metric.load_games.side_effect = lambda _root, _arm: [
            {'result': {'backForthMetric': 'pose20-final-inclusive-v2'}} for _ in range(32)]
        with self.assertRaisesRegex(ValueError, 'legacy'): runner.reaudit(self.frozen)


class PriorFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plan = self.root / 'prior-plan.json'; self.monitor = self.root / 'monitor'; self.output = self.root / 'old'
        rows = []
        for i in range(32):
            scene = self.root / 'scenes' / str(i); scene.mkdir(parents=True)
            for name in ('case.json', 'environment.bin', 'layout.json'):
                (scene / name).write_bytes(f'{i}:{name}'.encode())
            rows.append({'index': i, 'seed': 7820000 + i, 'layout': 12 + i % 6,
                         'variant': i % 16, 'scene': str(scene)})
        self.tasks = [{'name': f'L{level}', 'level': level, 'rows': copy.deepcopy(rows)} for level in range(1, 6)]
        files = {str(Path(row['scene']) / name): digest(Path(row['scene']) / name)
                 for row in rows for name in ('case.json', 'environment.bin', 'layout.json')}
        for relative in ('build/flex/control/control', 'build/flex/control/simulator',
                         'build/flex/sim/puppybot.bin', 'evaluate.sh'):
            path = self.root / relative; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(relative.encode()); files[str(path)] = digest(path)
        self.runtime = {'hip': 'fixture-runtime'}
        self.models = {**runner.MODELS, 'parent': self.root / 'parent'}
        files[str(self.models['parent'] / 'weights.bin')] = runner.WEIGHTS['parent']
        self.old = {'status': 'frozen_before_play', 'design': {'tasks': copy.deepcopy(self.tasks),
                    'models': {'control': str(self.models['parent'])}},
                    'files': files, 'runtime': self.runtime}
        self.receipt_paths = {'evidenceSHA256': 'evidence.json', 'launchSHA256': 'launch.json',
            'telemetrySHA256': 'telemetry.jsonl', 'diskSHA256': 'disk.jsonl',
            'monitorResultSHA256': 'monitor-result.json', 'outerSupervisorStatusSHA256': 'outer-monitor/supervisor-result.json',
            'frozenManifestSHA256': 'frozen-manifest.json',
            'finalInventoryInvocationSHA256': 'final-inventory-monitor/invocation.json',
            'finalInventoryStatusSHA256': 'final-inventory-monitor/supervisor-result.json',
            'finalInventoryResultSHA256': 'final-inventory-monitor/client.log'}
        for path in ('evidence.json', 'launch.json', 'telemetry.jsonl', 'disk.jsonl',
                     'final-inventory-monitor/invocation.json'):
            dump(self.monitor / path, {})
        dump(self.monitor / 'monitor-result.json', {'status': 'passed'})
        dump(self.monitor / 'outer-monitor/supervisor-result.json', clean_status())
        dump(self.monitor / 'final-inventory-monitor/supervisor-result.json', clean_status())
        dump(self.monitor / 'final-inventory-monitor/client.log', {'status': 'final_inventory_verified'})
        self.write_prior()
        self.patches = [mock.patch.object(runner, 'ROOT', self.root),
                        mock.patch.object(runner, 'PRIOR_PLAN', self.plan),
                        mock.patch.object(runner, 'PRIOR_MONITOR', self.monitor),
                        mock.patch.object(runner, 'PRIOR_OUTPUT', self.output),
                        mock.patch.object(runner, 'PRIOR_COMPLETION', digest(self.monitor / 'completion.json')),
                        mock.patch.object(runner, 'MODELS', self.models),
                        mock.patch.object(runner, 'design', return_value={'tasks': self.tasks}),
                        mock.patch.object(runner.base.old, 'runtime_chain', return_value=self.runtime),
                        mock.patch.object(runner.base, 'EVALUATE', self.root / 'evaluate.sh')]
        for patch in self.patches: patch.start(); self.addCleanup(patch.stop)

    def write_prior(self, reanchor=False):
        dump(self.plan, self.old); dump(self.monitor / 'frozen-manifest.json', self.old)
        dump(self.output / 'inputs.json', self.old)
        done = {'status': 'diagnostic_only'}
        done.update({key: digest(self.monitor / relative) for key, relative in self.receipt_paths.items()})
        dump(self.monitor / 'completion.json', done)
        if reanchor: runner.PRIOR_COMPLETION = digest(self.monitor / 'completion.json')

    def test_valid_cross_root_prior_and_binary_pin(self):
        self.assertEqual(runner.prior_receipts()['sceneRows'], 160)
        (self.root / 'build/flex/control/simulator').write_bytes(b'wrong simulator')
        with self.assertRaisesRegex(ValueError, 'binary or evaluator'): runner.prior_receipts()

    def test_retargeted_hip_runtime_is_rejected(self):
        runner.base.old.runtime_chain.return_value = {'hip': 'different-runtime'}
        with self.assertRaisesRegex(ValueError, 'runtime'): runner.prior_receipts()

    def test_wrong_parent_alias_or_weight_is_rejected(self):
        self.old['design']['models']['control'] = str(self.root / 'other-parent')
        self.write_prior(reanchor=True)
        with self.assertRaisesRegex(ValueError, 'parent model identity'): runner.prior_receipts()
        self.old['design']['models']['control'] = str(self.models['parent'])
        self.old['files'][str(self.models['parent'] / 'weights.bin')] = 'wrong-hash'
        self.write_prior(reanchor=True)
        with self.assertRaisesRegex(ValueError, 'parent model identity'): runner.prior_receipts()

    def test_resealed_alternative_receipts_do_not_replace_pinned_completion(self):
        dump(self.monitor / 'evidence.json', {'different': 'but internally resealed'})
        self.write_prior()
        with self.assertRaisesRegex(ValueError, 'prior selection did not complete'): runner.prior_receipts()
        runner.PRIOR_COMPLETION = digest(self.monitor / 'completion.json')
        self.assertEqual(runner.prior_receipts()['sceneRows'], 160)

    def test_rejects_scene_tamper_and_failed_or_altered_monitor(self):
        scene = Path(self.tasks[0]['rows'][0]['scene']) / 'case.json'
        scene.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'scene bytes'): runner.prior_receipts()
        scene.write_bytes(b'0:case.json')
        dump(self.monitor / 'monitor-result.json', {'status': 'failed'})
        with self.assertRaisesRegex(ValueError, 'evidence changed'): runner.prior_receipts()

    def test_rejects_missing_or_extra_historical_levels(self):
        self.old['design']['tasks'].pop(); self.write_prior(reanchor=True)
        with self.assertRaises(ValueError): runner.prior_receipts()
        self.old['design']['tasks'] = copy.deepcopy(self.tasks) + [copy.deepcopy(self.tasks[0])]
        self.write_prior(reanchor=True)
        with self.assertRaises(ValueError): runner.prior_receipts()

    def test_rejects_wrong_row_order_even_if_both_sets_of_files_exist(self):
        self.old['design']['tasks'][0]['rows'][1], self.old['design']['tasks'][0]['rows'][2] = (
            self.old['design']['tasks'][0]['rows'][2], self.old['design']['tasks'][0]['rows'][1])
        self.write_prior(reanchor=True)
        with self.assertRaisesRegex(ValueError, 'rows differ'): runner.prior_receipts()


class TrainingFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.training = self.root / 'training'; self.training.mkdir()
        self.plan = self.root / 'training-plan.json'; dump(self.plan, {'status': 'registered'})
        self.models, self.weights, self.packages = {}, {}, {}
        for arm in ('parent', 'control', 'treatment'):
            model = self.root / ('model-' + arm); model.mkdir(); (model / 'weights.bin').write_bytes(arm.encode())
            self.models[arm] = model; self.weights[arm] = digest(model / 'weights.bin')
            if arm != 'parent':
                self.packages[arm] = {'weightsSHA256': self.weights[arm], 'checkpointRule': 'fixed epoch'}
        dump(self.training / 'guardian-result.json', {'status': 'passed', 'reason': None,
             'coordinatorExit': 0, 'descendantsTerminated': False, 'diskEmergency': False})
        dump(self.training / 'guardian-telemetry.jsonl', {})
        dump(self.training / 'final-result.json', {'status': 'full_epoch_pair_diagnostic_only',
             'planSHA256': digest(self.plan), 'report': {'arms': {a: {'fixedPackage': self.packages[a]}
                                                                   for a in ('control', 'treatment')}}})
        self.coordinator = {'status': 'full_epoch_pair_diagnostic_only', 'planSHA256': digest(self.plan),
                            'evidenceSHA256': {'final-result.json': digest(self.training / 'final-result.json')}}
        self.write_completion()
        self.patches = [mock.patch.object(runner, 'TRAINING', self.training),
                        mock.patch.object(runner, 'TRAINING_PLAN', self.plan),
                        mock.patch.object(runner, 'MODELS', self.models),
                        mock.patch.object(runner, 'WEIGHTS', self.weights),
                        mock.patch.object(runner, 'TRAIN_COMPLETION', digest(self.training / 'completion.json')),
                        mock.patch.object(runner.pair.audit, 'verify_package',
                                          side_effect=lambda _plan, arm: self.packages[arm])]
        for patch in self.patches: patch.start(); self.addCleanup(patch.stop)

    def write_completion(self):
        dump(self.training / 'coordinator-result.json', self.coordinator)
        dump(self.training / 'completion.json', {'status': 'full_epoch_pair_diagnostic_only',
             'planSHA256': digest(self.plan), 'coordinatorSHA256': digest(self.training / 'coordinator-result.json'),
             'guardianResultSHA256': digest(self.training / 'guardian-result.json'),
             'guardianTelemetrySHA256': digest(self.training / 'guardian-telemetry.jsonl')})

    def test_valid_training_receipt_and_changed_parent_weights(self):
        self.assertEqual(runner.training_receipts()['planSHA256'], digest(self.plan))
        (self.models['parent'] / 'weights.bin').write_bytes(b'altered')
        with self.assertRaisesRegex(ValueError, 'wrong parent model'): runner.training_receipts()

    def test_changed_evidence_and_package_cannot_be_laundered(self):
        dump(self.training / 'final-result.json', {'status': 'wrong'})
        with self.assertRaisesRegex(ValueError, 'report'): runner.training_receipts()
        # Restoring the report and then changing a bound coordinator is rejected
        # by the immutable completion hash before its contents can be trusted.
        self.coordinator['evidenceSHA256']['forged'] = '0' * 64
        dump(self.training / 'coordinator-result.json', self.coordinator)
        with self.assertRaisesRegex(ValueError, 'receipt changed'): runner.training_receipts()

    def test_tampered_completion_and_guardian_status_are_rejected(self):
        original = (self.training / 'completion.json').read_bytes()
        (self.training / 'completion.json').write_bytes(original + b' ')
        with self.assertRaisesRegex(ValueError, 'completion differs'): runner.training_receipts()
        (self.training / 'completion.json').write_bytes(original)
        dump(self.training / 'guardian-result.json', {'status': 'failed', 'reason': 'test'})
        with self.assertRaisesRegex(ValueError, 'receipt changed'): runner.training_receipts()


class DeepInputsFixture(unittest.TestCase):
    def setUp(self):
        self.frozen = {'plan': 'matched'}
        self.old = {'design': 'legacy'}
        self.previous_report = {'legacy': 'report'}
        self.previous_files = {'legacy': 'inventory'}
        self.training_report = {'matched': 'training'}
        self.training_files = {'matched': 'inventory'}
        self.guardian_pid = 84321
        self.parent_pid = 84320
        self.old_plan, self.old_output, self.old_monitor, self.train = (Path('/fixture') / name for name in
                            ('old-plan', 'old-output', 'old-monitor', 'training'))
        values = {self.old_plan: self.old,
                  self.old_monitor / 'evidence.json': {'status': 'diagnostic_only',
                      'report': self.previous_report, 'files': self.previous_files},
                  self.old_output / 'report.json': self.previous_report,
                  self.train / 'final-result.json': {'report': self.training_report,
                                                       'inventory': self.training_files},
                  self.train / 'guardian-launch.json': {'guardianPID': self.guardian_pid,
                                                        'parentPID': self.parent_pid},
                  self.train / 'launcher.json': {'argv': ['launch', str(self.parent_pid)],
                                                   'planSHA256': 'fixture-plan-sha',
                                                   'environment': {'fixture': 'env'}}}
        self.values = values
        previous = types.SimpleNamespace(verify_saved=lambda value: self.previous_report,
                          base=types.SimpleNamespace(monitor=types.SimpleNamespace(verify_logs=lambda _root: None)))
        def guardian(pid):
            if pid != self.guardian_pid or os.getpid() != self.parent_pid:
                raise ValueError('historical guardian identity differs')
        self.patches = [mock.patch.object(runner, 'PRIOR_PLAN', self.old_plan),
                        mock.patch.object(runner, 'PRIOR_OUTPUT', self.old_output),
                        mock.patch.object(runner, 'PRIOR_MONITOR', self.old_monitor),
                        mock.patch.object(runner, 'TRAINING', self.train),
                        mock.patch.object(runner, 'sha', return_value='fixture-plan-sha'),
                        mock.patch.object(runner, 'current', return_value=self.frozen),
                        mock.patch.object(runner, 'read', side_effect=lambda path: values[Path(path)]),
                        mock.patch.object(runner, 'previous', previous),
                        mock.patch.object(runner.catalog.postrun, 'expected_catalogs', return_value={'catalog': 'links'}),
                        mock.patch.object(runner.catalog.postrun, 'inventory', return_value=self.previous_files),
                        mock.patch.object(runner.pair, 'verify_arms', return_value=self.training_report),
                        mock.patch.object(runner.pair, 'inventory', return_value=self.training_files),
                        mock.patch.object(runner.pair.plan.smoke.plan, 'environment', return_value={'fixture': 'env'}),
                        mock.patch.object(runner.pair, 'verify_guardian', side_effect=guardian)]
        for patch in self.patches: patch.start(); self.addCleanup(patch.stop)

    def test_reaudits_historical_guardian_as_a_saved_record(self):
        result = runner.deep_inputs(self.frozen)
        self.assertEqual(result['status'], 'retained_inputs_consistent')
        self.assertEqual(result['priorGames'], 480)

    def test_late_changed_prior_inventory_and_final_source_drift_rejected(self):
        runner.catalog.postrun.inventory.return_value = {'changed': 'inventory'}
        with self.assertRaisesRegex(ValueError, 'prior selection inventory'): runner.deep_inputs(self.frozen)
        runner.catalog.postrun.inventory.return_value = self.previous_files
        runner.pair.inventory.return_value = {'changed': 'training inventory'}
        with self.assertRaisesRegex(ValueError, 'training output inventory'): runner.deep_inputs(self.frozen)
        runner.pair.inventory.return_value = self.training_files
        runner.current.side_effect = [self.frozen, {'different': 'source'}]
        with self.assertRaisesRegex(ValueError, 'changed during deep review'): runner.deep_inputs(self.frozen)

    def test_historical_parent_must_match_the_saved_launcher(self):
        self.values[self.train / 'launcher.json']['argv'][-1] = str(self.parent_pid + 1)
        with self.assertRaisesRegex(ValueError, 'historical training guardian identity'):
            runner.deep_inputs(self.frozen)


if __name__ == '__main__':
    unittest.main()
