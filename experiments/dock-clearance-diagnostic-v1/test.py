#!/usr/bin/env python3
"""Compile and exercise the copied diagnostic with mocked map/IK inputs."""
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def replace_function(path, name, body):
    text = path.read_text()
    start = text.index('fn ' + name + '(')
    end = text.find('\nfn ', start + 1)
    if end < 0:
        end = len(text)
    path.write_text(text[:start] + body + '\n' + text[end:])


transform = load('clearance_transform', HERE / 'transform.py')
builder = load('clearance_original_builder', ROOT / 'experiments/dock-survey-elevation-trial-v1/build.py')


class ClearanceDiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='puppy-clearance-')
        cls.root = Path(cls.tmp.name)
        cls.output = cls.root / 'build'
        builder.build(cls.output)
        source = cls.output / 'source/sim'
        paths = [source / name for name in ('dock-vision.flex', 'dock-search.flex', 'navigation.flex')]
        for path, content in zip(paths, transform.transform(*(p.read_text() for p in paths))):
            path.write_text(content)
        main = source / 'main.flex'
        compiled = subprocess.run([str(builder.COMPILER), str(main), '-o', str(cls.root / 'simulator')],
                                  cwd=ROOT, capture_output=True, text=True, timeout=120)
        if compiled.returncode:
            raise RuntimeError('full transformed simulator failed: ' + compiled.stdout + compiled.stderr)
        replace_function(source / 'floor-memory.flex', 'ps_floor_clear',
                         'fn ps_floor_clear(x,y,heading) { dc_floor_calls = dc_floor_calls + 1; return dc_floor; }')
        replace_function(source / 'navigation.flex', 'ps_nav_observed_clear',
                         'fn ps_nav_observed_clear(x,y,heading) { dc_observed_calls = dc_observed_calls + 1; return dc_observed; }')
        replace_function(source / 'navigation.flex', 'ps_nav_box_gap',
                         'fn ps_nav_box_gap(x,y,heading) { dc_box_calls = dc_box_calls + 1; return f64_from_i64(dc_gap); }')
        replace_function(source / 'navigation.flex', 'ps_nav_cell',
                         'fn ps_nav_cell(x,y) { return 0; }')
        replace_function(source / 'navigation.flex', 'ps_nav_plan_release',
                         'fn ps_nav_plan_release(x,y,heading) { dc_route_calls = dc_route_calls + 1; return dc_route; }')
        replace_function(source / 'navigation.flex', 'ps_nav_end_pose',
                         'fn ps_nav_end_pose(out) { pb_zero(out, 24); return 1; }')
        replace_function(source / 'case.flex', 'ps_case_drop_clearance',
                         'fn ps_case_drop_clearance(height,x,y,heading) { dc_drop_calls = dc_drop_calls + 1; return dc_drop; }')
        replace_function(source / 'dock-search.flex', 'ps_dock_refine_allowed',
                         'fn ps_dock_refine_allowed(enabled,physical,fresh,stable) { return 0; }')
        text = main.read_text()
        old = 'fn main(argc, argv) {'
        if text.count(old) != 1 or text.count('global ps_robot = 0;') != 1:
            raise ValueError('unexpected main source')
        text = text.replace(old, 'fn dc_original_main(argc, argv) {', 1)
        globals_ = ('global dc_floor = 0; global dc_observed = 0; global dc_gap = 0; '
                    'global dc_drop = 0; global dc_route = 0; '
                    'global dc_floor_calls = 0; global dc_observed_calls = 0; global dc_box_calls = 0; '
                    'global dc_drop_calls = 0; global dc_route_calls = 0;\n')
        text = text.replace('global ps_robot = 0;', globals_ + 'global ps_robot = 0;', 1)
        main.write_text(text + '\n' + (HERE / 'probe.flex').read_text())
        cls.probe = cls.root / 'probe'
        compiled = subprocess.run([str(builder.COMPILER), str(main), '-o', str(cls.probe)],
                                  cwd=ROOT, capture_output=True, text=True, timeout=120)
        if compiled.returncode:
            raise RuntimeError('native probe failed: ' + compiled.stdout + compiled.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_real_dispatch_and_counter_accounting(self):
        target = self.root / 'diagnostics'
        target.mkdir()
        result = subprocess.run([str(self.probe), str(target)], cwd=ROOT, capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed['prefix'], 1)
        self.assertEqual(parsed['dockVision']['clearanceDiagnostic']['stageCandidates'], 0)
        self.assertIn('surveyDiagnostic', parsed['dockVision'])
        candidate = json.loads((target / 'search-1-candidate-2.json').read_text())
        self.assertEqual((candidate['step'], candidate['reason'], candidate['clearanceDetail']), (123, 3, 2))

    def test_refuses_reapplication_and_source_drift(self):
        source = builder.ARCHIVE / 'source/sim'
        names = ('dock-vision.flex', 'dock-search.flex', 'navigation.flex')
        # The elevation archive of the builder predates elevation itself but
        # has the same three diagnostic-bearing files.
        inputs = [(source / name).read_text() for name in names]
        result = transform.transform(*inputs)
        with self.assertRaises(ValueError):
            transform.transform(*result)
        with self.assertRaises(ValueError):
            transform.transform(inputs[0], inputs[1].replace('fn ps_dock_search_stage()', 'fn changed_stage()'), inputs[2])


if __name__ == '__main__':
    unittest.main()
