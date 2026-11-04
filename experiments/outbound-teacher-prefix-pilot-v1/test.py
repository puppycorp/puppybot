#!/usr/bin/env python3
import importlib.util
import hashlib
import contextlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('outbound_screen', HERE / 'screen.py')
screen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(screen)
plan = screen.plan


def records():
    values = []
    for row in plan.design()['rows']:
        values.append({key: row[key] for key in ('index', 'seed', 'layout', 'fitting')} | {
            'sceneMatched': True, 'initialMatched': True, 'completeHorizon': True,
            'labelsVerified': True, 'studentFirstConsumptionAction': 200,
            'teacherFirstConsumptionAction': 200, 'teacherOutboundBackForthActions': 0})
    for index in (0, 1, 3, 9):
        values[index]['teacherFirstConsumptionAction'] = 100
    return values


class PilotScreenTest(unittest.TestCase):
    def test_design_and_commands_are_paired_and_disjoint(self):
        data = plan.design(); rows = data['rows']
        self.assertEqual(len(rows), 12)
        self.assertEqual(sum(row['fitting'] for row in rows), 9)
        self.assertEqual({row['layout'] for row in rows if not row['fitting']}, {13, 15, 17})
        student = plan.command('student', '/tmp/student')
        teacher = plan.command('teacher', '/tmp/teacher')
        self.assertEqual(student[student.index('--scene-catalog') + 1], teacher[teacher.index('--scene-catalog') + 1])
        self.assertEqual(student[student.index('--seed') + 1], teacher[teacher.index('--seed') + 1])
        self.assertIn('--policy', student); self.assertNotIn('--policy', teacher)
        reserved = {plan.heldout.BASE_SEED + level * 100 + i for level in range(1, 6) for i in range(32)}
        selected = set(range(7800000, 7800032)) | set(range(plan.selection.SEED, plan.selection.SEED + plan.selection.GAMES))
        plan.check_seed_boundaries(rows, reserved, selected, plan.validation.SEEDS)
        with self.assertRaises(ValueError):
            plan.check_seed_boundaries(rows, reserved | {rows[0]['seed']}, selected, plan.validation.SEEDS)
        with self.assertRaises(ValueError):
            plan.check_seed_boundaries(rows, reserved, selected | {rows[0]['seed']}, plan.validation.SEEDS)
        with self.assertRaises(ValueError):
            plan.check_seed_boundaries(rows, reserved, selected, set(plan.validation.SEEDS) | {rows[0]['seed']})

    def test_pass_never_authorizes_training(self):
        result = screen.evaluate(records())
        self.assertEqual(result['status'], 'screen_passed')
        self.assertEqual((result['fittingHelpful'], result['fittingHelpfulLayouts'], result['validationHelpful']), (3, 2, 1))
        self.assertIs(result['trainingAuthorized'], False)

    def test_misses_censoring_and_nonhelpful_cases_are_not_successes(self):
        values = records()
        for row in values:
            row['studentFirstConsumptionAction'] = None
            row['teacherFirstConsumptionAction'] = None
        self.assertEqual(screen.evaluate(values)['status'], 'screen_failed')
        # A student miss is only useful when the teacher succeeds within 200,
        # leaving at least 100 observed horizon actions of separation.
        values = records(); values[0]['studentFirstConsumptionAction'] = None
        self.assertTrue(screen.evaluate(values)['games'][0]['teacherHelpful'])
        values[0]['teacherFirstConsumptionAction'] = 201
        self.assertFalse(screen.evaluate(values)['games'][0]['teacherHelpful'])

    def test_teacher_loops_or_worsening_fail_gate(self):
        values = records(); values[0]['teacherOutboundBackForthActions'] = 1
        self.assertEqual(screen.evaluate(values)['status'], 'screen_failed')
        values = records()
        for index in (4, 5, 6, 7):
            values[index]['teacherFirstConsumptionAction'] = None
        self.assertEqual(screen.evaluate(values)['status'], 'screen_failed')

    def test_missing_or_contradictory_evidence_is_censored(self):
        values = records(); del values[0]['teacherFirstConsumptionAction']
        with self.assertRaises(ValueError): screen.evaluate(values)
        values = records(); values[0]['labelsVerified'] = False
        with self.assertRaises(ValueError): screen.evaluate(values)
        values = records(); values[0]['completeHorizon'] = False
        with self.assertRaises(ValueError): screen.evaluate(values)
        values = records(); values[0]['seed'] += 1
        with self.assertRaises(ValueError): screen.evaluate(values)
        values = records(); values[0]['teacherFirstConsumptionAction'] = True
        with self.assertRaises(ValueError): screen.evaluate(values)
        values = records(); values[0]['teacherOutboundBackForthActions'] = 100
        with self.assertRaises(ValueError): screen.evaluate(values)
        with self.assertRaises(ValueError): screen.evaluate(records()[:-1])

    def test_existing_two_game_pilot_is_reconstructed_without_training(self):
        # This is a saved-data compatibility check only, not the new 12-game
        # pilot or evidence that the earlier teacher route was useful.
        base = plan.P / 'l5-teacher-rollin-pilot-v1'
        catalog = plan.P / 'heading-rollin-pilot-catalogs/control-L5/catalogs/shard-0'
        model = plan.P / 'search-dagger-heading/models/heading-epoch8-pair/treatment'
        if not (base / 'student/report.json').exists() or not (base / 'teacher/report.json').exists():
            self.skipTest('archived two-game pilot is not available')
        spec = importlib.util.spec_from_file_location('outbound_saved_audit', HERE / 'audit.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        subject = module.plan
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        inputs = {'modelFiles': {str(model / 'weights.bin'): digest(model / 'weights.bin')},
                  'scenes': [{'files': {name: digest(catalog / str(index) / name)
                                       for name in ('case.json', 'environment.bin')}} for index in range(2)]}
        design = lambda: {'rows': [{'index': index, 'seed': 6700000 + index} for index in range(2)]}
        with (mock.patch.object(subject, 'GAMES', 2), mock.patch.object(subject, 'FITTING', 1),
              mock.patch.object(subject, 'MODEL', model), mock.patch.object(subject, 'CATALOG', catalog),
              mock.patch.object(subject, 'design', design)):
            student, slabels = module.audit_arm(base / 'student', 'student', inputs)
            teacher, tlabels = module.audit_arm(base / 'teacher', 'teacher', inputs)
        self.assertEqual([game['first'] for game in student], [241, 255])
        self.assertEqual([game['first'] for game in teacher], [259, None])
        self.assertEqual(slabels['teacherStudentDisagreements'], 328)
        self.assertEqual((slabels['checkedRows'], tlabels['checkedRows']), (600, 600))

    def test_catalog_layout_tampering_and_symlinks_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog = Path(tmp) / 'catalog'; catalog.mkdir(); scenes = []
            for index in range(plan.GAMES):
                target = catalog / str(index); target.mkdir(); files = {}
                for name in ('case.json', 'environment.bin', 'layout.json'):
                    path = target / name; path.write_bytes(f'{index}:{name}'.encode())
                    files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
                scenes.append({'index': index, 'files': files})
            with mock.patch.object(plan, 'CATALOG', catalog):
                plan.verify_catalog({'scenes': scenes})
                layout = catalog / '0/layout.json'; layout.write_bytes(b'changed')
                with self.assertRaises(ValueError): plan.verify_catalog({'scenes': scenes})
                layout.unlink(); layout.symlink_to(catalog / '1/layout.json')
                with self.assertRaises(ValueError): plan.verify_catalog({'scenes': scenes})

    def test_frozen_invocations_and_clean_supervisors_are_required(self):
        spec = importlib.util.spec_from_file_location('outbound_saved_audit_receipt', HERE / 'audit.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        subject = module.plan
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); catalog = root / 'catalog'; catalog.mkdir(); scenes = []
            for index in range(subject.GAMES):
                target = catalog / str(index); target.mkdir(); files = {}
                for name in ('case.json', 'environment.bin', 'layout.json'):
                    path = target / name; path.write_bytes(f'{index}:{name}'.encode())
                    files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
                scenes.append({'index': index, 'files': files})
            inputs = {'scenes': scenes}
            (root / 'catalog.json').write_text(json.dumps({'status': 'catalog_inputs_only', 'inputs': inputs}))
            with (mock.patch.object(subject, 'P', root), mock.patch.object(subject, 'OUTPUT', root),
                  mock.patch.object(subject, 'CATALOG', catalog), mock.patch.object(subject, 'preflight', return_value=inputs),
                  mock.patch.object(subject.register.base, 'acquire_lock', return_value=contextlib.nullcontext()),
                  mock.patch.object(subject.shutil, 'disk_usage') as disk):
                disk.return_value.free = 40 * 1024**3
                frozen = subject.freeze(); self.assertEqual(frozen['status'], 'frozen_before_play')
                for arm in subject.design()['arms']:
                    directory = root / f'monitor-{arm}'; directory.mkdir()
                    invocation = {'argv': subject.command(arm, root / arm), 'environment': subject.environment(), 'wallSeconds': 3600}
                    (directory / 'invocation.json').write_text(json.dumps(invocation))
                    status = {'clientExit': 0, 'timedOut': False, 'signal': None, 'remainingWorkersTerminated': False, 'processGroup': 123}
                    (directory / 'supervisor-result.json').write_text(json.dumps(status))
                self.assertEqual(module.verify_collection_evidence(root), inputs)
                path = root / 'monitor-teacher/supervisor-result.json'
                status['timedOut'] = True; path.write_text(json.dumps(status))
                with self.assertRaises(ValueError): module.verify_collection_evidence(root)
                status['timedOut'] = False; status.pop('signal'); path.write_text(json.dumps(status))
                with self.assertRaises(ValueError): module.verify_collection_evidence(root)

    def test_action_clock_rejects_wrong_duration_and_bad_state_timing(self):
        spec = importlib.util.spec_from_file_location('outbound_saved_audit_clock', HERE / 'audit.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        initial = {'totalSteps': 5, 'timeMs': 100}
        rows = [{'step': 15, 'state': {'totalSteps': 15, 'timeMs': 300}},
                {'step': 25, 'state': {'totalSteps': 25, 'timeMs': 500}}]
        module.validate_clock(initial, rows, 60.0)
        with self.assertRaises(ValueError): module.validate_clock(initial, rows, 59.8)
        rows[1]['state']['timeMs'] += 1
        with self.assertRaises(ValueError): module.validate_clock(initial, rows, 60.0)
        rows[1]['state']['timeMs'] -= 1; rows[1]['state']['totalSteps'] += 1
        with self.assertRaises(ValueError): module.validate_clock(initial, rows, 60.0)


if __name__ == '__main__':
    unittest.main()
