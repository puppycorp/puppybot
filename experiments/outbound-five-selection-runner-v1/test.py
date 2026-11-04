#!/usr/bin/env python3
"""CPU checks for a fresh catalog-aware fixed selection runner."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


runner = load('outbound_fixed_selection_test', HERE / 'runner.py')
prior_fixture = load('outbound_catalog_fixture', ROOT / 'experiments/fresh-policy-catalog-monitor-v1/test.py')


class RunnerTests(unittest.TestCase):
    def test_fixed_predeclared_design_and_arm_commands(self):
        design = runner.base.design()
        self.assertEqual(design['arms'], ['control', 'treatment', 'teacher'])
        self.assertEqual([task['level'] for task in design['tasks']], [1, 2, 3, 4, 5])
        self.assertEqual(design['models']['control'], str(runner.P / 'search-dagger-l35-4workers/student-s1'))
        self.assertEqual(design['models']['treatment'], str(runner.P / 'outbound-five-fixed-epoch1-v1'))
        for task in design['tasks']:
            self.assertEqual([row['seed'] for row in task['rows']], list(range(7820000, 7820032)))
            for arm in design['arms']:
                command = runner.base.command(task, arm)
                self.assertEqual(command.count('--explore-teacher'), int(arm == 'teacher'))
                self.assertEqual(command[command.index('--level') + 1], str(task['level']))

    def test_fresh_subprocess_reloads_v3_bindings(self):
        output = subprocess.check_output(runner.python_call('describe_configuration'), cwd=ROOT, text=True, timeout=20)
        value = json.loads(output)
        self.assertEqual(value['output'], str(runner.OUTPUT))
        self.assertEqual(value['manifest'], str(runner.MANIFEST))
        self.assertEqual(value['worker'], runner.python_call('run'))
        self.assertEqual(value['registrar'], str(HERE / 'runner.py'))

    def test_catalog_inventory_is_installed_for_every_configuration(self):
        sentinel = {'installed': True}
        with mock.patch.object(runner.strict_inventory, 'install', return_value=sentinel) as install:
            self.assertEqual(runner.configure_monitor(), sentinel)
            self.assertEqual(runner.configure_monitor(), sentinel)
        self.assertEqual(install.call_count, 2)
        self.assertEqual(runner.base.monitor.REGISTER, HERE / 'runner.py')
        self.assertEqual(runner.base.monitor.worker_command(), runner.python_call('run'))
        self.assertEqual(install.call_args.args[1:4], (runner.OUTPUT, runner.MONITOR, runner.MANIFEST))

    def test_training_receipt_requires_all_pins_and_clean_supervisors(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); mon = root / 'monitor'; worker = root / 'worker'; plan = root / 'plan.json'
            for path in (mon / 'outer-monitor', mon / 'final-inventory-monitor', worker):
                path.mkdir(parents=True)
            with (mock.patch.object(runner, 'TRAIN_PLAN', plan), mock.patch.object(runner, 'TRAIN_MONITOR', mon),
                  mock.patch.object(runner, 'TRAIN_WORKER', worker)):
                status = {'clientExit': 0, 'signal': None, 'timedOut': False,
                          'remainingWorkersTerminated': False, 'processGroup': 42}
                for path in runner.training_receipts().values():
                    path.parent.mkdir(parents=True, exist_ok=True); path.write_text('{}')
                for path in (mon / 'outer-monitor/supervisor-result.json',
                             mon / 'final-inventory-monitor/supervisor-result.json', worker / 'supervisor-result.json'):
                    path.write_text(json.dumps(status))
                (mon / 'monitor-result.json').write_text(json.dumps({'status': 'passed'}))
                (mon / 'final-inventory-monitor/client.log').write_text(json.dumps({'status': 'final_inventory_verified'}))
                completion = {'status': 'training_diagnostic_only'}
                completion.update({key: runner.sha(path) for key, path in runner.training_receipts().items()})
                (mon / 'completion.json').write_text(json.dumps(completion))
                self.assertEqual(runner.check_training_receipts(), completion)
                (mon / 'telemetry.jsonl').write_text('tampered')
                with self.assertRaisesRegex(ValueError, 'changed'):
                    runner.check_training_receipts()

    def test_reuse_requires_original_rows_and_frozen_selection_hashes(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); previous = root / 'old.json'; old_monitor = root / 'old-monitor.json'
            design = runner.base.design(); old = {'design': {'tasks': design['tasks']}}
            previous.write_text(json.dumps(old))
            old_monitor.write_text(json.dumps({'status': 'failed', 'reason': 'unsafe or vanished output directory'}))
            rows = []
            for task in design['tasks']:
                for row in task['rows']:
                    rows.append(dict(row, level=task['level'], files={name: 'scene-hash' for name in
                                ('case.json', 'environment.bin', 'layout.json')}))
            with (mock.patch.object(runner, 'PRIOR_SELECTION', previous), mock.patch.object(runner, 'PRIOR_MONITOR', old_monitor),
                  mock.patch.object(runner, 'sha', return_value='scene-hash')):
                training = {'inputs': {'design': {'evaluation': {'selectionManifest': str(previous),
                            'selectionManifestSHA256': 'scene-hash', 'selectionRows': rows}}}}
                self.assertEqual(runner.check_reused_selection(design, training)['sceneRows'], 160)
                missing = rows[0]['files'].pop('layout.json')
                with self.assertRaisesRegex(ValueError, 'scene inventory'):
                    runner.check_reused_selection(design, training)
                rows[0]['files']['layout.json'] = missing
                rows[0]['seed'] += 1
                with self.assertRaisesRegex(ValueError, 'training selection design'):
                    runner.check_reused_selection(design, training)
                rows[0]['seed'] -= 1; rows[0]['files']['case.json'] = 'tampered'
                with self.assertRaisesRegex(ValueError, 'scene bytes'):
                    runner.check_reused_selection(design, training)

    def test_imported_local_source_graph_includes_catalog_transitive_dependencies(self):
        paths = runner.loaded_local_sources((runner.base, runner.strict_inventory, runner.metric, runner.training))
        for path in ('experiments/fresh-policy-catalog-monitor-v1/adapter.py',
                     'experiments/fresh-policy-postrun-v1/verify.py',
                     'experiments/fresh-policy-comparison-v1/selection.py',
                     'experiments/outbound-five-selection-metrics-v1/metrics.py',
                     'experiments/outbound-five-trainer-v1/monitor.py'):
            self.assertIn(ROOT / path, paths)

    def test_saved_game_metrics_require_strict_audit_and_agreement(self):
        strict = {'status': 'diagnostic_only', 'pool': {'status': 'complete_diagnostic'}, 'tasks': {}}
        for level in range(1, 6):
            strict['tasks'][f'L{level}'] = {'results': {arm: {'gamesWithDelivery': 12, 'deliveries': 15,
                                                                  'backForthShare': 0.0}
                                                       for arm in runner.metric.ARMS}}
        summary = {'games': 32, 'actions': 9600, 'gamesWithDelivery': 12, 'deliveries': 15,
                   'legacyBackForthActions': 0}
        with (mock.patch.object(runner, 'old_reaudit', return_value=strict),
              mock.patch.object(runner.metric, 'load_games', return_value=[]),
              mock.patch.object(runner.metric, 'summarize', return_value=summary)):
            result = runner.strict_plus_metrics({'frozen': True})
            self.assertEqual(set(result['inclusiveMetrics']), {'L1', 'L2', 'L3', 'L4', 'L5'})
            self.assertEqual(result['strictAudit'], strict)
            self.assertEqual(set(result['comparisons']['L1']), {'candidateDeliveryRateAtLeastTeacher',
                'candidateDeliveredGamesAtLeastControl', 'candidateDeliveredGamesAtLeastTeacher', 'scope'})
            summary['deliveries'] = 14
            with self.assertRaisesRegex(ValueError, 'disagree'):
                runner.strict_plus_metrics({'frozen': True})
            summary['deliveries'] = 15; strict['pool']['status'] = 'censored'
            with self.assertRaisesRegex(ValueError, 'did not complete'):
                runner.strict_plus_metrics({'frozen': True})

    def test_current_uses_old_preflight_once_without_recursive_call(self):
        design = {'tasks': ['synthetic']}
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / 'training.json'; path.write_text('{}')
            with (mock.patch.object(runner, 'TRAIN_PLAN', path),
                  mock.patch.object(runner, 'old_current', return_value={'design': design, 'files': {}}) as old,
                  mock.patch.object(runner, 'check_reused_selection', return_value={'sceneRows': 160}),
                  mock.patch.object(runner, 'check_training_receipts', return_value={'status': 'training_diagnostic_only'})):
                result = runner.current()
                old.assert_called_once_with(include_history=False)
                self.assertEqual(result['history']['sceneRows'], 160)
                self.assertEqual(result['trainingCompletion']['status'], 'training_diagnostic_only')

    def test_launch_requires_complete_nested_freeze_receipts(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); outer = root / 'outer'; inner = root / 'inner'; plan = root / 'plan'
            outer.mkdir(); inner.mkdir(); plan.write_text('{}')
            for path in (outer / 'invocation.json', inner / 'launch.json', inner / 'worker-result.json'):
                path.write_text('{}')
            status = {'clientExit': 0, 'signal': None, 'timedOut': False,
                      'remainingWorkersTerminated': False, 'processGroup': 42}
            for path in (outer / 'supervisor-result.json', inner / 'supervisor-result.json'):
                path.write_text(json.dumps(status))
            inner_result = {'status': 'plan_registered_only', 'reason': None, 'supervisorStatus': status,
                            'supervisorSHA256': runner.sha(inner / 'supervisor-result.json'),
                            'planSHA256': runner.sha(plan), 'launchSHA256': runner.sha(inner / 'launch.json'),
                            'workerSHA256': runner.sha(inner / 'worker-result.json')}
            (inner / 'result.json').write_text(json.dumps(inner_result))
            outer_result = {'status': 'plan_registered_only', 'reason': None, 'supervisorStatus': status,
                            'supervisorSHA256': runner.sha(outer / 'supervisor-result.json'),
                            'planSHA256': runner.sha(plan), 'innerReceiptSHA256': runner.sha(inner / 'result.json'),
                            'invocationSHA256': runner.sha(outer / 'invocation.json')}
            (outer / 'result.json').write_text(json.dumps(outer_result))
            with (mock.patch.object(runner, 'FREEZE_OUTER', outer), mock.patch.object(runner, 'FREEZE_MONITOR', inner),
                  mock.patch.object(runner, 'MANIFEST', plan), mock.patch.object(runner.base, 'launch', return_value='ok') as launch):
                self.assertEqual(runner.launch(), 'ok'); launch.assert_called_once()
                for supervisor in (inner / 'supervisor-result.json', outer / 'supervisor-result.json'):
                    original = supervisor.read_text(); supervisor.unlink()
                    with self.assertRaisesRegex(ValueError, 'freeze did not complete'):
                        runner.launch()
                    supervisor.write_text(json.dumps(dict(status, clientExit=1)))
                    with self.assertRaisesRegex(ValueError, 'freeze did not complete'):
                        runner.launch()
                    supervisor.unlink(); target = root / ('target-' + supervisor.parent.name); target.write_text(original)
                    supervisor.symlink_to(target)
                    with self.assertRaisesRegex(ValueError, 'freeze did not complete'):
                        runner.launch()
                    supervisor.unlink(); supervisor.write_text(original)
                (inner / 'worker-result.json').write_text('tampered')
                with self.assertRaisesRegex(ValueError, 'freeze did not complete'):
                    runner.launch()

    def test_fresh_monitor_and_final_processes_install_catalog_adapter(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); output = root / 'fresh-policy-selection-v3'
            monitored = root / 'fresh-policy-selection-monitored-v3'
            manifest = root / 'fresh-policy-selection-plan-v3.json'
            frozen = prior_fixture.design(root)
            manifest.write_text(json.dumps(frozen)); monitored.mkdir()
            command = [sys.executable, '-B', '-I', str(HERE / 'fixture_driver.py')]
            args = [str(root), str(output), str(monitored), str(manifest)]
            worker = subprocess.run(command + ['worker'] + args, capture_output=True, text=True, timeout=30)
            self.assertEqual(worker.returncode, 0, worker.stdout + worker.stderr)
            self.assertEqual(json.loads(worker.stdout), {'worker': 'completed', 'catalogLinks': 160})
            final = subprocess.run(command + ['final'] + args, capture_output=True, text=True, timeout=30)
            self.assertEqual(final.returncode, 0, final.stdout + final.stderr)
            self.assertEqual(json.loads(final.stdout), {'status': 'final_inventory_verified'})
            expected = runner.strict_inventory.postrun.expected_catalogs(frozen)
            path = output / next(iter(expected)); path.unlink(); path.symlink_to(root, target_is_directory=True)
            changed = subprocess.run(command + ['final'] + args, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(changed.returncode, 0)
            self.assertIn('retargeted', changed.stderr)


if __name__ == '__main__': unittest.main()
