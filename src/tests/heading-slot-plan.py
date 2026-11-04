#!/usr/bin/env python3
"""CPU checks for fixed historical L5 slot authorization."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
p = ROOT / 'datasets/visual-control/chase-v1/levels/heading-slot-plan.py'
s = importlib.util.spec_from_file_location('slots', p); slots = importlib.util.module_from_spec(s); s.loader.exec_module(slots)


class SlotPlanTest(unittest.TestCase):
    def test_current_fixed_plan(self):
        report = slots.fixed_plan()
        self.assertEqual((report['fitOffset'], report['validationOffset'], report['unaffectedGames']), (808, 1016, 896))
        self.assertEqual(len(report['replacedSlots']), 128)

    def test_rejects_wrong_order_split_and_driver(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for i, original in enumerate(slots.fixed_shards()):
                path = Path(tmp) / str(i); path.mkdir(); (path / 'report.json').write_bytes((original / 'report.json').read_bytes()); paths.append(path)
            slots.derive(paths, paths[-4:])
            with self.assertRaises(ValueError): slots.derive(paths, list(reversed(paths[-4:])))
            r = json.loads((paths[-1] / 'report.json').read_text()); r['studentDriven'] = False
            (paths[-1] / 'report.json').write_text(json.dumps(r))
            with self.assertRaises(ValueError): slots.derive(paths, paths[-4:])


if __name__ == '__main__': unittest.main()
