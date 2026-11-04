#!/usr/bin/env python3
"""CPU-only source, dispatch and recorded-pose kinematics checks."""
import importlib.util
import json
import math
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ARCHIVE = ROOT / 'build/flex/sim/levels-v2/pitch82/dock-survey-diagnostic-build-v1'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def replace_function(path, name, body):
    text = path.read_text(); start = text.index('fn ' + name + '(')
    end = text.index('\nfn ', start + 1)
    path.write_text(text[:start] + body + '\n' + text[end:])


builder = load('survey_source_builder', ROOT / 'experiments/dock-survey-diagnostic-v1/build.py')
transform = load('high_survey_transform', HERE / 'transform.py')


class HighSurveyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='puppy-high-survey-')
        cls.root = Path(cls.tmp.name); cls.output = cls.root / 'build'
        builder.build(cls.output)
        source = cls.output / 'source/sim'; case = source / 'case.flex'; main = source / 'main.flex'
        original_case, original_main = case.read_text(), main.read_text()
        candidate_case, candidate_main = transform.transform(original_case, original_main)
        case.write_text(candidate_case); main.write_text(candidate_main)
        cls.candidate = cls.root / 'simulator'
        cls.compile(main, cls.candidate)
        cls.kinematic = cls.root / 'kinematic'
        main.write_text(candidate_main.replace('fn main(argc, argv) {', 'fn hs_original_main(argc, argv) {', 1)
                        + '\n' + (HERE / 'kinematic-probe.flex').read_text())
        cls.compile(main, cls.kinematic)
        pickup = source / 'pickup.flex'; app = cls.output / 'source/runtime/app.flex'
        replace_function(pickup, 'ps_arm_solve', '''fn ps_arm_solve(point, height, pitch) {
            let radius = f64_hypot(load64(point), load64(point + 8));
            if !test_solve_calls { test_height0 = height; test_pitch0 = pitch; test_radius0 = radius; }
            else { test_height1 = height; test_pitch1 = pitch; test_radius1 = radius; }
            test_solve_calls = test_solve_calls + 1;
            let i = 0; while i < 4 { store64(ps_pickup_targets + i * 8, 100 + i * 100); i = i + 1; }
            if height == 380 && pitch == 80 { return test_high_ok; } return 1;
        }''')
        replace_function(pickup, 'ps_arm_move_ticks', 'fn ps_arm_move_ticks() { return test_move_ticks; }')
        replace_function(pickup, 'ps_arm_move_timeout', 'fn ps_arm_move_timeout() { return 1234; }')
        replace_function(app, 'pr_apply', 'fn pr_apply(app, command, values, now) { test_apply_calls = test_apply_calls + 1; return test_apply_error; }')
        replace_function(case, 'ps_case_fail', 'fn ps_case_fail(reason) { test_failure = 1; ps_case_stage = 13; return 0; }')
        globals_ = ('global test_solve_calls = 0; global test_apply_calls = 0; global test_high_ok = 1;\n'
                    'global test_height0 = 0; global test_height1 = 0; global test_pitch0 = 0; global test_pitch1 = 0;\n'
                    'global test_radius0 = 0; global test_radius1 = 0; global test_move_ticks = 0;\n'
                    'global test_apply_error = 0; global test_failure = 0;\n')
        mock_main = candidate_main.replace('global ps_robot = 0;', globals_ + 'global ps_robot = 0;', 1)
        main.write_text(mock_main.replace('fn main(argc, argv) {', 'fn hs_original_main(argc, argv) {', 1)
                        + '\n' + (HERE / 'test-probe.flex').read_text())
        cls.dispatch = cls.root / 'dispatch'; cls.compile(main, cls.dispatch)

    @classmethod
    def compile(cls, source, output):
        result = subprocess.run([str(builder.COMPILER), str(source), '-o', str(output)], cwd=ROOT,
                                capture_output=True, text=True, timeout=120)
        if result.returncode: raise RuntimeError(result.stdout + result.stderr)

    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def test_dispatch_and_fallbacks(self):
        result = subprocess.run([str(self.dispatch)], cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_invalid_opt_in_rejected_before_start(self):
        env = dict(os.environ, PUPPYBOT_DOCK_HIGH_SURVEY='not-a-boolean')
        result = subprocess.run([str(self.candidate)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 2)
        self.assertIn('Invalid high survey option', result.stderr)

    def test_reachable_recorded_pose_and_estimated_projection(self):
        result = subprocess.run([str(self.kinematic)], cwd=ROOT, check=True, capture_output=True, text=True, timeout=15)
        old, high = json.loads(result.stdout)
        centre = (-1.2766186403198314, -0.4392589458269684); yaw = -1.5431883309147871
        def project(camera, dx, dy):
            point = (centre[0] + dx * math.cos(yaw) - dy * math.sin(yaw),
                     centre[1] + dx * math.sin(yaw) + dy * math.cos(yaw), 0.0985)
            delta = [point[i] - camera[i] for i in range(3)]
            dot = lambda offset: sum(delta[i] * camera[offset + i] for i in range(3))
            depth = dot(3)
            self.assertGreater(depth, 0.0)
            return 320 + 415.69224 * dot(6) / depth, 240 + 415.69224 * dot(9) / depth
        self.assertGreater(project(old['camera'], 0, 0)[1], 480)
        corners = [project(high['camera'], dx, dy) for dx in (-.114, .114) for dy in (-.104, .104)]
        self.assertTrue(all(0 <= x < 640 and 0 <= y < 480 for x, y in corners), corners)
        self.assertLess(max(abs(x-y) for x, y in zip(high['ticks'], [1477, 531, 3032, 2911])), 2048)

    def test_transform_rejects_source_drift(self):
        case = (ARCHIVE / 'source/sim/case.flex').read_text()
        main = (ARCHIVE / 'source/sim/main.flex').read_text()
        with self.assertRaises(ValueError): transform.transform(case.replace('let pitch = 60;', 'let pitch = 61;').replace('global ps_case_survey_index = 0;', ''), main)
        candidate = transform.transform(case, main)
        with self.assertRaises(ValueError): transform.transform(*candidate)


if __name__ == '__main__': unittest.main()
