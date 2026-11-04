#!/usr/bin/env python3
"""CPU checks for non-authorizing selection from a recomputed pilot screen."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


spec = importlib.util.spec_from_file_location('pilot_selection', Path(__file__).with_name('pilot-selection.py'))
selection = importlib.util.module_from_spec(spec); spec.loader.exec_module(selection)


def passed():
    rows = selection.pilot.plan.design()['rows']; helpful = {0, 2, 3, 7, 9}
    games = [{'index': row['index'], 'seed': row['seed'], 'fitting': row['fitting'],
              'teacherHelpful': row['index'] in helpful, 'teacherWorse': False} for row in rows]
    return {'status': 'screen_passed', 'trainingAuthorized': False, 'games': games,
            'fittingHelpful': 4, 'fittingHelpfulLayouts': 3, 'validationHelpful': 1, 'teacherWorse': 0}


def saved_hashes(root):
    teacher = root / 'teacher'
    result = {str(teacher / 'data.bin'): 'a' * 64, str(teacher / 'report.json'): 'b' * 64}
    for index in (0, 2, 3, 7):
        for name in ('result.json', 'initial.json', 'chase.jsonl', 'decisions.jsonl'):
            result[str(teacher / ('expert-' + str(index)) / name)] = 'c' * 64
    return result


def selection_manifest():
    return {'path': '/tmp/selection-manifest', 'sha256': 'd' * 64,
            'design': selection.pilot.plan.selection.design()}


class PilotSelectionTest(unittest.TestCase):
    def test_selects_only_helpful_fitting_cases(self):
        rows = selection.pilot.plan.design()['rows']
        self.assertEqual(selection.identities(passed()),
                         [{'episode': row['index'], 'seed': row['seed']} for row in rows if row['index'] in (0, 2, 3, 7)])

    def test_rejects_failed_spoofed_or_unmatched_screen(self):
        changes = []
        data = passed(); data['status'] = 'screen_failed'; changes.append(data)
        data = passed(); data['trainingAuthorized'] = True; changes.append(data)
        data = passed(); data['games'][0]['seed'] += 1; changes.append(data)
        data = passed(); data['games'][9]['fitting'] = True; changes.append(data)
        data = passed(); data['games'][0]['teacherWorse'] = True; changes.append(data)
        data = passed(); data['fittingHelpful'] = 5; changes.append(data)
        data = passed(); data['games'].pop(); changes.append(data)
        for data in changes:
            with self.subTest(data=data), self.assertRaises(ValueError): selection.identities(data)

    def test_preview_reaudits_and_never_authorizes_training(self):
        root = Path('/tmp/pilot-selection-fixture'); teacher = root / 'teacher'
        files = saved_hashes(root)
        with mock.patch.object(selection.pilot.plan, 'OUTPUT', root), \
             mock.patch.object(selection, 'snapshot', side_effect=[files, files]), \
             mock.patch.object(selection, 'frozen_selection', return_value=selection_manifest()), \
             mock.patch.object(selection.pilot.plan, 'preflight', return_value={'identity': 1}), \
             mock.patch.object(selection.pilot, 'audit', return_value=passed()) as audited:
            result = selection.preview()
        audited.assert_called_once_with()
        self.assertIs(result['outerMonitorVerified'], False)
        self.assertIs(result['usableForTraining'], False)
        self.assertEqual([row['episode'] for row in result['selection'][str(teacher)]['episodes']], [2, 3, 7])
        self.assertEqual([row['episode'] for row in result['exactSceneOverlapExcluded']], [0])
        self.assertEqual((result['postFilterFittingGames'], result['postFilterFittingLayouts']), (3, 3))
        self.assertEqual(set(result['selection'][str(teacher)]['episodes'][0]['evidence']),
                         {'result.json', 'initial.json', 'chase.jsonl', 'decisions.jsonl'})
        self.assertNotIn(9, [row['episode'] for row in result['selection'][str(teacher)]['episodes']])

    def test_passing_original_gate_cannot_bypass_post_filter_sufficiency(self):
        root = Path('/tmp/pilot-selection-fixture'); files = saved_hashes(root)
        data = passed()
        for row in data['games']:
            row['teacherHelpful'] = row['index'] in (0, 3, 6, 9)
        data['fittingHelpful'] = 3
        with mock.patch.object(selection.pilot.plan, 'OUTPUT', root), \
             mock.patch.object(selection, 'snapshot', side_effect=[files, files]), \
             mock.patch.object(selection, 'frozen_selection', return_value=selection_manifest()), \
             mock.patch.object(selection.pilot.plan, 'preflight', return_value={'identity': 1}), \
             mock.patch.object(selection.pilot, 'audit', return_value=data):
            with self.assertRaisesRegex(ValueError, 'post-hoc exact-scene filter leaves insufficient'):
                selection.preview()

    def test_preview_rejects_changed_evidence_and_never_writes(self):
        root = Path('/tmp/pilot-selection-fixture'); teacher = root / 'teacher'
        files = saved_hashes(root)
        changed = copy.deepcopy(files); changed[str(teacher / 'data.bin')] = 'c' * 64
        with mock.patch.object(selection.pilot.plan, 'OUTPUT', root), \
             mock.patch.object(selection, 'snapshot', side_effect=[files, changed]), \
             mock.patch.object(selection, 'frozen_selection', return_value=selection_manifest()), \
             mock.patch.object(selection.pilot.plan, 'preflight', return_value={'identity': 1}), \
             mock.patch.object(selection.pilot, 'audit', return_value=passed()):
            with self.assertRaisesRegex(ValueError, 'changed during audit'): selection.preview()

    def test_preview_rejects_changed_preflight_inputs(self):
        root = Path('/tmp/pilot-selection-fixture'); teacher = root / 'teacher'
        files = saved_hashes(root)
        with mock.patch.object(selection.pilot.plan, 'OUTPUT', root), \
             mock.patch.object(selection, 'snapshot', side_effect=[files, files]), \
             mock.patch.object(selection, 'frozen_selection', return_value=selection_manifest()), \
             mock.patch.object(selection.pilot.plan, 'preflight', side_effect=[{'identity': 1}, {'identity': 2}]), \
             mock.patch.object(selection.pilot, 'audit', return_value=passed()):
            with self.assertRaisesRegex(ValueError, 'changed during audit'): selection.preview()

    def test_frozen_selection_manifest_requires_actual_design_and_stable_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'fresh-policy-selection-plan-v2.json'
            value = {'schema': 'puppybot.fresh-policy-selection-plan.v1', 'status': 'frozen_before_play',
                     'design': selection.pilot.plan.selection.design()}
            path.write_text(json.dumps(value))
            with mock.patch.object(selection.pilot.plan, 'P', Path(temp)):
                result = selection.frozen_selection()
                self.assertEqual(result['sha256'], selection.mask.sha(path))
                altered = copy.deepcopy(value); altered['design']['tasks'][0]['rows'][0]['layout'] = 999
                path.write_text(json.dumps(altered))
                with self.assertRaisesRegex(ValueError, 'selection design differs'): selection.frozen_selection()

    def test_preview_rejects_selection_manifest_change_during_audit(self):
        root = Path('/tmp/pilot-selection-fixture'); files = saved_hashes(root)
        first = selection_manifest(); changed = dict(first, sha256='e' * 64)
        with mock.patch.object(selection.pilot.plan, 'OUTPUT', root), \
             mock.patch.object(selection, 'snapshot', side_effect=[files, files]), \
             mock.patch.object(selection, 'frozen_selection', side_effect=[first, changed]), \
             mock.patch.object(selection.pilot.plan, 'preflight', return_value={'identity': 1}), \
             mock.patch.object(selection.pilot, 'audit', return_value=passed()):
            with self.assertRaisesRegex(ValueError, 'changed during audit'): selection.preview()

    def test_snapshot_binds_policy_kernels_catalog_and_optional_log_presence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'pilot'; root.mkdir()
            def write(relative, value=b'x'):
                path = root / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(value); return path
            write('catalog.json'); write('launch-plan.json')
            for name in ('receipt.json', 'weights.bin', 'policy', 'kernels/a'):
                write('student/policy/' + name)
            for row in selection.pilot.plan.design()['rows']:
                for name in ('case.json', 'environment.bin', 'layout.json'):
                    write('catalog/' + str(row['index']) + '/' + name)
            for arm in ('student', 'teacher'):
                for name in ('report.json', 'data.bin', 'map.bin'):
                    write(arm + '/' + name)
                for name in ('invocation.json', 'supervisor-result.json'):
                    write('monitor-' + arm + '/' + name)
                for row in selection.pilot.plan.design()['rows']:
                    for name in ('result.json', 'initial.json', 'chase.jsonl', 'decisions.jsonl',
                                 'scene/case.json', 'scene/environment.bin'):
                        write(arm + '/expert-' + str(row['index']) + '/' + name)
            with mock.patch.object(selection.pilot.plan, 'OUTPUT', root):
                first = selection.snapshot()
                log = write('teacher/expert-0/native.log')
                self.assertNotEqual(first, selection.snapshot())
                log.unlink(); self.assertEqual(first, selection.snapshot())
                weight = write('student/policy/weights.bin', b'changed')
                self.assertNotEqual(first, selection.snapshot())
                weight.write_bytes(b'x')
                kernel = write('student/policy/kernels/a', b'changed')
                self.assertNotEqual(first, selection.snapshot())
                kernel.write_bytes(b'x')
                catalog = write('catalog/0/layout.json', b'changed')
                self.assertNotEqual(first, selection.snapshot())
                catalog.write_bytes(b'x')
                self.assertEqual(first, selection.snapshot())


if __name__ == '__main__': unittest.main()
