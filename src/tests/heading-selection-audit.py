#!/usr/bin/env python3
"""CPU tests for all-six heading selection pair verification."""
import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
path = ROOT / 'datasets/visual-control/chase-v1/levels/heading-selection-audit.py'
spec = importlib.util.spec_from_file_location('heading_audit', path)
audit = importlib.util.module_from_spec(spec); spec.loader.exec_module(audit)


class HeadingAuditTest(unittest.TestCase):
    def test_standard_and_l2_use_strict_trace_checks(self):
        for level in (0, 2):
            task = {'name': 'standard' if level == 0 else 'L2', 'level': level}
            models = {'control': Path('/control-model'), 'treatment': Path('/treatment-model')}
            game = ({'levelPlacement': 'same'}, [], {'robot': [0, 0, 0]}, ('case', 'environment'))
            with mock.patch.object(audit.qualification, 'strict_games', return_value={7800000: game}) as strict, \
                 mock.patch.object(audit.selection, 'summary', return_value={'games': 32}), \
                 mock.patch.object(audit.metrics, 'summarize', return_value={'games': []}) as metrics:
                report = audit.audit_pair(task, Path('/selection'), models)
            self.assertEqual(report['level'], level)
            self.assertEqual(strict.call_count, 2)
            self.assertEqual(metrics.call_count, 2)
            self.assertEqual([c.args[2] for c in strict.call_args_list], [level, level])
            self.assertIn('no winner', report['scope'])

    def test_mismatched_start_rejected_for_standard_and_l2(self):
        models = {'control': Path('/a'), 'treatment': Path('/b')}
        left = ({'levelPlacement': 'same'}, [], {'robot': [0, 0, 0]}, ('case', 'environment'))
        right = ({'levelPlacement': 'same'}, [], {'robot': [1, 0, 0]}, ('case', 'environment'))
        for level in (0, 2):
            with mock.patch.object(audit.qualification, 'strict_games', side_effect=[{7800000: left}, {7800000: right}]):
                with self.assertRaisesRegex(ValueError, 'unmatched'):
                    audit.audit_pair({'name': str(level), 'level': level}, Path('/selection'), models)

    def test_incomplete_or_changed_plan_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'plan.json'; expected = {'status': 'selection_plan_only', 'tasks': [{'name': 'standard'}]}
            path.write_text(json.dumps(expected))
            with mock.patch.object(audit.plan_tool, 'PLAN', path), \
                 mock.patch.object(audit.plan_tool, 'verify_training', return_value={}), \
                 mock.patch.object(audit.plan_tool, 'make_plan', return_value=expected):
                _, task = audit.validate_plan(path, 'standard'); self.assertEqual(task['name'], 'standard')
                changed = copy.deepcopy(expected); changed['tasks'][0]['name'] = 'L2'; path.write_text(json.dumps(changed))
                with self.assertRaisesRegex(ValueError, 'plan differs'): audit.validate_plan(path, 'L2')

    def test_real_strict_games_accepts_standard_and_requires_l2_placement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); models = {'control': Path('/a'), 'treatment': Path('/b')}
            for level in (0, 2):
                task = {'name': 'standard' if level == 0 else 'L2', 'level': level}
                task_root = root / task['name']; games = {}
                for arm in ('control', 'treatment'):
                    games[arm] = {}
                    for i in range(32):
                        seed = 7800000 + i; game = task_root / arm / str(i // 8) / str(seed)
                        game.mkdir(parents=True)
                        result = {'seed': seed, 'game': 'fetch', 'controller': 'native neural policy',
                                  'exploreTeacher': False, 'carryCue': True, 'taskEventHint': False,
                                  'suppliedMap': False, 'maximumBrickDistanceM': .35, 'deliveries': 0,
                                  'backForthSteps': 0, 'farBricks': False, 'sweepTeacher': False}
                        if level == 2: result['levelPlacement'] = 'just off view'
                        (game / 'result.json').write_text(json.dumps(result))
                        games[arm][seed] = (result, [], {'robot': [0, 0, 0]}, ('case', 'environment'))
                def load_games(path, model, requested_level):
                    self.assertEqual(requested_level, level)
                    return games[path.name]
                with mock.patch.object(audit.selection, 'load', side_effect=load_games), \
                     mock.patch.object(audit.selection, 'summary', return_value={'games': 32}), \
                     mock.patch.object(audit.metrics, 'summarize', return_value={'games': []}), \
                     mock.patch.object(audit.selection, 'check_score'), \
                     mock.patch.object(audit.heldout_helpers, 'backforth_steps', return_value=0):
                    self.assertEqual(audit.audit_pair(task, task_root, models)['level'], level)
                    if level == 2:
                        target = task_root / 'control/0/7800000/result.json'
                        changed = json.loads(target.read_text()); changed.pop('levelPlacement')
                        target.write_text(json.dumps(changed))
                        with self.assertRaisesRegex(ValueError, 'placement'):
                            audit.audit_pair(task, task_root, models)


if __name__ == '__main__': unittest.main()
