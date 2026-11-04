#!/usr/bin/env python3
"""Reproduce the offline fitted-corner connectivity results."""
import json
import subprocess
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


class SavedConnectivityTest(unittest.TestCase):
    def test_saved_views_and_negative_controls(self):
        process = subprocess.run(['python3', '-B', '-I', str(HERE / 'audit.py')], cwd=ROOT,
                                 capture_output=True, text=True, timeout=120, check=True)
        result = json.loads(process.stdout)
        barrier = result['barrier']; self.assertEqual(len(barrier), 45)
        self.assertEqual(sum(row['found'] for row in barrier), 5)
        self.assertEqual(sum(row['support']['accept'] for row in barrier), 5)
        self.assertTrue(all(row['found'] and row['support']['accept'] for row in result['knownPositiveViews']))
        negative = {row['name']: row for row in result['synthetic']}
        self.assertFalse(negative['blank']['found'])
        self.assertTrue(negative['patches']['found'])
        self.assertFalse(negative['patches']['support']['accept'])
        self.assertTrue(negative['connected']['found'])
        self.assertTrue(negative['connected']['support']['accept'])


if __name__ == '__main__':
    unittest.main()
