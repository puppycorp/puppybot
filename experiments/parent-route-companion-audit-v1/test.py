#!/usr/bin/env python3
"""Exercise the companion audit against the real native boundary fixture."""
import importlib.util
import struct
import unittest
from pathlib import Path
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit = load('companion_audit', HERE / 'audit.py')
fixture_module = load('parent_native_fixture', ROOT / 'experiments/parent-route-actor-boundary-v1/test.py')


class CompanionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_class = fixture_module.BoundaryTest
        cls.fixture_class.setUpClass()

    @classmethod
    def tearDownClass(cls):
        cls.fixture_class.tearDownClass()

    def setUp(self):
        self.fixture = self.fixture_class('test_native_records_align_with_data')
        self.fixture.setUp()
        self.horizon = patch.object(audit, 'HORIZON', 2)
        self.horizon.start()
        self.addCleanup(self.horizon.stop)
        self.addCleanup(self.fixture.tearDown)
        self.seed = 7820011
        for path in (self.fixture.actor, self.fixture.boundary):
            self.change(path, 16, struct.pack('<q', self.seed))
        self.rows = self.fixture.rows
        # A valid unfinished episode can have no delivery and no label disagreement.
        self.rows[1]['state']['findReturn']['deliveries'] = 0
        for index, label in enumerate((struct.pack('<2f', 0, 1), struct.pack('<2f', .6, 1))):
            self.change(self.fixture.data, 32 + 2 * (audit.IMAGE + audit.ROW) +
                        2 * audit.IMAGE + index * audit.ROW + 28, label)
            self.change(self.fixture.boundary, 40 + index * audit.MAP_RECORD + 24 + audit.MAP, label)
        self.result = {'seed': self.seed, 'steps': 2, 'deliveries': 0, 'game': 'fetch', 'level': 5,
                       'controller': 'native neural policy with exploring fetch teacher labels',
                       'exploreTeacher': True, 'carryCue': True,
                       'blackout': False, 'suppliedMap': False, 'taskEventHint': False,
                       'sweepTeacher': False, 'teacherDisagreements': 0,
                       'policyWeightsSHA256': '9c586f40ad6fc1a13a17f325cd3b33da5aca07e4790ee0922fd59049cd89f0d1'}

    @staticmethod
    def change(path, offset, value):
        data = bytearray(path.read_bytes())
        data[offset:offset + len(value)] = value
        path.write_bytes(data)

    def check(self, episode=1):
        f = self.fixture
        return audit.audit(f.data, f.maps, f.actor, f.boundary, self.seed, episode, self.rows, self.result)

    def test_unfinished_and_identical_labels_are_valid(self):
        result = self.check()
        self.assertEqual(result['role'], 'validation_companion_only')
        self.assertIsNone(result['firstDeliveryAction'])
        self.assertEqual(result['labelDifferences'], 0)

    def test_delivered_companion_does_not_need_different_labels(self):
        self.rows[1]['state']['findReturn']['phase'] = 'delivered'
        self.rows[1]['state']['findReturn']['deliveries'] = 1
        self.result['deliveries'] = 1
        result = self.check()
        self.assertEqual(result['firstDeliveryAction'], 2)
        self.assertEqual(result['prefixLabelDifferences'], 0)

    def test_wrong_seed_episode_split_and_result_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'seed or episode'):
            self.check(0)
        self.seed = 7820010
        with self.assertRaisesRegex(ValueError, 'seed or episode'):
            self.check()
        self.seed = 7820011
        self.result['seed'] = 7820026
        with self.assertRaisesRegex(ValueError, 'result identity'):
            self.check()
        self.result['seed'] = self.seed
        self.change(self.fixture.data, 16, struct.pack('<q', 2))
        with self.assertRaisesRegex(ValueError, 'split'):
            self.check()

    def test_image_map_label_and_actor_corruption_are_rejected(self):
        f = self.fixture
        originals = [(f.data, 32 + 2 * (audit.IMAGE + audit.ROW), b'\xff', 'RGB'),
                     (f.maps, 32 + 2 * audit.MAP, b'\xff', 'map'),
                     (f.boundary, 40 + 24 + audit.MAP, b'\xff', 'teacher label'),
                     (f.actor, 56 + 24, b'\xff', 'RGB')]
        for path, offset, value, reason in originals:
            before = path.read_bytes()
            self.change(path, offset, value)
            with self.assertRaisesRegex(ValueError, reason):
                self.check()
            path.write_bytes(before)

    def test_actions_cues_order_footer_and_delivery_are_checked(self):
        self.rows[1]['action'] = [0, 1]
        with self.assertRaisesRegex(ValueError, 'action'):
            self.check()
        self.rows[1]['action'] = [.6, 1]
        self.rows[0]['state']['findReturn']['consumedIndex'] = -1
        self.rows[0]['state']['findReturn']['phase'] = 'search'
        with self.assertRaisesRegex(ValueError, 'carry cue'):
            self.check()
        self.rows[0]['state']['findReturn']['consumedIndex'] = 0
        self.rows[0]['state']['findReturn']['phase'] = 'return'
        self.rows[0]['sequence'] = 4
        with self.assertRaisesRegex(ValueError, 'order'):
            self.check()
        self.rows[0]['sequence'] = 3
        self.rows[1]['state']['findReturn']['deliveries'] = 2
        with self.assertRaisesRegex(ValueError, 'delivery sequence'):
            self.check()
        self.rows[1]['state']['findReturn']['deliveries'] = 0
        self.result['teacherDisagreements'] = 1
        with self.assertRaisesRegex(ValueError, 'disagreement'):
            self.check()
        self.result['teacherDisagreements'] = 0
        self.fixture.actor.write_bytes(self.fixture.actor.read_bytes()[:-1])
        with self.assertRaises(ValueError):
            self.check()


if __name__ == '__main__':
    unittest.main()
