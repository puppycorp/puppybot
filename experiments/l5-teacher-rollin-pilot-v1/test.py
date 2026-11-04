#!/usr/bin/env python3
"""CPU-only fixtures for matched training-pilot preparation and auditing."""
import copy
import importlib.util
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('rollin_pilot_fixture', HERE / 'pilot.py')
p = importlib.util.module_from_spec(spec); spec.loader.exec_module(p)


def arm_data(first=(100, 150)):
    return {'labels': {'checkedRows': 600}, 'games': [
        {'seed': seed, 'start': {'step': 0, 'event': 'start', 'robot': [0., 1., .42], 'brick': [2., 3.]},
         'startLineSHA256': f'start-{seed}', 'initialStateSHA256': f'initial-{seed}', 'metrics': {'firstVirtualConsumptionAction': action}}
        for seed, action in zip(p.SEEDS, first)]}


class PilotTests(unittest.TestCase):
    def test_real_input_inventory_including_runtime_symlink_chain(self):
        original = p.sha
        def light_sha(path):
            path = Path(path)
            return original(path) if p.CATALOG in path.parents else 'mocked-non-catalog-file'
        with mock.patch.object(p.base.package, 'verify'), mock.patch.object(p, 'sha', side_effect=light_sha):
            pins = p.pin_inputs()
        runtime = p.ROOT / 'build/flex/rocm-runtime/libamdhip64.so'
        self.assertTrue(runtime.is_symlink())
        self.assertTrue(pins[str(runtime)].startswith('symlink:'))
        self.assertEqual(pins[str(runtime.resolve())], 'sha256:mocked-non-catalog-file')

    def test_runtime_symlink_changes_and_cycles_are_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'one').write_bytes(b'one'); (root / 'two').write_bytes(b'two')
            link = root / 'runtime'; link.symlink_to('one'); before = p.symlink_chain(link)
            link.unlink(); link.symlink_to('two')
            self.assertNotEqual(before, p.symlink_chain(link))
            link.unlink(); link.symlink_to('runtime')
            with self.assertRaisesRegex(ValueError, 'cycle'): p.symlink_chain(link)

    def test_initial_placement_and_first_sequence(self):
        initial = {'pose': [-.04, -.04, .42], 'step': 495}
        events = [{'event': 'start', 'step': 0, 'robot': [-.04, -.04, .42], 'brick': [2., 3.]}]
        rows = [{'sequence': i + 3, 'step': 505 + 10 * i,
                 'state': {'ball': [2., 3., .01], 'findReturn': {'consumedIndex': -1}}} for i in range(300)]
        p.validate_initial_and_sequences(initial, rows, events, (-.04, -.04, .42))
        shifted = copy.deepcopy(rows)
        for row in shifted: row['sequence'] += 1
        with self.assertRaisesRegex(ValueError, 'first action'): p.validate_initial_and_sequences(initial, shifted, events, (-.04, -.04, .42))
        changed = copy.deepcopy(rows); changed[0]['state']['ball'][0] = 4
        with self.assertRaisesRegex(ValueError, 'initial pose'): p.validate_initial_and_sequences(initial, changed, events, (-.04, -.04, .42))
        bad_initial = dict(initial, pose=[0., 1., .42]); bad_events = [dict(events[0], robot=[0., 1., .42])]
        with self.assertRaisesRegex(ValueError, 'initial pose'): p.validate_initial_and_sequences(bad_initial, rows, bad_events, (-.04, -.04, .42))

    def test_catalog_spawn_is_fixed_and_finite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'environment.bin'; data = bytearray(256); data[:8] = b'PBENV001'
            struct.pack_into('<3d', data, 96, -.04, -.04, .42); path.write_bytes(data)
            self.assertEqual(p.catalog_spawn(path), (-.04, -.04, .42))
            for yaw in (.35, float('nan')):
                struct.pack_into('<d', data, 112, yaw); path.write_bytes(data)
                with self.assertRaises(ValueError): p.catalog_spawn(path)

    def test_commands_only_differ_by_driver(self):
        student = p.command('student', '/tmp/student'); teacher = p.command('teacher', '/tmp/teacher')
        self.assertEqual(student[-2:], ['--policy', str(p.MODEL)])
        self.assertEqual(student[:-2][:student.index('--output') + 1], teacher[:teacher.index('--output') + 1])
        self.assertEqual(student[student.index('--output') + 2:-2], teacher[teacher.index('--output') + 2:])
        self.assertIn('--explore-teacher', teacher)
        self.assertNotIn('--policy', teacher)
        with self.assertRaises(ValueError): p.command('wrong', '/tmp/out')

    def test_matched_start_scene_result_and_censoring(self):
        student = arm_data((None, 120)); teacher = arm_data((80, None))
        result = p.compare(student, teacher)
        self.assertEqual([x['teacherEarlier'] for x in result['pairs']], [True, False])
        self.assertTrue(result['teacherEarlierInAnyGame'])
        both_missing = p.compare(arm_data((None, None)), arm_data((None, None)))
        self.assertIsNone(both_missing['teacherEarlierInAnyGame'])
        partly_unknown = p.compare(arm_data((None, 120)), arm_data((None, None)))
        self.assertIsNone(partly_unknown['teacherEarlierInAnyGame'])
        neither_earlier = p.compare(arm_data((100, 100)), arm_data((101, None)))
        self.assertIs(neither_earlier['teacherEarlierInAnyGame'], False)
        for mutation in ('seed', 'robot', 'brick', 'bytes', 'initial', 'missing', 'nonfinite'):
            altered = copy.deepcopy(teacher)
            if mutation == 'seed': altered['games'][0]['seed'] += 1
            elif mutation == 'robot': altered['games'][0]['start']['robot'][0] = 4
            elif mutation == 'brick': altered['games'][0]['start']['brick'][0] = 4
            elif mutation == 'bytes': altered['games'][0]['startLineSHA256'] = 'changed'
            elif mutation == 'initial': altered['games'][0]['initialStateSHA256'] = 'changed'
            elif mutation == 'missing': altered['games'].pop()
            else: altered['games'][0]['start']['robot'][0] = float('nan')
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): p.compare(student, altered)

    def test_teacher_labels_and_student_disagreement_counts(self):
        rows = [[{'action': [0., 1.]} for _ in range(300)] for _ in range(2)]
        results = [{'teacherDisagreements': 0}, {'teacherDisagreements': 0}]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (root / 'data.bin').open('wb') as stream:
                stream.truncate(32 + 2 * 300 * 21212)
                for ep in range(2):
                    stream.seek(32 + ep * 300 * 21212 + 300 * 21168)
                    for _ in range(300): stream.write(bytes(28) + struct.pack('<2f2f', 0., 1., 0., 1.))
            self.assertEqual(p.label_evidence(root, 'teacher', rows, results)['checkedRows'], 600)
            self.assertEqual(p.label_evidence(root, 'student', rows, results)['teacherStudentActionDisagreements'], 0)
            rows[0][0]['action'] = [1., 0.]
            with self.assertRaisesRegex(ValueError, 'teacher label differs'): p.label_evidence(root, 'teacher', rows, results)
            with self.assertRaisesRegex(ValueError, 'disagreement count'): p.label_evidence(root, 'student', rows, results)
            results[0]['teacherDisagreements'] = 1
            self.assertEqual(p.label_evidence(root, 'student', rows, results)['teacherStudentActionDisagreements'], 1)
            with (root / 'data.bin').open('r+b') as stream:
                stream.seek(32 + 300 * 21168 + 40); stream.write(struct.pack('<f', 0.))
            with self.assertRaisesRegex(ValueError, 'supervision weight'): p.label_evidence(root, 'student', rows, results)

    def test_no_overwrite_timeout_and_disabled_cli(self):
        result = subprocess.run([sys.executable, '-I', str(HERE / 'pilot.py')], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0); self.assertIn('Disabled', result.stderr)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); output = root / 'pilot'; output.mkdir()
            with mock.patch.object(p, 'P', root), mock.patch.object(p, 'OUTPUT', output), \
                 mock.patch.object(p.standalone, 'require_dedicated_process'), mock.patch.object(p.base, 'acquire_lock', return_value=nullcontext()):
                with self.assertRaisesRegex(ValueError, 'already exists'): p.run()
            output.rmdir(); status = {'signal': None, 'timedOut': True, 'clientExit': -15, 'remainingWorkersTerminated': False}
            with mock.patch.object(p, 'P', root), mock.patch.object(p, 'OUTPUT', output), \
                 mock.patch.object(p.standalone, 'require_dedicated_process'), mock.patch.object(p.base, 'acquire_lock', return_value=nullcontext()), \
                 mock.patch.object(p.base, 'require_capacity'), mock.patch.object(p, 'pin_inputs', return_value={'input': 'hash'}), \
                 mock.patch.object(p.base.hidden, 'supervise', return_value=status) as supervised:
                with self.assertRaisesRegex(RuntimeError, 'failed'): p.run()
            self.assertEqual(supervised.call_count, 1)
            self.assertEqual(json.loads((output / 'partial.json').read_text())['status'], 'censored')
            self.assertFalse((output / 'report.json').exists())


if __name__ == '__main__': unittest.main()
