#!/usr/bin/env python3
"""Disposable CPU build and diagnostic I/O checks; no rendered scene."""
import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def replace_function(path, name, body):
    text = path.read_text(); start = text.index('fn ' + name + '(')
    end = text.index('\nfn ', start + 1)
    path.write_text(text[:start] + body + '\n' + text[end:])


builder = load('survey_build', HERE / 'build.py')
transform = builder.transform


class TestDiagnostic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='puppy-dock-survey-')
        root = Path(cls.tmp.name); cls.output = root / 'build'
        cls.report = builder.build(cls.output)
        main = cls.output / 'source/sim/main.flex'
        text = main.read_text()
        if text.count('fn main(argc, argv) {') != 1: raise ValueError('unexpected main')
        main.write_text(text.replace('fn main(argc, argv) {', 'fn sd_original_main(argc, argv) {', 1) + '\n' + (HERE / 'test-probe.flex').read_text())
        cls.probe = root / 'probe'
        result = subprocess.run([str(builder.COMPILER), str(main), '-o', str(cls.probe)], cwd=ROOT, capture_output=True, text=True, timeout=120)
        if result.returncode: raise RuntimeError(result.stdout + result.stderr)
        nav = cls.output / 'source/sim/navigation.flex'
        replace_function(nav, 'ps_nav_heading_free', 'fn ps_nav_heading_free() { return sd_heading; }')
        replace_function(nav, 'ps_nav_cell', 'fn ps_nav_cell(x, y) { return sd_cell; }')
        replace_function(nav, 'ps_nav_clear', 'fn ps_nav_clear(x, y, heading) { return sd_clear; }')
        replace_function(nav, 'ps_nav_index', 'fn ps_nav_index(x, y, heading) { return -1; }')
        text = main.read_text(); old = 'fn main(argc, argv) {'
        if text.count(old) != 1 or text.count('global ps_robot = 0;') != 1: raise ValueError('unexpected probe source')
        text = text.replace(old, 'fn sd_io_main(argc, argv) {', 1)
        text = text.replace('global ps_robot = 0;', 'global sd_heading = 0; global sd_cell = 0; global sd_clear = 0;\nglobal ps_robot = 0;', 1)
        main.write_text(text + '\n' + (HERE / 'route-probe.flex').read_text())
        cls.route_probe = root / 'route-probe'
        result = subprocess.run([str(builder.COMPILER), str(main), '-o', str(cls.route_probe)], cwd=ROOT, capture_output=True, text=True, timeout=120)
        if result.returncode: raise RuntimeError(result.stdout + result.stderr)

    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def invoke(self, mode, path):
        result = subprocess.run([str(self.probe), mode, str(path)], cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_disabled_mode_writes_nothing(self):
        path = Path(self.tmp.name) / 'off'; path.mkdir()
        self.invoke('off', path); self.assertEqual(list(path.iterdir()), [])

    def test_raw_survey_metadata_and_candidate(self):
        path = Path(self.tmp.name) / 'on'; path.mkdir()
        observed = json.loads(self.invoke('on', path))['dockVision']['surveyDiagnostic']
        self.assertEqual(observed, {'count': 1, 'planCount': 1, 'writeErrors': 0})
        self.assertEqual((path / 'survey-7.rgb').stat().st_size, 640 * 480 * 3)
        metadata = json.loads((path / 'survey-7.sensor.camera.json').read_text())
        self.assertEqual((metadata['frameId'], metadata['width'], metadata['height']), (70, 640, 480))
        candidate = json.loads((path / 'search-2-candidate-4.json').read_text())
        self.assertEqual((candidate['step'], candidate['search'], candidate['index'], candidate['planned'], candidate['reason'], candidate['expanded']), (70, 2, 4, False, 3, 17))
        self.assertEqual(candidate['goal'], [0, 0, 0])

    def test_write_failures_reported_without_crash(self):
        self.invoke('bad-path', Path(self.tmp.name) / 'missing' / 'nested')

    def test_planner_entry_reason_categories(self):
        result = subprocess.run([str(self.route_probe)], cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_transform_refuses_reapplication_and_source_drift(self):
        source = builder.ARCHIVE / 'source/sim'; names = ('main.flex', 'dock-vision.flex', 'dock-search.flex', 'navigation.flex')
        inputs = [(source / name).read_text() for name in names]
        result = transform.transform(*inputs)
        with self.assertRaises(ValueError): transform.transform(*result)
        with self.assertRaises(ValueError): transform.transform(inputs[0], inputs[1], inputs[2].replace('if ps_nav_plan(load64(ps_dock_search_goal)', 'if changed(load64(ps_dock_search_goal)'), inputs[3])

    def test_existing_build_path_refused(self):
        with self.assertRaises(ValueError): builder.build(self.output)


if __name__ == '__main__': unittest.main()
