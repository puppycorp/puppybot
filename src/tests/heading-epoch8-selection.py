#!/usr/bin/env python3
"""CPU-only tests for the heading fixed-epoch packaging and selection plan."""
import importlib.util
import json
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
path = ROOT / 'datasets/visual-control/chase-v1/levels/heading-epoch8-selection.py'
spec = importlib.util.spec_from_file_location('heading_selection', path)
selection = importlib.util.module_from_spec(spec); spec.loader.exec_module(selection)


class SelectionPlanTest(unittest.TestCase):
    def test_missing_monitored_full_training_blocks_before_input_audit(self):
        with mock.patch.object(selection.training_receipt, 'verify', side_effect=ValueError('no full training receipt')), \
             mock.patch.object(selection.training.collection_receipt, 'verify') as collection:
            with self.assertRaisesRegex(ValueError, 'no full training receipt'):
                selection.verify_training()
            collection.assert_not_called()

    def test_fixed_paired_tasks_and_training_scene_layouts(self):
        tasks = selection.selection_design()
        self.assertEqual([task['name'] for task in tasks], ['standard', 'L1', 'L2', 'L3', 'L4', 'L5'])
        for task in tasks:
            self.assertEqual((task['horizon'], task['gamesPerArm']), (300, 32))
            self.assertEqual([r['seed'] for r in task['rows']], list(range(7800000, 7800032)))
            for row in task['rows']:
                expected = 13 + 2 * (row['index'] % 3) if task['twoRoom'] else 12 + row['index'] % 6
                self.assertEqual((row['layout'], row['variant']), (expected, row['index'] % 16))
        self.assertEqual([t['twoRoom'] for t in tasks], [False, False, False, False, True, True])
        self.assertEqual(tasks[0]['levelArgs'], [])
        self.assertEqual(tasks[2]['levelArgs'], ['--level', '2'])

    def test_clean_training_status_is_strict(self):
        with tempfile.TemporaryDirectory() as tmp:
            status = Path(tmp) / 'status.json'
            good = {'clientExit': 0, 'signal': None, 'timedOut': False,
                    'remainingWorkersTerminated': False, 'processGroup': 123}
            status.write_text(json.dumps(good)); selection.clean_status(status)
            for key, value in [('clientExit', True), ('signal', 15), ('timedOut', True),
                               ('remainingWorkersTerminated', True), ('processGroup', 0)]:
                bad = dict(good); bad[key] = value; status.write_text(json.dumps(bad))
                with self.subTest(key=key), self.assertRaises(ValueError): selection.clean_status(status)

    def test_package_uses_common_lock_and_rechecks_training(self):
        calls = []
        with mock.patch.object(selection.sys, 'argv', ['heading-epoch8-selection.py', 'package']), \
             mock.patch.object(selection.base, 'acquire_lock', side_effect=lambda path: calls.append(path) or nullcontext()), \
             mock.patch.object(selection, 'verify_training', return_value={'trainingReportSHA256': 'x'}) as verify, \
             mock.patch.object(selection.package, 'create') as create, \
             mock.patch.object(selection.package, 'verify') as verify_package:
            selection.main()
        self.assertEqual(calls, [selection.P / '.l4-matched.lock'])
        create.assert_called_once_with(selection.MODELS / 'control-s0', selection.MODELS / 'treatment-s0', selection.PACKAGE)
        verify_package.assert_called_once_with(selection.MODELS / 'control-s0', selection.MODELS / 'treatment-s0', selection.PACKAGE)
        self.assertEqual(verify.call_count, 2)

    def test_existing_plan_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / 'plan.json'; plan.write_text('original')
            with mock.patch.object(selection, 'PLAN', plan), \
                 mock.patch.object(selection.sys, 'argv', ['heading-epoch8-selection.py', 'plan']), \
                 mock.patch.object(selection.base, 'acquire_lock', return_value=nullcontext()), \
                 mock.patch.object(selection, 'verify_training', return_value={}):
                with self.assertRaisesRegex(ValueError, 'already exists'): selection.main()
            self.assertEqual(plan.read_text(), 'original')

    def test_plan_is_refused_after_selection_output_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); played = root / 'played'; played.mkdir()
            with mock.patch.object(selection, 'PLAN', root / 'new-plan.json'), \
                 mock.patch.object(selection, 'SELECTION_ROOT', played), \
                 mock.patch.object(selection.sys, 'argv', ['heading-epoch8-selection.py', 'plan']), \
                 mock.patch.object(selection.base, 'acquire_lock', return_value=nullcontext()), \
                 mock.patch.object(selection, 'verify_training', return_value={}):
                with self.assertRaisesRegex(ValueError, 'after play'): selection.main()
            self.assertFalse((root / 'new-plan.json').exists())

    def test_reserved_scene_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); package = root / 'package'
            for arm in ('control', 'treatment'): (package / arm / 'kernels').mkdir(parents=True)
            scene = root / 'scene'; scene.mkdir()
            layout = {'layoutId': 13, 'fit': True, 'startRoom': 0, 'reservedHeldOut': True}
            (scene / 'layout.json').write_text(json.dumps(layout))
            tasks = [{'rows': [{'scene': str(scene), 'layout': 13}]}]
            with mock.patch.object(selection, 'PACKAGE', package):
                with self.assertRaisesRegex(ValueError, 'authorized training layout'):
                    selection.plan_inputs(tasks)


if __name__ == '__main__': unittest.main()
