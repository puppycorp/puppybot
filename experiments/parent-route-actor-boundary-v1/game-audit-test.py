#!/usr/bin/env python3
"""CPU tests for saved-game identity and collector split gates."""
import hashlib
import importlib.util
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('parent_game_audit', HERE / 'game-audit.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True))


def write_lines(path, values):
    path.write_text(''.join(json.dumps(value, sort_keys=True) + '\n' for value in values))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class GameAuditTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name); self.original = root / 'original'; self.collected = root / 'collected'
        for directory in (self.original, self.collected):
            (directory / 'scene').mkdir(parents=True)
            (directory / 'scene/case.json').write_bytes(b'case')
            (directory / 'scene/environment.bin').write_bytes(b'environment')
        self.initial = {'totalSteps': 495, 'findReturn': {'phase': 'search', 'deliveries': 0}}
        self.rows = [
            {'sequence': 3, 'step': 505, 'action': [0, 1], 'proprio': [0] * 7,
             'state': {'totalSteps': 505, 'pose': [0, 0, 0],
                       'findReturn': {'phase': 'return', 'consumedIndex': 0, 'deliveries': 0}}},
            {'sequence': 4, 'step': 515, 'action': [.6, 1], 'proprio': [0] * 7,
             'state': {'totalSteps': 515, 'pose': [.1, 0, 0],
                       'findReturn': {'phase': 'delivered', 'consumedIndex': 0, 'deliveries': 1}}},
        ]
        self.events = [{'event': 'start', 'step': 0, 'robot': [0, 0, 0]}, {'event': 'delivery', 'step': 2}]
        self.old_result = {'seed': 7820010, 'steps': 2, 'deliveries': 1, 'reaches': 1, 'game': 'fetch',
                           'controller': 'native neural policy', 'exploreTeacher': False,
                           'teacherDisagreements': 0, 'backForthSteps': 0}
        self.new_result = dict(self.old_result, controller='native neural policy with exploring fetch teacher labels',
                               exploreTeacher=True, teacherDisagreements=1, coverageMisses=0,
                               backForthMetric='pose20-final-inclusive-v2')
        for directory in (self.original, self.collected):
            write_json(directory / 'initial.json', self.initial)
            write_lines(directory / 'decisions.jsonl', self.rows)
            write_lines(directory / 'chase.jsonl', self.events)
        write_json(self.original / 'result.json', self.old_result)
        write_json(self.collected / 'result.json', self.new_result)
        self.row = {'selectionRun': str(self.original), 'seed': 7820010, 'role': 'fit', 'episode': 0,
                    'firstDeliveryStep': 2,
                    'sceneSHA256': {name: sha(self.original / 'scene' / name) for name in ('case.json', 'environment.bin')},
                    'selectionSHA256': {name: sha(self.original / name) for name in audit.ORIGINAL_FILES}}

    def tearDown(self):
        self.tmp.cleanup()

    def check(self):
        return audit.game(self.row, self.collected, 1, horizon=2)[0]

    def test_exact_game_parity_and_recording_metadata(self):
        result = self.check()
        self.assertEqual(result['firstDeliveryStep'], 2)
        self.assertEqual(result['boundedPrefixBackForthActions'], 0)

    def test_changed_original_or_scene_rejected(self):
        (self.original / 'scene/case.json').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'sealed original'):
            self.check()

    def test_changed_action_or_state_rejected(self):
        self.rows[0]['action'] = [.6, 1]
        write_lines(self.collected / 'decisions.jsonl', self.rows)
        with self.assertRaisesRegex(ValueError, 'decisions or states'):
            self.check()

    def test_changed_event_or_result_rejected(self):
        self.events[-1]['step'] = 1
        write_lines(self.collected / 'chase.jsonl', self.events)
        with self.assertRaisesRegex(ValueError, 'task events'):
            self.check()

    def test_unexpected_result_field_is_not_normalized(self):
        self.new_result['unregisteredIntervention'] = True
        write_json(self.collected / 'result.json', self.new_result)
        with self.assertRaisesRegex(ValueError, 'unexpected game result difference'):
            self.check()

    def test_wrong_teacher_disagreement_and_metric_rejected(self):
        self.new_result['teacherDisagreements'] = 0
        write_json(self.collected / 'result.json', self.new_result)
        with self.assertRaisesRegex(ValueError, 'teacher-label declaration'):
            self.check()
        self.new_result['teacherDisagreements'] = 1
        self.new_result['backForthSteps'] = 1
        write_json(self.collected / 'result.json', self.new_result)
        with self.assertRaisesRegex(ValueError, 'back-and-forth'):
            self.check()

    def test_label_count_and_mask(self):
        path = Path(self.tmp.name) / 'data.bin'; horizon = 2
        images = bytes(horizon * audit.IMAGE)
        first = struct.pack('<7f2f2f', *([0] * 7), .6, 1, 0, 1)
        second = struct.pack('<7f2f2f', *([0] * 7), .6, 1, 0, 1)
        path.write_bytes(bytes(32) + images + first + second)
        self.assertEqual(audit.labels(path, 0, self.rows, horizon), 1)
        broken = bytearray(path.read_bytes()); broken[32 + horizon * audit.IMAGE + 43] = 0
        path.write_bytes(broken)
        with self.assertRaisesRegex(ValueError, 'mask'):
            audit.labels(path, 0, self.rows, horizon)

    def test_fixed_role_and_split_identity(self):
        rows = [dict(zip(('shard', 'episode', 'role', 'seed', 'layout', 'variant', 'firstDeliveryStep'), values),
                     selectionSHA256={name: 'a' * 64 for name in audit.ORIGINAL_FILES}) for values in audit.EXPECTED]
        plan = {'schema': 'puppybot.parent-route-collector-plan.v1', 'status': 'cpu_plan_only', 'rows': rows}
        self.assertEqual(audit.fixed_rows(plan), rows)
        rows[1]['role'] = 'fit'
        with self.assertRaisesRegex(ValueError, 'identity'):
            audit.fixed_rows(plan)

    def test_superseded_v1_plan_is_rejected(self):
        plan = Path(self.tmp.name) / 'plan.json'; plan.write_text('{}')
        with mock.patch.object(audit, 'digest', return_value='54acceb5e71859e1b6eb010dca66528733a317b8cbb100e5318cf95ec368604d'):
            with self.assertRaisesRegex(ValueError, 'plan hash'):
                audit.audit(plan, Path(self.tmp.name) / 'missing-output', None)

    def test_scene_link_must_resolve_to_registered_parent(self):
        parent = Path(self.tmp.name) / 'layout'; scene = parent / '10'; scene.mkdir(parents=True)
        (scene / 'case.json').write_bytes(b'case')
        (parent / 'environment.bin').write_bytes(b'env'); (parent / 'layout.json').write_bytes(b'layout')
        for name in ('environment.bin', 'layout.json'):
            (scene / name).symlink_to(parent / name)
        row = {'scene': str(scene), 'sceneSHA256': {name: sha(scene / name)
               for name in ('case.json', 'environment.bin', 'layout.json')}}
        audit.verify_scene(row)
        other = Path(self.tmp.name) / 'other'; other.write_bytes(b'env')
        (scene / 'environment.bin').unlink(); (scene / 'environment.bin').symlink_to(other)
        with self.assertRaisesRegex(ValueError, 'link'):
            audit.verify_scene(row)


if __name__ == '__main__':
    unittest.main()
