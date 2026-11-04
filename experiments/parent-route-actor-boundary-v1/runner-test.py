#!/usr/bin/env python3
"""Small CPU-only tests for collector commands, inventory and guardian receipts."""
import importlib.util
import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


runner = load('parent_route_runner_test', HERE / 'runner.py')
registration = runner.registration


class RunnerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.old = runner.OUTPUT; runner.OUTPUT = self.root / 'output'; runner.OUTPUT.mkdir()

    def tearDown(self):
        runner.OUTPUT = self.old; self.temp.cleanup()

    def test_registered_commands_only_change_binary_and_output_paths(self):
        prior = json.loads(registration.PRIOR.read_text())
        updated = registration.commands(prior)
        self.assertEqual(len(updated), 2)
        for shard, (old, new) in enumerate(zip(prior['commands'], updated)):
            self.assertEqual(new[0], str(registration.builder.OUTPUT / 'control'))
            self.assertEqual(new[new.index('--scene-catalog') + 1], str(registration.OUTPUT / 'catalogs' / str(shard)))
            self.assertEqual(new[new.index('--output') + 1], str(registration.OUTPUT / f'shard-{shard}'))
            for flag in ('--policy', '--episodes', '--validation', '--seed', '--level', '--camera-pitch'):
                self.assertEqual(new[new.index(flag) + 1], old[old.index(flag) + 1])
            self.assertIn('--record-map', new); self.assertIn('--lean', new)
            self.assertNotIn('--self-imitate', new)

    def test_catalog_and_inventory_reject_unplanned_links(self):
        scene = self.root / 'scene'; scene.mkdir()
        for name in ('case.json', 'environment.bin', 'layout.json'):
            (scene / name).write_text(name)
        plan = {'rows': [{'shard': 0, 'episode': 0, 'scene': str(scene),
                          'sceneSHA256': {name: registration.sha(scene / name) for name in
                                          ('case.json', 'environment.bin', 'layout.json')}}]}
        links = runner.catalog(plan, create=True)
        self.assertEqual(runner.inventory(links)['links'], links)
        (runner.OUTPUT / 'extra').symlink_to(scene, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'links differ'):
            runner.inventory(links)
        (runner.OUTPUT / 'extra').unlink()
        (scene / 'case.json').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'scene bytes'):
            runner.catalog(plan)

    def test_shard_failure_is_retained_and_rejected(self):
        plan = {'commands': [['fake']], 'environment': {}, 'thresholds': {'perShardSeconds': 1}}
        bad = {'clientExit': 1, 'timedOut': False, 'remainingWorkersTerminated': False,
               'signal': None, 'processGroup': 77}
        def supervise(argv, directory, env, deadline):
            (directory / 'supervisor-result.json').write_text(json.dumps(bad)); return bad
        with mock.patch.object(runner.hidden, 'supervise', side_effect=supervise):
            with self.assertRaisesRegex(RuntimeError, 'shard 0 failed'):
                runner.run_shard(plan, 0)
        self.assertTrue((runner.OUTPUT / 'monitor-0/invocation.json').is_file())
        self.assertTrue((runner.OUTPUT / 'monitor-0/supervisor-result.json').is_file())

    def test_first_shard_failure_prevents_second(self):
        plan = {'rows': [], 'commands': [['one'], ['two']], 'environment': {},
                'thresholds': {'perShardSeconds': 1}}
        attempted = []
        def fail_first(_plan, shard):
            attempted.append(shard)
            raise RuntimeError('simulated first shard failure')
        with mock.patch.object(runner.registration, 'verify', return_value=plan), \
                mock.patch.object(runner, 'catalog', return_value={}), \
                mock.patch.object(runner, 'run_shard', side_effect=fail_first), \
                mock.patch.object(runner.game_audit, 'audit') as audit:
            with self.assertRaisesRegex(RuntimeError, 'simulated first shard failure'):
                runner.worker()
            audit.assert_not_called()
        self.assertEqual(attempted, [0])
        self.assertFalse((runner.OUTPUT / 'worker-result.json').exists())

    def guardian_fixture(self):
        env = {'PATH': '/usr/bin:/bin'}; pid = 9999
        launch = {'guardianPID': pid, 'parentPID': os.getpid(), 'coordinatorPID': 9998,
                  'wallSeconds': 7500, 'startedMonotonic': 10.0, 'command': runner.coordinator_command(),
                  'environment': dict(env, PUPPY_TURN_GUARD_PID=str(pid), PUPPY_TURN_GUARD_FD='4',
                                      PUPPY_TURN_GUARD_OUTPUT=str(runner.OUTPUT))}
        rows = []
        phases = [(10.2 + i, 'active', i == 31) for i in range(32)] + [(42.2, 'cleanup', True), (42.3, 'cleanup', True)]
        for t, phase, passed in phases:
            volumes = {key: 40 * runner.GIB for key in ('workspace', 'home', 'output')}
            rows.append({'phase': phase, 'monotonicSeconds': t, 'baselinePassed': passed,
                         'freeBytes': 40 * runner.GIB, 'volumes': volumes, 'gpuFreeBytes': 8 * runner.GIB,
                         'gpuTotalBytes': 16 * runner.GIB, 'gpuUsedBytes': 8 * runner.GIB, 'gpuBusyPercent': 3})
        result = {'status': 'passed', 'reason': None, 'coordinatorExit': 0, 'descendantsTerminated': False,
                  'diskEmergency': False, 'samples': len(rows), 'observedDoneMonotonic': 42.1, 'endedMonotonic': 42.4}
        for name, value in (('guardian-launch.json', launch), ('guardian-result.json', result),
                            ('baseline-passed.json', {'status': 'passed', 'monotonicSeconds': 41.0})):
            (runner.OUTPUT / name).write_text(json.dumps(value))
        (runner.OUTPUT / 'guardian-telemetry.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
        baseline = [{'phase': 'baseline', 'monotonicSeconds': 10.5 + i,
                     'freeBytes': 8 * runner.GIB, 'totalBytes': 16 * runner.GIB,
                     'usedBytes': 8 * runner.GIB, 'busyPercent': 3} for i in range(31)]
        (runner.OUTPUT / 'baseline.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in baseline))
        return {'environment': env}, pid, rows

    def test_guardian_telemetry_rejects_baseline_floor_and_gaps(self):
        launch, pid, rows = self.guardian_fixture()
        self.assertEqual(runner.verify_guardian(runner.OUTPUT, launch, pid)['status'], 'passed')
        rows[0]['freeBytes'] = 37 * runner.GIB; rows[0]['volumes']['output'] = 37 * runner.GIB
        path = runner.OUTPUT / 'guardian-telemetry.jsonl'
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        with self.assertRaisesRegex(ValueError, 'resource sample'):
            runner.verify_guardian(runner.OUTPUT, launch, pid)
        rows[0]['freeBytes'] = 40 * runner.GIB; rows[0]['volumes']['output'] = 40 * runner.GIB
        rows[1]['monotonicSeconds'] = 14.0
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        with self.assertRaisesRegex(ValueError, 'coverage'):
            runner.verify_guardian(runner.OUTPUT, launch, pid)

    def test_baseline_busy_or_short_window_is_rejected(self):
        launch, pid, _ = self.guardian_fixture()
        path = runner.OUTPUT / 'baseline.jsonl'
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        for row in rows[5:10]:
            row['busyPercent'] = 11
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        with self.assertRaisesRegex(ValueError, 'GPU busy'):
            runner.verify_guardian(runner.OUTPUT, launch, pid)
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows[:10]))
        with self.assertRaisesRegex(ValueError, 'coverage'):
            runner.verify_guardian(runner.OUTPUT, launch, pid)

    def test_final_checker_rejects_output_added_after_worker(self):
        plan_path = self.root / 'plan.json'; plan_path.write_text('{}')
        report = {'status': 'diagnostic_only'}
        runner.write_new(runner.OUTPUT / 'report.json', report)
        frozen = runner.inventory({})
        runner.write_new(runner.OUTPUT / 'inventory.json', frozen)
        runner.write_new(runner.OUTPUT / 'worker-result.json', {
            'status': 'collection_diagnostic_only',
            'reportSHA256': registration.sha(runner.OUTPUT / 'report.json'),
            'inventorySHA256': registration.sha(runner.OUTPUT / 'inventory.json')})
        (runner.OUTPUT / 'unexpected').write_text('late mutation')
        with mock.patch.object(registration, 'PLAN', plan_path), \
                mock.patch.object(registration, 'verify', return_value={}), \
                mock.patch.object(runner, 'verify_shards'), \
                mock.patch.object(runner, 'catalog', return_value={}), \
                mock.patch.object(runner.game_audit, 'audit') as audit:
            with self.assertRaisesRegex(ValueError, 'changed after worker'):
                runner.final_check()
            audit.assert_not_called()

    def test_coordinator_never_starts_final_after_worker_failure(self):
        plan = {'environment': {}}
        phases = []
        def fail_worker(_plan, name, function, seconds):
            phases.append((name, function))
            raise RuntimeError('worker failed')
        with mock.patch.object(registration, 'verify', return_value=plan), \
                mock.patch.object(runner.telemetry, 'baseline'), \
                mock.patch.object(runner, 'supervise_phase', side_effect=fail_worker):
            with self.assertRaisesRegex(RuntimeError, 'worker failed'):
                runner.coordinator()
        self.assertEqual(phases, [('worker-supervisor', 'worker')])
        self.assertFalse((runner.OUTPUT / 'coordinator-result.json').exists())

    def test_supervisor_log_change_after_coordinator_is_rejected(self):
        for name in ('worker-supervisor', 'final-supervisor'):
            directory = runner.OUTPUT / name; directory.mkdir()
            for child in ('supervisor-result.json', 'invocation.json', 'client.log'):
                (directory / child).write_text(name + child)
        receipt = runner.supervisor_hashes()
        runner.verify_supervisor_hashes(receipt)
        (runner.OUTPUT / 'final-supervisor/client.log').write_text('late mutation')
        with self.assertRaisesRegex(ValueError, 'supervisor evidence changed'):
            runner.verify_supervisor_hashes(receipt)

    def test_changed_pin_after_guardian_is_rejected(self):
        plan_path = self.root / 'plan.json'; plan_path.write_text('{}')
        expected = {'frozen': True}
        with mock.patch.object(registration, 'PLAN', plan_path), \
                mock.patch.object(runner.shutil, 'disk_usage', return_value=types.SimpleNamespace(free=40 * runner.GIB)), \
                mock.patch.object(registration, 'verify', return_value={'frozen': False}):
            with self.assertRaisesRegex(ValueError, 'inputs changed after guardian'):
                runner.verify_post_guard(expected, registration.sha(plan_path))


if __name__ == '__main__':
    unittest.main()
