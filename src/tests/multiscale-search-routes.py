#!/usr/bin/env python3
"""CPU-only controls for the exploratory closed-route diagnostic."""
import importlib.util
import math
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
path = ROOT / 'datasets/visual-control/chase-v1/levels/multiscale-search-routes.py'
spec = importlib.util.spec_from_file_location('multiscale_routes', path)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


class RouteTest(unittest.TestCase):
    def test_straight_and_partial_turn_do_not_close(self):
        straight = [[i * .04, 0, 0] for i in range(300)]
        turn = [[5 * math.sin(i * math.pi / 600), 5 * (1 - math.cos(i * math.pi / 600)), i * math.pi / 600]
                for i in range(300)]
        for route in (straight, turn):
            self.assertEqual(m.analyze(route, [True] * 300)['unionMarkedActions'], 0)

    def test_closed_circle_detected_but_phase_break_rejects_window(self):
        route = [[1.5 * math.cos(2 * math.pi * i / 200), 1.5 * math.sin(2 * math.pi * i / 200),
                  2 * math.pi * i / 200] for i in range(201)]
        self.assertGreater(m.analyze(route, [True] * len(route))['byWindow']['200']['matchingWindows'], 0)
        phases = [True] * len(route); phases[100] = False
        self.assertEqual(m.analyze(route, phases)['byWindow']['200']['matchingWindows'], 0)

    def test_invalid_pose_rejected(self):
        with self.assertRaises(ValueError): m.analyze([[float('nan'), 0, 0]], [True])

    def test_post_action_interval_endpoints(self):
        route = [[1.5 * math.cos(2 * math.pi * i / 100), 1.5 * math.sin(2 * math.pi * i / 100), 0]
                 for i in range(101)]
        result = m.analyze(route, [True] * len(route))['byWindow']['100']
        self.assertEqual(result['matchingWindows'], 1)
        self.assertEqual(result['markedActionRanges'], [[2, 101]])
        self.assertEqual((result['example']['firstPoseAction'], result['example']['lastPoseAction']), (1, 101))

    def test_motivating_saved_case_when_available(self):
        game = ROOT / 'build/flex/sim/levels-v2/pitch82/search-dagger-l4-matched/selection-epoch8-L5/treatment-s0/0/7800001'
        if not game.is_dir(): self.skipTest('saved local selection game unavailable')
        result = m.game(game)
        self.assertEqual(result['seed'], 7800001)
        # Fixed windows were chosen before this test: this route is missed.
        self.assertEqual(result['wheelOdometry']['unionMarkedActions'], 0)
        self.assertEqual(result['simulatorTruth']['unionMarkedActions'], 0)


if __name__ == '__main__': unittest.main()
