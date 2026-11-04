#!/usr/bin/env python3
"""CPU fixtures for pair-worker failure retention and guardian evidence."""
import importlib.util
import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('paired_supervisor', HERE / 'supervise.py')
supervise = importlib.util.module_from_spec(spec); spec.loader.exec_module(supervise)
plan = supervise.plan


class SupervisionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.old_output, self.old_monitor = plan.OUTPUT, plan.MONITOR
        plan.OUTPUT = self.root / 'out'; plan.MONITOR = self.root / 'monitor'; plan.MONITOR.mkdir()

    def tearDown(self):
        plan.OUTPUT, plan.MONITOR = self.old_output, self.old_monitor
        self.temp.cleanup()

    def test_first_arm_retained_when_second_reservation_fails(self):
        frozen = {'frozen': True}
        def first(_data, _maps, _shards, output, _selected):
            output.mkdir(); (output / 'data.bin').write_bytes(b'data'); (output / 'map.bin').write_bytes(b'map')
            return {'reservation': {'minimumFreeBytes': 1}}
        with mock.patch.object(supervise, 'priority', return_value={'cpuNice': 15, 'ioClass': 'idle'}), \
                mock.patch.object(plan, 'verify_plan', return_value=frozen), \
                mock.patch.object(plan.builder, 'create_control', side_effect=first), \
                mock.patch.object(plan.builder, 'create_treatment', side_effect=ValueError('insufficient free space')), \
                mock.patch.object(supervise, 'verify_outputs') as verify:
            with self.assertRaisesRegex(ValueError, 'insufficient free space'):
                supervise.worker()
            verify.assert_not_called()
        self.assertTrue((plan.OUTPUT / 'control/data.bin').is_file())
        self.assertFalse((plan.OUTPUT / 'treatment').exists())
        self.assertTrue((plan.MONITOR / 'control-result.json').is_file())
        self.assertFalse((plan.MONITOR / 'worker-result.json').exists())

    def test_inventory_rejects_extra_file_or_symlink(self):
        plan.OUTPUT.mkdir()
        for arm in ('control', 'treatment'):
            directory = plan.OUTPUT / arm; directory.mkdir()
            for name in ('data.bin', 'map.bin'): (directory / name).write_text(arm + name)
        (plan.OUTPUT / 'report.json').write_text('{}')
        self.assertEqual(len(supervise.output_inventory()), 5)
        (plan.OUTPUT / 'extra').write_text('unplanned')
        with self.assertRaisesRegex(ValueError, 'inventory differs'):
            supervise.output_inventory()
        (plan.OUTPUT / 'extra').unlink()
        (plan.OUTPUT / 'control/data.bin').unlink()
        (plan.OUTPUT / 'control/data.bin').symlink_to(plan.OUTPUT / 'treatment/data.bin')
        with self.assertRaisesRegex(ValueError, 'unsafe paired output file'):
            supervise.output_inventory()

    def test_inventory_rejects_output_hardlinked_outside_known_tree(self):
        plan.OUTPUT.mkdir()
        for arm in ('control', 'treatment'):
            directory = plan.OUTPUT / arm; directory.mkdir()
            for name in ('data.bin', 'map.bin'): (directory / name).write_text(arm + name)
        (plan.OUTPUT / 'report.json').write_text('{}')
        self.assertEqual(len(supervise.output_inventory()), 5)
        os.link(plan.OUTPUT / 'control/data.bin', self.root / 'outside-hardlink')
        with self.assertRaisesRegex(ValueError, 'unsafe paired output file'):
            supervise.output_inventory()

    def test_inventory_rejects_symlink_at_output_root(self):
        target = self.root / 'elsewhere'; target.mkdir()
        plan.OUTPUT.symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'unsafe paired output root'):
            supervise.output_inventory()

    def test_worker_failure_prevents_final_checker(self):
        calls = []
        def fail(name, function, seconds):
            calls.append((name, function)); raise RuntimeError('simulated worker failure')
        with mock.patch.object(plan, 'verify_plan', return_value={'valid': True}), \
                mock.patch.object(supervise, 'supervise_phase', side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, 'simulated worker failure'):
                supervise.coordinator()
        self.assertEqual(calls, [('worker-supervisor', 'worker')])
        self.assertFalse((plan.MONITOR / 'coordinator-result.json').exists())

    def test_supervisor_hashes_detect_modified_final_log(self):
        for phase in ('worker-supervisor', 'final-supervisor'):
            directory = plan.MONITOR / phase; directory.mkdir()
            for filename in ('client.log', 'invocation.json', 'supervisor-result.json'):
                (directory / filename).write_text(phase + filename)
        saved = supervise.supervisor_hashes()
        (plan.MONITOR / 'final-supervisor/client.log').write_text('tampered')
        self.assertNotEqual(saved, supervise.supervisor_hashes())

    def test_supervisor_receipts_reject_changed_invocation_and_boolean_exit(self):
        clean = {'clientExit': 0, 'timedOut': False, 'remainingWorkersTerminated': False,
                 'signal': None, 'processGroup': 42}
        for phase, function, seconds in (('worker-supervisor', 'worker', 3600),
                                         ('final-supervisor', 'final_check', 2400)):
            directory = plan.MONITOR / phase; directory.mkdir()
            (directory / 'invocation.json').write_text(json.dumps({'argv': supervise.command(function),
                'environment': supervise.environment(), 'wallSeconds': seconds}))
            (directory / 'supervisor-result.json').write_text(json.dumps(clean))
        supervise.verify_phase_results()
        path = plan.MONITOR / 'worker-supervisor/supervisor-result.json'
        status = json.loads(path.read_text()); status['clientExit'] = False; path.write_text(json.dumps(status))
        with self.assertRaisesRegex(ValueError, 'invocation or status'):
            supervise.verify_phase_results()

    def test_post_guard_rejects_changed_output_and_changed_source(self):
        plan.OUTPUT.mkdir()
        for arm in ('control', 'treatment'):
            directory = plan.OUTPUT / arm; directory.mkdir()
            for name in ('data.bin', 'map.bin'): (directory / name).write_text(arm + name)
        (plan.OUTPUT / 'report.json').write_text('{}')
        plan_path = self.root / 'plan.json'; plan_path.write_text('{}')
        plan_hash = plan.sha(plan_path); report_hash = plan.sha(plan.OUTPUT / 'report.json')
        final = {'status': 'paired_bytes_verified', 'planSHA256': plan_hash,
                 'reportSHA256': report_hash, 'outputInventory': supervise.output_inventory()}
        (plan.MONITOR / 'final-result.json').write_text(json.dumps(final))
        result = {'reportSHA256': report_hash}; frozen = {'valid': True}
        with mock.patch.object(plan, 'PLAN', plan_path), \
                mock.patch.object(supervise.shutil, 'disk_usage', return_value=types.SimpleNamespace(free=40 * supervise.GIB)), \
                mock.patch.object(plan, 'verify_plan', return_value=frozen):
            supervise.verify_post_guard(frozen, plan_hash, result)
            (plan.OUTPUT / 'treatment/data.bin').write_text('changed after guardian')
            with self.assertRaisesRegex(ValueError, 'output changed after guardian'):
                supervise.verify_post_guard(frozen, plan_hash, result)
            (plan.OUTPUT / 'treatment/data.bin').write_text('treatmentdata.bin')
            with mock.patch.object(plan, 'verify_plan', return_value={'valid': False}):
                with self.assertRaisesRegex(ValueError, 'input changed after guardian'):
                    supervise.verify_post_guard(frozen, plan_hash, result)

    def guardian_fixture(self):
        pid = 9999; started = 10.0; marker_tick = 11.0
        env = dict(supervise.environment(), PUPPY_TURN_GUARD_PID=str(pid), PUPPY_TURN_GUARD_FD='4',
                   PUPPY_TURN_GUARD_OUTPUT=str(plan.MONITOR))
        launch = {'guardianPID': pid, 'parentPID': os.getpid(), 'coordinatorPID': 9998,
                  'wallSeconds': 7500, 'startedMonotonic': started, 'command': supervise.command('coordinator'),
                  'environment': env}
        rows = []
        for t, phase, passed in ((10.2, 'active', False), (11.2, 'active', True),
                                 (12.2, 'cleanup', True), (12.3, 'cleanup', True)):
            volumes = {key: 40 * supervise.GIB for key in ('workspace', 'home', 'output')}
            rows.append({'phase': phase, 'monotonicSeconds': t, 'baselinePassed': passed,
                         'freeBytes': 40 * supervise.GIB, 'volumes': volumes, 'gpuFreeBytes': 8 * supervise.GIB,
                         'gpuTotalBytes': 16 * supervise.GIB, 'gpuUsedBytes': 8 * supervise.GIB, 'gpuBusyPercent': 3})
        result = {'status': 'passed', 'reason': None, 'coordinatorExit': 0, 'descendantsTerminated': False,
                  'diskEmergency': False, 'samples': len(rows), 'observedDoneMonotonic': 12.1, 'endedMonotonic': 12.4}
        for name, value in (('guardian-launch.json', launch), ('guardian-result.json', result),
                            ('baseline-passed.json', {'status': 'passed', 'monotonicSeconds': marker_tick})):
            (plan.MONITOR / name).write_text(json.dumps(value))
        path = plan.MONITOR / 'guardian-telemetry.jsonl'
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        return pid, rows, path

    def test_guardian_rejects_early_floor_drop_and_telemetry_gap(self):
        pid, rows, path = self.guardian_fixture()
        self.assertEqual(supervise.verify_guardian(pid)['status'], 'passed')
        rows[0]['freeBytes'] = 37 * supervise.GIB; rows[0]['volumes']['output'] = 37 * supervise.GIB
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        with self.assertRaisesRegex(ValueError, 'resource sample'):
            supervise.verify_guardian(pid)
        rows[0]['freeBytes'] = 40 * supervise.GIB; rows[0]['volumes']['output'] = 40 * supervise.GIB
        rows[1]['monotonicSeconds'] = 15.0
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        with self.assertRaisesRegex(ValueError, 'sampling coverage'):
            supervise.verify_guardian(pid)


if __name__ == '__main__':
    unittest.main()
