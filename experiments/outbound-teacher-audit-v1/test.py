#!/usr/bin/env python3
import importlib.util
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('outbound_audit', HERE / 'audit.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def row(speed, x=0, consumed=-1):
    return {'action': [0, speed], 'state': {'pose': [x, 0, 0],
                                           'findReturn': {'consumedIndex': consumed}}}


class OutboundAuditTests(unittest.TestCase):
    def test_first_virtual_consumption_uses_one_based_action(self):
        self.assertEqual(audit.first_consumption([row(1), row(1, consumed=0)]), 2)
        self.assertIsNone(audit.first_consumption([row(1), row(1)]))

    def test_stationary_reversals_are_flagged_but_travel_is_not(self):
        alternating = [row(1 if i % 2 else -1) for i in range(30)]
        self.assertEqual(audit.reversal_marks(alternating, [0, 0, 0]), set(range(29)))
        travelling = [row(1 if i % 2 else -1, x=i) for i in range(30)]
        self.assertEqual(audit.reversal_marks(travelling, [0, 0, 0]), set())

    def test_mismatched_scene_or_start_is_rejected(self):
        matched = {'scene': ('case', 'environment'), 'start': {'robot': [0, 0, 0]}}
        audit.validate_match([matched, dict(matched)], 1)
        with self.assertRaisesRegex(ValueError, 'unmatched'):
            audit.validate_match([matched, {'scene': ('case', 'different'), 'start': matched['start']}], 1)
        with self.assertRaisesRegex(ValueError, 'unmatched'):
            audit.validate_match([matched, {'scene': matched['scene'], 'start': {'robot': [1, 0, 0]}}], 1)


if __name__ == '__main__':
    unittest.main()
