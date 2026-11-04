#!/usr/bin/env python3
"""CPU-only virtual-fetch and long search diagnostics."""
import copy
import importlib.util
import math
import struct
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('metrics', ROOT / 'datasets/visual-control/chase-v1/levels/heading-selection-metrics.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def fixture(mobile=False):
    rows = []
    for i in range(300):
        angle = 2 * math.pi * i / 50
        pose = [math.cos(angle), math.sin(angle), 0] if mobile else [0, 0, 0]
        rows.append({'step': 10 * (i + 1), 'state': {'pose': pose[:],
                     'localization': {'mode': 'wheel-drift', 'pose': pose[:]},
                     'findReturn': {'phase': 'search', 'consumedIndex': -1, 'deliveries': 0}}})
    return {'seed': 7800000, 'steps': 300, 'reaches': 0, 'deliveries': 0}, rows, [
        {'event': 'start', 'step': 0, 'robot': [0, 0, 0], 'brick': [2, 0]}]


def environment():
    data = bytearray(384); data[:8] = b'PBENV001'; struct.pack_into('<q', data, 8, 1)
    data[256:270] = b'Wall.partition'; struct.pack_into('<d', data, 304, 1.0)
    return bytes(data)


class MetricsTest(unittest.TestCase):
    def test_summarize_real_saved_game_without_teacher_claim(self):
        result, rows, events = fixture(True)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); directory = root / '0/7800000'; directory.mkdir(parents=True)
            (directory / 'result.json').write_text(json.dumps(result))
            (directory / 'chase.jsonl').write_text(''.join(json.dumps(event) + '\n' for event in events))
            report = m.summarize(root, {7800000: (result, rows, events[0], ('a', 'b'))}, 3)
            self.assertEqual(report['games'][0]['seed'], 7800000)
            self.assertGreater(report['odometryLoopActions'], 0)
            self.assertEqual(report['completedGames'], 0)
            self.assertIsNone(report['doorwayCases'])
            self.assertNotIn('teacher', report)

    def test_mobile_loop_and_stationary_negative(self):
        result, rows, events = fixture(True)
        mobile = m.game(result, rows, events)
        self.assertGreater(mobile['odometryLoopActions'], 0)
        self.assertEqual(mobile['odometryLoopActions'], mobile['overlapActions'])
        self.assertGreater(mobile['firstSearchTruth']['pathM'], 30)
        self.assertLess(mobile['firstSearchTruth']['netDisplacementM'], .2)
        result, rows, events = fixture(False)
        self.assertEqual(m.game(result, rows, events)['odometryLoopActions'], 0)

    def test_search_phase_and_odometry_truth_disagreement(self):
        result, rows, events = fixture(True)
        for row in rows:
            row['state']['pose'] = [0, 0, 0]
        metrics = m.game(result, rows, events)
        self.assertGreater(metrics['odometryLoopActions'], 0)
        self.assertEqual(metrics['truthLoopActions'], 0)
        for row in rows:
            row['state']['findReturn'] = {'phase': 'return', 'consumedIndex': 0, 'deliveries': 0}
        result['reaches'] = 1
        metrics = m.game(result, rows, events)
        self.assertEqual(metrics['searchActions'], 0)
        self.assertIsNone(metrics['firstSearchTruth'])
        self.assertIsNone(metrics['odometryLoopShareOfSearch'])
        self.assertEqual(metrics['firstVirtualConsumptionAction'], 1)

    def test_doorway_counts_delivered_and_unfinished_cases(self):
        result, rows, events = fixture()
        result.update(reaches=1, deliveries=1)
        for row in rows[4:20]: row['state']['findReturn'] = {'phase': 'return', 'consumedIndex': 0, 'deliveries': 0}
        rows[19]['state']['findReturn'] = {'phase': 'delivered', 'consumedIndex': 0, 'deliveries': 1}
        for row in rows[20:]: row['state']['findReturn']['deliveries'] = 1
        events.append({'event': 'delivery', 'step': 20, 'robot': [0, 0, 0], 'brick': [2, 0]})
        metrics = m.game(result, rows, events, environment())
        self.assertEqual((metrics['doorwayCases'], metrics['doorwayDelivered']), (2, 1))
        self.assertEqual(metrics['doorwayCensoredAtHorizon'], 1)
        self.assertEqual(metrics['doorwayZeroTimePlacements'], 0)
        self.assertEqual(metrics['firstVirtualConsumptionAction'], 5)
        self.assertTrue(metrics['completedDelivery'])
        events[-1]['step'] = 300
        for row in rows[19:]: row['state']['findReturn']['deliveries'] = 0
        rows[19]['state']['findReturn']['phase'] = 'return'
        rows[-1]['state']['findReturn'] = {'phase': 'delivered', 'consumedIndex': 0, 'deliveries': 1}
        self.assertEqual(m.game(result, rows, events, environment())['doorwayZeroTimePlacements'], 1)

    def test_reject_bad_data_instead_of_reporting_a_goal_pass(self):
        result, rows, events = fixture()
        bad = copy.deepcopy(rows); bad[10]['state']['localization']['pose'][0] = float('nan')
        with self.assertRaises(ValueError): m.game(result, bad, events)
        bad = copy.deepcopy(rows); bad[10]['state']['findReturn']['consumedIndex'] = True
        with self.assertRaises(ValueError): m.game(result, bad, events)
        bad = dict(result, reaches=1)
        with self.assertRaisesRegex(ValueError, 'consumption'): m.game(bad, rows, events)
        with self.assertRaisesRegex(ValueError, 'environment'): m.game(result, rows, events, b'bad')
        bad_events = events + [{'event': 'mystery', 'step': 10}]
        with self.assertRaisesRegex(ValueError, 'event sequence'): m.game(result, rows, bad_events)
        result2 = dict(result, reaches=1, deliveries=1)
        bad_events = events + [{'event': 'delivery', 'step': 10}]
        with self.assertRaisesRegex(ValueError, 'timing'): m.game(result2, rows, bad_events)


if __name__ == '__main__': unittest.main()
