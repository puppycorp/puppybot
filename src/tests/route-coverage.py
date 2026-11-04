#!/usr/bin/env python3
"""CPU controls for offline grid route geometry."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

p = Path(__file__).resolve().parents[2] / 'datasets/visual-control/chase-v1/levels/route-coverage.py'
spec = importlib.util.spec_from_file_location('route', p)
route = importlib.util.module_from_spec(spec); spec.loader.exec_module(route)


class RouteCoverageTest(unittest.TestCase):
    def test_stationary(self):
        a = route.geometry([[0, 0, 0]] * 4)
        self.assertEqual((a['uniqueCells'], a['cellTransitions'], a['revisitedCellEntries']), (1, 0, 0))
        self.assertIsNone(a['revisitedEntryShare'])

    def test_reentry_excludes_dwell(self):
        a = route.geometry([[0, 0, 0], [.3, 0, 0], [.3, 0, 0], [0, 0, 0]])
        self.assertEqual((a['uniqueCells'], a['cellTransitions'], a['revisitedCellEntries']), (2, 2, 1))
        self.assertAlmostEqual(a['pathM'], .6)
        self.assertEqual(a['netDisplacementM'], 0)

    def test_invalid_pose_rejected(self):
        for pose in ([float('nan'), 0, 0], [0, float('inf'), 0], [0, 0], [True, 0, 0]):
            with self.subTest(pose=pose), self.assertRaises(ValueError): route.geometry([pose])

    def test_game_rejects_oracle_and_bad_trace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); scene = root / 'scene'; scene.mkdir()
            source = p.parents[4] / 'build/flex/sim/expanded-rooms-v1/scenes/15/1/environment.bin'
            (scene / 'environment.bin').write_bytes(source.read_bytes())
            result = {'seed': 1, 'level': 5, 'levelPlacement': 'other room', 'steps': 300,
                      'blackout': False, 'suppliedMap': False, 'taskEventHint': False,
                      'deliveries': 0, 'backForthSteps': 0}
            (root / 'result.json').write_text(json.dumps(result))
            (root / 'chase.jsonl').write_text(json.dumps({'event': 'start', 'robot': [0, 0, 0], 'brick': [2.5, 0]}) + '\n')
            rows = [{'step': i * 10, 'state': {'pose': [0, 0, 0], 'trainingOracle': {'enabled': False, 'queries': 0},
                    'findReturn': {'phase': 'search'}}} for i in range(300)]
            def save(): (root / 'decisions.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
            save(); self.assertIsNone(route.game(root)['firstEntryAction'])
            rows[20]['state']['trainingOracle']['queries'] = 1; save()
            with self.assertRaises(ValueError): route.game(root)
            rows[20]['state']['trainingOracle']['queries'] = 0; rows[1]['step'] = 9; save()
            with self.assertRaises(ValueError): route.game(root)


if __name__ == '__main__':
    unittest.main()
