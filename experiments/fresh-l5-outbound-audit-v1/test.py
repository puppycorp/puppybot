#!/usr/bin/env python3
import importlib.util
import pathlib
import unittest


HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('audit', HERE / 'audit.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class FreshOutboundTest(unittest.TestCase):
    def test_time_and_missing_categories(self):
        self.assertEqual(audit.bucket(None, None), 'both_missed')
        self.assertEqual(audit.bucket(None, 299), 'teacher_only')
        self.assertEqual(audit.bucket(20, None), 'student_only')
        self.assertEqual(audit.bucket(50, 49), 'teacher_earlier')
        self.assertEqual(audit.bucket(49, 50), 'student_earlier')
        self.assertEqual(audit.bucket(50, 50), 'tie')

    def test_prefix_stops_at_first_action_or_pose_change(self):
        games = [{'arms': {'control': {'path': [(0, 0)] * 300}}} for _ in range(3)]
        games[2]['arms']['control']['path'][100] = (1, 0)
        self.assertEqual(audit.common_prefix(games, 'control'), 100)
        self.assertIsNone(audit.common_prefix(games[:1], 'control'))


if __name__ == '__main__': unittest.main()
