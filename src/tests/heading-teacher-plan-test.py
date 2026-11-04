#!/usr/bin/env python3
"""CPU-only assertions for the non-executing teacher plan draft."""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('teacher_plan', ROOT / 'datasets/visual-control/chase-v1/levels/heading-teacher-plan-v1.py')
plan = importlib.util.module_from_spec(spec); spec.loader.exec_module(plan)


class TeacherPlanTest(unittest.TestCase):
    def test_all_task_commands_match_saved_student_plan(self):
        draft = plan.draft(); student = plan.plan_tool.selection_design()
        self.assertEqual(draft['status'], 'draft_only')
        self.assertEqual(draft['expectedDataBytesPerPart'], 50908832)
        self.assertEqual(draft['expectedDataBytesAllParts'], 1221811968)
        self.assertEqual(len(draft['tasks']), 6)
        for task, expected in zip(draft['tasks'], student):
            self.assertEqual(task['rows'], expected['rows'])
            self.assertEqual(task['environment'], plan.runner.environment(expected))
            argv = task['argv']
            self.assertEqual(argv[:2], ['/usr/bin/bash', str(plan.runner.EVALUATE)])
            self.assertEqual(argv[3:6], ['teacher', 'teacher', '--fetch'])
            self.assertEqual(argv[6:-3], expected['levelArgs'])
            self.assertEqual(argv[-3:], ['--camera-pitch', '82', '--explore-teacher'])
            self.assertEqual(len(task['expectedOutput']['parts']), 4)
            self.assertTrue(all(part['data'].endswith('/data.bin') for part in task['expectedOutput']['parts']))
            self.assertTrue(all(part['games'] == [f'expert-{i}' for i in range(8)]
                                for part in task['expectedOutput']['parts']))

    def test_separate_destination_and_limitations(self):
        draft = plan.draft()
        self.assertNotEqual(plan.TEACHER_ROOT, plan.plan_tool.SELECTION_ROOT)
        self.assertIn('wall geometry', draft['limits'])
        self.assertIn('teacher-rate goal', draft['limits'])
        self.assertIn('no teacher runner', plan.__doc__)


if __name__ == '__main__': unittest.main()
