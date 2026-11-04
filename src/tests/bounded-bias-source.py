#!/usr/bin/env python3
"""CPU source-transformation guards for the bounded bias prototype."""
import importlib.util
import unittest
from pathlib import Path

root = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('bounded', root / 'datasets/visual-control/chase-v1/levels/bounded-bias-source.py')
bounded = importlib.util.module_from_spec(spec); spec.loader.exec_module(bounded)


class SourceTest(unittest.TestCase):
    def test_expected_source_transforms_once(self):
        before = (root / 'flex/control/chase.flex').read_text()
        after = bounded.transform(before)
        self.assertEqual(after.count('global vx_bias_eligible=0;'), 1)
        self.assertIn('age<vw_straight_after+30', after)
        self.assertIn('if bias && best!=unmodified', after)
        self.assertIn('straightEligibleSteps', after)
        self.assertIn('straightChangedSteps', after)
        with self.assertRaises(ValueError): bounded.transform(after)

    def test_missing_or_duplicate_anchor_rejected(self):
        source = (root / 'flex/control/chase.flex').read_text()
        with self.assertRaises(ValueError): bounded.transform(source.replace(bounded.PICK, ''))
        with self.assertRaises(ValueError): bounded.transform(source + bounded.PICK)


if __name__ == '__main__': unittest.main()
