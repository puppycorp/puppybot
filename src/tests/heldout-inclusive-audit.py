#!/usr/bin/env python3
"""Boundary and integration checks for inclusive held-out score verification."""
import importlib.util
import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


heldout = load('heldout_inclusive', ROOT / 'datasets/visual-control/chase-v1/levels/audit-heldout-inclusive.py')
fixtures = load('heldout_fixture', ROOT / 'flex/tests/heldout-audit.py')
qualify = load('qualification_inclusive', ROOT / 'datasets/visual-control/chase-v1/levels/qualify-selection-inclusive.py')


def rows(speeds):
    return [{'action': [0., x], 'state': {'pose': [0., 0., 0.]}} for x in speeds]


class InclusiveTests(unittest.TestCase):
    def test_final_only_window_and_legacy(self):
        data = rows([1., -1.] * 10)
        self.assertEqual(heldout.legacy.backforth_steps(data, [0., 0., 0.]), 0)
        self.assertEqual(heldout.backforth_steps(data, [0., 0., 0.]), 20)
        self.assertEqual(heldout.backforth_steps(data[:-1], [0., 0., 0.]), 0)

    def test_overlapping_windows_are_not_double_counted(self):
        data = rows([1., -1.] * 11)
        self.assertEqual(heldout.legacy.backforth_steps(data, [0., 0., 0.]), 21)
        self.assertEqual(heldout.backforth_steps(data, [0., 0., 0.]), 22)

    def test_nonfinite_final_pose_rejected(self):
        data = rows([0.] * 20); data[-1]['state']['pose'][0] = float('nan')
        with self.assertRaises(ValueError): heldout.backforth_steps(data, [0., 0., 0.])

    def test_real_game_reader_requires_version_and_inclusive_count(self):
        fixture = fixtures.HeldoutAuditTests(methodName='test_complete_games_accepted')
        fixture.setUp(); self.addCleanup(fixture.tearDown)
        for file in fixture.root.glob('*/[0-9]*/result.json'):
            result = json.loads(file.read_text()); result['backForthMetric'] = heldout.METRIC
            file.write_text(json.dumps(result))
        first = fixture.root / '0' / '1700000100'
        data = rows([0.] * 280 + [1., -1.] * 10)
        (first / 'decisions.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in data))
        path = first / 'result.json'; result = json.loads(path.read_text())
        result['backForthSteps'] = heldout.backforth_steps(data, [0., 0., 0.]); path.write_text(json.dumps(result))
        self.assertGreater(result['backForthSteps'], heldout.legacy.backforth_steps(data, [0., 0., 0.]))
        self.assertEqual(len(heldout.load_games(fixture.root, fixture.expected, fixture.model, 1,
                                                heldout.legacy.load_helpers())), 32)
        result['backForthMetric'] = 'legacy'; path.write_text(json.dumps(result))
        with self.assertRaises(ValueError):
            heldout.load_games(fixture.root, fixture.expected, fixture.model, 1, heldout.legacy.load_helpers())
        result['backForthMetric'] = heldout.METRIC
        result['backForthSteps'] = heldout.legacy.backforth_steps(data, [0., 0., 0.]); path.write_text(json.dumps(result))
        with self.assertRaises(ValueError):
            heldout.load_games(fixture.root, fixture.expected, fixture.model, 1, heldout.legacy.load_helpers())

    def test_teacher_metric_is_checked_too(self):
        data = rows([1., -1.] * 10)
        event = [{'robot': [0., 0., 0.]}]
        teacher = {5: ({'backForthMetric': heldout.METRIC, 'backForthSteps': 20}, data, event, Path('teacher'))}
        self.assertIs(heldout.validate_games(teacher), teacher)
        teacher[5][0]['backForthSteps'] = 0
        with self.assertRaises(ValueError): heldout.validate_games(teacher)

    def test_selection_requires_version_and_correct_count(self):
        data = rows([1., -1.] * 10)
        game = {5: ({'backForthMetric': heldout.METRIC, 'backForthSteps': 20}, data,
                    {'robot': [0., 0., 0.]}, Path('game'))}
        self.assertIs(qualify.validate_games(game), game)
        game[5][0].pop('backForthMetric')
        with self.assertRaises(ValueError): qualify.validate_games(game)
        game[5][0]['backForthMetric'] = heldout.METRIC
        game[5][0]['backForthSteps'] = 0
        with self.assertRaises(ValueError): qualify.validate_games(game)

    def test_main_requires_wrapper_hash_registered(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            path = ROOT / 'datasets/visual-control/chase-v1/levels/audit-heldout-inclusive.py'
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            inputs = output / 'inputs.sha256'
            inputs.write_text(f'{digest}  {path}\n')
            stream = io.StringIO()
            with mock.patch.object(heldout.sys, 'argv', ['audit', 'catalog', 'model', str(output)]), \
                    mock.patch.object(heldout.legacy, 'main', lambda: print('{"status":"fixture"}')), \
                    contextlib.redirect_stdout(stream):
                heldout.main()
            self.assertEqual(json.loads(stream.getvalue())['backForthMetric'], heldout.METRIC)
            inputs.write_text(f'{"0" * 64}  {path}\n')
            with mock.patch.object(heldout.sys, 'argv', ['audit', 'catalog', 'model', str(output)]):
                with self.assertRaises(ValueError): heldout.main()
            inputs.write_text('')
            with mock.patch.object(heldout.sys, 'argv', ['audit', 'catalog', 'model', str(output)]):
                with self.assertRaises(ValueError): heldout.main()


if __name__ == '__main__': unittest.main()
