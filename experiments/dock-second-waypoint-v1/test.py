#!/usr/bin/env python3
"""Compile a private simulator copy and test the bounded second waypoint."""
import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ARCHIVE = ROOT / 'build/flex/sim/levels-v2/pitch82/dock-short-waypoint-build-v1'
COMPILER = ROOT / 'build/flex/control/compiler'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


builder = load('waypoint_builder', ROOT / 'experiments/dock-short-waypoint-v1/build.py')
previous = load('floor_test', ROOT / 'experiments/dock-floor-refresh-v1/test.py')
transform = load('second_waypoint', HERE / 'transform.py')


def replace_function(text, name, body):
    start = text.index('fn ' + name + '('); opening = text.index('{', start)
    depth = 1; end = opening + 1
    while depth:
        if text[end] == '{': depth += 1
        if text[end] == '}': depth -= 1
        end += 1
    return text[:start] + body + text[end:]


class SecondWaypointTest(unittest.TestCase):
    def test_private_simulator_and_transitions(self):
        builder.verify(ARCHIVE)
        with tempfile.TemporaryDirectory(prefix='puppy-dock-second-waypoint-') as temp:
            root = Path(temp); source = root / 'source'; build = root / 'build'
            shutil.copytree(ARCHIVE / 'source', source); shutil.copytree(ARCHIVE / 'build', build)
            library = build / 'flex/sim/library'; adapter = library / 'lib/f64.flex'
            adapter.write_text(transform.once(adapter.read_text(),
                f'import "{ARCHIVE / "source/core/words.flex"}";', f'import "{source / "core/words.flex"}";'))
            (library.parent / 'dependencies.flex').write_text(
                f'import "{library / "libs/render.flex"}";\nimport "{library / "libs/physics/physics.flex"}";\n')
            sim = source / 'sim'; names = ('dock-search.flex', 'discovery.flex', 'case.flex', 'main.flex')
            paths = [sim / name for name in names]
            for path, data in zip(paths, transform.transform(*(path.read_text() for path in paths))): path.write_text(data)
            binary = root / 'simulator'
            compiled = subprocess.run([str(COMPILER), str(sim / 'main.flex'), '-o', str(binary)],
                                      cwd=ROOT, capture_output=True, text=True, timeout=120)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            done = subprocess.run([str(binary), '--help'], cwd=ROOT, capture_output=True, text=True,
                                  timeout=30, env=dict(os.environ, PUPPYBOT_SIM_DOCK_SECOND_WAYPOINT='invalid'))
            self.assertNotEqual(done.returncode, 0); self.assertIn('Invalid dock second waypoint option', done.stderr)
            replacements = {
                'dock-search.flex': {'ps_dock_waypoint_plan': 'fn ps_dock_waypoint_plan() { probe_plans = probe_plans + 1; return probe_route; }'},
                'dock-vision.flex': {'ps_dock_fresh': 'fn ps_dock_fresh() { return 0; }'},
                'pickup.flex': {'ps_pickup_settled': 'fn ps_pickup_settled() { return 1; }'},
                'navigation.flex': {'ps_nav_tick': 'fn ps_nav_tick() { return 1; }'},
                'case.flex': {'ps_case_travel_pose': 'fn ps_case_travel_pose() { return probe_travel; }',
                              'ps_case_tcp_survey': 'fn ps_case_tcp_survey() { probe_surveys = probe_surveys + 1; return 1; }',
                              'ps_case_fail': 'fn ps_case_fail(reason) { ps_case_phase(13); return 0; }'},
            }
            for name, functions in replacements.items():
                path = sim / name; text = path.read_text()
                for function, body in functions.items(): text = replace_function(text, function, body)
                path.write_text(text)
            main = sim / 'main.flex'; text = main.read_text()
            probe = (HERE / 'probe.flex').read_text(); globals_, functions = probe.split('fn probe_reset()', 1)
            text = transform.once(text, 'global ps_robot = 0;', globals_ + '\nglobal ps_robot = 0;')
            main.write_text(transform.once(text, 'fn main(argc, argv) {', 'fn probe_original_main(argc, argv) {') + '\nfn probe_reset()' + functions)
            probe_binary = root / 'probe'
            compiled = subprocess.run([str(COMPILER), str(main), '-o', str(probe_binary)],
                                      cwd=ROOT, capture_output=True, text=True, timeout=120)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            done = subprocess.run([str(probe_binary)], cwd=ROOT, capture_output=True, text=True, timeout=30)
            self.assertEqual(done.returncode, 0, f'rc={done.returncode}\n{done.stdout}{done.stderr}')
            self.assertIn('second waypoint transition checks passed', done.stdout)
        builder.verify(ARCHIVE)


if __name__ == '__main__':
    unittest.main()
