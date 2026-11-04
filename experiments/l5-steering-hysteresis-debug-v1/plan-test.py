#!/usr/bin/env python3
"""CPU-only tests of the fixed reproduction plan and preflight."""
import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('debug_plan', HERE / 'plan.py')
plan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plan)


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.patch = patch.multiple(plan, ROOT=root, SCENES=root / 'scenes', MODEL=root / 'model',
                                    BUILD=root / 'build', OUTPUT=root / 'output')
        self.patch.start()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.patch.stop)
        for path in (plan.BUILD / 'control', plan.MODEL / 'policy', plan.MODEL / 'weights.bin',
                     root / 'build/flex/control/simulator', root / 'build/flex/sim/puppybot.bin'):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(path))
        files = {str(path): plan.sha(path) for path in
                 (plan.BUILD / 'control', plan.MODEL / 'policy', plan.MODEL / 'weights.bin',
                  root / 'build/flex/control/simulator', root / 'build/flex/sim/puppybot.bin')}
        self.scenes = []
        for row in plan.design()['conditions']:
            scene = Path(row['scene']); scene.mkdir(parents=True)
            for name in ('case.json', 'environment.bin', 'layout.json'):
                (scene / name).write_text(str(scene / name))
            self.scenes.append({**row, 'index': row['oldIndex'],
                                'files': {name: plan.sha(scene / name) for name in
                                          ('case.json', 'environment.bin', 'layout.json')}})
        self.kick = {'schema': 'puppybot.l5-steering-kick-plan.v1', 'status': 'frozen_before_play',
                     'scenes': self.scenes, 'files': files, 'runtime': {'hip': 'same'}}
        self.hys = {'schema': 'puppybot.l5-steering-hysteresis-plan.v1', 'status': 'frozen_before_play',
                    'files': files.copy(), 'runtime': {'hip': 'same'}}
        self.report = {'status': 'diagnostic_only', 'pairs': [
            {'seed': row['seed'], 'triggered': True, 'interventionMostlyBackForth': True}
            for row in plan.design()['conditions']]}

    def test_fixed_commands_use_single_binary_and_distinct_outputs(self):
        commands = [plan.command(row, arm) for row in plan.design()['conditions']
                    for arm in plan.design()['arms']]
        self.assertEqual(len(commands), 6)
        self.assertEqual({command[0] for command in commands}, {str(plan.BUILD / 'control')})
        self.assertEqual(len({command[command.index('--output') + 1] for command in commands}), 6)
        self.assertEqual([command.count('--steer-hysteresis') for command in commands], [0, 0, 1, 0, 0, 1])
        self.assertEqual(plan.preflight(self.kick, self.report, self.hys)['cases'], 2)

    def test_reject_changed_scene_and_changed_binary(self):
        scene = Path(plan.design()['conditions'][0]['scene'])
        (scene / 'case.json').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'scene changed'):
            plan.preflight(self.kick, self.report, self.hys)
        (scene / 'case.json').write_text(str(scene / 'case.json'))
        (plan.BUILD / 'control').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'current input differs'):
            plan.preflight(self.kick, self.report, self.hys)

    def test_reject_missing_prior_failure_or_changed_model_pin(self):
        report = copy.deepcopy(self.report)
        report['pairs'][0]['interventionMostlyBackForth'] = False
        with self.assertRaisesRegex(ValueError, 'prior case or failure differs'):
            plan.preflight(self.kick, report, self.hys)
        self.kick['files'][str(plan.MODEL / 'weights.bin')] = 'different'
        with self.assertRaisesRegex(ValueError, 'current input differs'):
            plan.preflight(self.kick, self.report, self.hys)

    def test_reject_arbitrary_case_or_arm(self):
        with self.assertRaises(ValueError):
            plan.command({**plan.design()['conditions'][0], 'seed': 42}, 'kick')
        with self.assertRaises(ValueError):
            plan.command(plan.design()['conditions'][0], 'other')


if __name__ == '__main__':
    unittest.main()
