#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location('final_loop_audit', Path(__file__).with_name('audit.py'))
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def rows(speeds, poses=None):
    if poses is None: poses = [[0., 0., 0.] for _ in speeds]
    return [{'action': [0., speed], 'state': {'pose': pose}} for speed, pose in zip(speeds, poses)]


class WindowTests(unittest.TestCase):
    def test_only_complete_window_is_the_final_one(self):
        data = rows([1., -1.] * 10)
        self.assertEqual(audit.marks(data, [0., 0., 0.], False), set())
        self.assertEqual(audit.marks(data, [0., 0., 0.], True), set(range(20)))

    def test_final_window_overlap_is_a_union(self):
        data = rows([1., -1.] * 11)
        old = audit.marks(data, [0., 0., 0.], False)
        full = audit.marks(data, [0., 0., 0.], True)
        self.assertEqual(old, set(range(21)))
        self.assertEqual(full - old, {21})

    def test_motion_and_insufficient_actions_do_not_count(self):
        self.assertFalse(audit.marks(rows([1., -1.] * 9), [0., 0., 0.], True))
        data = rows([1., -1.] * 10, [[float(i), 0., 0.] for i in range(20)])
        self.assertFalse(audit.marks(data, [0., 0., 0.], True))

    def test_invalid_input_is_rejected(self):
        data = rows([1., -1.] * 10); data[-1]['state']['pose'][0] = float('nan')
        with self.assertRaises(ValueError): audit.marks(data, [0., 0., 0.], True)


if __name__ == '__main__': unittest.main()
