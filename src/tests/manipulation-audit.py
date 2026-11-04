#!/usr/bin/env python3
import importlib.util
import math
import subprocess
import sys
import unittest
from pathlib import Path

path = Path(__file__).resolve().parents[1] / 'exploration' / 'manipulation_audit.py'
spec = importlib.util.spec_from_file_location('manipulation_audit', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Geometry:
    @staticmethod
    def rotation(quaternion):
        return [[1, 0, 0], [0, 1, 0], [0, 0, 1]]

    @staticmethod
    def contained(obj, definition, container):
        if not obj.get('independentlyContained'):
            raise ValueError('not independently contained')


CASE = {'id': 'case', 'objects': [{'id': 'brick', 'kind': 'block', 'position': [0.05, 0, 0.1]}],
        'container': {'position': [0, 0, 0], 'innerSize': [0.2, 0.2, 0.1], 'wallThickness': 0.01},
        'success': {'settleSteps': 3}}


def frame(step, held=False, inside=False, body=7, contact=3, contained=True):
    return {'step': step, 'timeMs': step * 20, 'episode': 0, 'physicsFault': 0, 'vehicle': {'queryFault': 0},
            'environment': {'sensorCameras': ['tcp']},
            'gripper': {'held': held, 'body': body, 'captureContactMask': contact, 'constraintActive': held},
            'case': {'id': 'case', 'container': {'position': [0, 0, 0], 'velocity': [0, 0, 0], 'angularVelocity': [0, 0, 0], 'quaternion': [0, 0, 0, 1]},
                     'objects': [{'id': 'brick', 'body': 7, 'kind': 'block', 'initialYawRad': 0,
                     'initialPosition': [0.05, 0, 0.1], 'position': [0.05, 0, 0.1], 'velocity': [0, 0, 0],
                     'quaternion': [0, 0, 0, 1],
                     'inside': inside, 'independentlyContained': contained}]}}


class ManipulationAudit(unittest.TestCase):
    def test_bilateral_capture_release_and_settled_containment(self):
        rows = [frame(0), frame(1, held=True), frame(2), frame(3, inside=True),
                frame(4, inside=True), frame(5, inside=True)]
        result = module.audit(rows, CASE, Geometry)
        self.assertTrue(result['traceMeetsManipulationCriteria'])
        self.assertEqual(result['status'], 'diagnostic_only')
        self.assertEqual(result['captures'], [{'object': 'brick', 'step': 1}])
        self.assertEqual(result['releases'], [{'object': 'brick', 'step': 2, 'overBox': True}])
        self.assertEqual(result['settledDeliveries'], {'brick': 5})

    def test_placement_without_grasp_never_scores(self):
        rows = [frame(0)] + [frame(i, inside=True) for i in range(1, 5)]
        self.assertFalse(module.audit(rows, CASE, Geometry)['traceMeetsManipulationCriteria'])

    def test_held_or_insufficiently_settled_not_delivered(self):
        rows = [frame(0), frame(1, held=True), frame(2), frame(3, inside=True), frame(4, inside=True)]
        self.assertFalse(module.audit(rows, CASE, Geometry)['traceMeetsManipulationCriteria'])
        rows = [frame(0), frame(1, held=True), frame(2, held=True)]
        self.assertFalse(module.audit(rows, CASE, Geometry)['traceMeetsManipulationCriteria'])

    def test_displacement_or_recapture_removes_terminal_credit(self):
        rows = [frame(0), frame(1, held=True), frame(2)] + [frame(i, inside=True) for i in range(3, 6)]
        rows += [frame(6)]
        self.assertFalse(module.audit(rows, CASE, Geometry)['traceMeetsManipulationCriteria'])
        rows[-1] = frame(6, held=True)
        self.assertFalse(module.audit(rows, CASE, Geometry)['traceMeetsManipulationCriteria'])

    def test_rejects_unverified_capture_and_invalid_trace(self):
        for rows in ([frame(0), frame(1, held=True, contact=1)],
                     [frame(0), frame(2)], [frame(0, inside=True)],
                     [frame(0), frame(1, held=True, body=8)],
                     [frame(0), frame(1, inside=True, contained=False)]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                module.audit(rows, CASE, Geometry)

    def test_rejects_wrong_case_episode_and_teleport(self):
        wrong_case = frame(1); wrong_case['case']['id'] = 'different'
        wrong_episode = frame(1); wrong_episode['episode'] = 2
        teleport = frame(2); teleport['case']['objects'][0]['position'] = [1, 0, 0.1]
        for rows in ([frame(0), wrong_case], [frame(0), wrong_episode], [frame(0), frame(1, held=True), teleport]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                module.audit(rows, CASE, Geometry)

    def test_rejects_truncated_start_and_wrong_initial_height(self):
        moved = frame(0); moved['case']['objects'][0]['position'][2] = 0.15
        turned = frame(0); turned['case']['container']['quaternion'] = [0, 0, math.sin(0.5), math.cos(0.5)]
        for rows in ([frame(1000)], [moved], [turned]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                module.audit(rows, CASE, Geometry)

    def test_optimized_python_fails_closed(self):
        snippet = ("import importlib.util; "
                   f"s=importlib.util.spec_from_file_location('audit',{str(path)!r}); "
                   "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.audit([],{},None)")
        result = subprocess.run([sys.executable, '-I', '-O', '-c', snippet], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('optimized Python disables the geometry checker', result.stderr)

    def test_release_outside_box_does_not_count(self):
        case = {**CASE, 'container': {**CASE['container'], 'position': [0, 1, 0]}}
        rows = [frame(0), frame(1, held=True), frame(2)] + [frame(i, inside=True) for i in range(3, 6)]
        for row in rows:
            row['case']['container']['position'] = [0, 1, 0]
        result = module.audit(rows, case, Geometry)
        self.assertFalse(result['traceMeetsManipulationCriteria'])
        self.assertFalse(result['releases'][0]['overBox'])

    def test_rotating_object_is_not_settled(self):
        rows = [frame(0), frame(1, held=True), frame(2)]
        for i in range(3, 7):
            row = frame(i, inside=True)
            angle = i * math.pi / 2
            row['case']['objects'][0]['quaternion'] = [0, 0, math.sin(angle / 2), math.cos(angle / 2)]
            rows.append(row)
        self.assertFalse(module.audit(rows, CASE, Geometry)['traceMeetsManipulationCriteria'])

    def test_rotating_box_is_not_settled(self):
        rows = [frame(0), frame(1, held=True), frame(2)]
        for i in range(3, 7):
            row = frame(i, inside=True)
            row['case']['container']['angularVelocity'] = [0, 0, 1]
            rows.append(row)
        self.assertFalse(module.audit(rows, CASE, Geometry)['traceMeetsManipulationCriteria'])

    def test_stale_release_cannot_credit_a_later_arrival(self):
        rows = [frame(0), frame(1, held=True), frame(2)]
        positions = [0.05 + 0.01 * i for i in range(1, 26)] + [0.30 - 0.01 * i for i in range(1, 26)]
        for step, x in enumerate(positions, 3):
            row = frame(step)
            row['case']['objects'][0]['position'][0] = x
            row['case']['objects'][0]['velocity'][0] = 0.5
            rows.append(row)
        rows.extend(frame(i, inside=True) for i in range(53, 56))
        self.assertFalse(module.audit(rows, CASE, Geometry)['traceMeetsManipulationCriteria'])

    def test_unsettled_release_expires(self):
        rows = [frame(0), frame(1, held=True), frame(2)] + [frame(i) for i in range(3, 504)]
        rows.extend(frame(i, inside=True) for i in range(504, 507))
        self.assertFalse(module.audit(rows, CASE, Geometry)['traceMeetsManipulationCriteria'])


if __name__ == '__main__':
    unittest.main()
