#!/usr/bin/env python3
"""Compile the copied simulator and exercise its recovery state machine."""
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ARCHIVE = ROOT / 'build/flex/sim/levels-v2/pitch82/observed-footprint-matched-build-v2'
COMPILER = ROOT / 'build/flex/control/compiler'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


transform = load('dock_floor_refresh', HERE / 'transform.py')
builder = load('dock_floor_base', ROOT / 'experiments/observed-footprint-matched-v1/build.py')


def replace_function(source, name, replacement):
    start = source.index('fn ' + name + '(')
    end = source.index('\nfn ', start + 1)
    return source[:start] + replacement + source[end:]


class FloorRefreshTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        builder.verify(ARCHIVE)
        cls.temp = tempfile.TemporaryDirectory(prefix='puppy-dock-floor-refresh-')
        root = Path(cls.temp.name); cls.source = root / 'source'; build = root / 'build'
        shutil.copytree(ARCHIVE / 'source', cls.source); shutil.copytree(ARCHIVE / 'build', build)
        library = build / 'flex/sim/library'; adapter = library / 'lib/f64.flex'
        adapter.write_text(transform.once(adapter.read_text(),
            f'import "{ARCHIVE / "source/core/words.flex"}";',
            f'import "{cls.source / "core/words.flex"}";'))
        (library.parent / 'dependencies.flex').write_text(
            f'import "{library / "libs/render.flex"}";\nimport "{library / "libs/physics/physics.flex"}";\n')
        sim = cls.source / 'sim'
        files = [sim / name for name in ('dock-search.flex', 'collect.flex', 'main.flex')]
        for path, text in zip(files, transform.transform(*(p.read_text() for p in files))):
            path.write_text(text)
        cls.binary = root / 'simulator'
        subprocess.run([str(COMPILER), str(sim / 'main.flex'), '-o', str(cls.binary)],
                       cwd=ROOT, text=True, capture_output=True, timeout=120, check=True)
        # Keep the real transformed branches and replace only external actor,
        # motion and sensor dependencies. These stubs cannot demonstrate an
        # actual rendered scan, mapping output, or physical robot stop.
        original_map_begin = builder.function((sim / 'collect.flex').read_text(), 'ps_collect_map_begin')
        original_diagnostic = builder.function((sim / 'dock-vision.flex').read_text(), 'ps_dock_diag_candidate')
        replacements = {
            'dock-search.flex': {
                'ps_dock_search_candidate': 'fn ps_dock_search_candidate(index, out) { return 1; }',
                'ps_dock_search_stage': 'fn ps_dock_search_stage() { probe_stages = probe_stages + 1; return probe_stage_ok; }'},
            'dock-vision.flex': {'ps_dock_fresh': 'fn ps_dock_fresh() { return probe_fresh; }',
                                 'ps_dock_diag_candidate': 'fn ps_dock_diag_candidate(index, goal, planned) { return 1; }'},
            'navigation.flex': {'ps_nav_plan': 'fn ps_nav_plan(x, y, heading) { probe_plans = probe_plans + 1; return 0; }'},
            'collect.flex': {'ps_collect_map_begin': '''fn ps_collect_map_begin() {
                probe_maps = probe_maps + 1; if probe_map_mode { ps_case_stage = 13; probe_fails = probe_fails + 1; return 0; }
                ps_collect_mapping = 1; ps_collect_map_started = ps_total; ps_dock_search_maps = ps_dock_search_maps + 1;
                ps_dock_search_map_index = ps_dock_search_index; return 1; }'''},
            'discovery.flex': {'ps_discovery_next_sector': 'fn ps_discovery_next_sector() { probe_sectors = probe_sectors + 1; return 1; }'},
            'case.flex': {'ps_case_fail': 'fn ps_case_fail(reason) { probe_fails = probe_fails + 1; ps_case_stage = 13; return 0; }',
                          'ps_case_tcp_survey': 'fn ps_case_tcp_survey() { probe_surveys = probe_surveys + 1; return 1; }'},
        }
        for name, functions in replacements.items():
            path = sim / name; text = path.read_text()
            for function, body in functions.items():
                text = replace_function(text, function, body)
            if name == 'dock-search.flex':
                needle = '    pb_drive_stop(pb_robot_drive(ps_robot), ps_time);\n    ps_dock_search_staged = 0;'
                text = transform.once(text, needle, '    ps_dock_search_staged = 0;')
            path.write_text(text)
        main = sim / 'main.flex'; text = main.read_text()
        probe = (HERE / 'probe.flex').read_text(); globals_, functions = probe.split('fn probe_reset()', 1)
        text = transform.once(text, 'global ps_robot = 0;', globals_ + '\nglobal ps_robot = 0;')
        main.write_text(transform.once(text, 'fn main(argc, argv) {', 'fn probe_original_main(argc, argv) {')
                        + '\nfn probe_reset()' + functions)
        probe_main = main.read_text()
        cls.probe = root / 'probe'
        compiled = subprocess.run([str(COMPILER), str(main), '-o', str(cls.probe)], cwd=ROOT,
                                  text=True, capture_output=True, timeout=120)
        if compiled.returncode:
            raise RuntimeError(compiled.stdout + '\n' + compiled.stderr)
        # Reuse the transformed real map-begin/end code while stubbing only
        # arm actuation and the camera worker. Verify its fresh-map setup and
        # the transition back to survey in a private directory.
        collect = sim / 'collect.flex'; text = collect.read_text()
        stopped = transform.once(original_map_begin,
            '    pb_drive_stop(pb_robot_drive(ps_robot), ps_time); ps_collect_mapping = 1;',
            '    ps_collect_mapping = 1;')
        collect.write_text(replace_function(text, 'ps_collect_map_begin', stopped))
        discovery = sim / 'discovery.flex'; text = discovery.read_text()
        discovery.write_text(replace_function(text, 'ps_discovery_first_view',
            'fn ps_discovery_first_view() { ps_discovery_phase = 1; return 1; }'))
        map_dir = root / 'scan-map'; map_dir.mkdir()
        map_probe = (HERE / 'map-probe.flex').read_text().replace('@@MAP@@', str(map_dir))
        before = probe_main[:probe_main.index('fn probe_reset()')]
        main.write_text(before + '\n' + map_probe)
        cls.map_probe = root / 'map-probe'
        compiled = subprocess.run([str(COMPILER), str(main), '-o', str(cls.map_probe)], cwd=ROOT,
                                  text=True, capture_output=True, timeout=120)
        if compiled.returncode:
            raise RuntimeError(compiled.stdout + '\n' + compiled.stderr)
        vision = sim / 'dock-vision.flex'; text = vision.read_text()
        vision.write_text(replace_function(text, 'ps_dock_diag_candidate', original_diagnostic))
        cls.diag_dir = root / 'diagnostic'; cls.diag_dir.mkdir()
        diag_probe = (HERE / 'diag-probe.flex').read_text().replace('@@DIAG@@', str(cls.diag_dir))
        main.write_text(before + '\n' + diag_probe); cls.diag_probe = root / 'diag-probe'
        compiled = subprocess.run([str(COMPILER), str(main), '-o', str(cls.diag_probe)], cwd=ROOT,
                                  text=True, capture_output=True, timeout=120)
        if compiled.returncode:
            raise RuntimeError(compiled.stdout + '\n' + compiled.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_recovery_branches(self):
        done = subprocess.run([str(self.probe)], cwd=ROOT, text=True, capture_output=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn('branch checks passed', done.stdout)

    def test_real_map_setup_and_return_to_survey(self):
        done = subprocess.run([str(self.map_probe)], cwd=ROOT, text=True, capture_output=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn('map setup passed', done.stdout)

    def test_real_diagnostic_writer_preserves_both_sweeps(self):
        done = subprocess.run([str(self.diag_probe)], cwd=ROOT, text=True, capture_output=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        first = json.loads((self.diag_dir / 'search-1-candidate-0.json').read_text())
        second = json.loads((self.diag_dir / 'search-2-candidate-0.json').read_text())
        self.assertEqual((first['search'], first['step']), (1, 100))
        self.assertEqual((second['search'], second['step']), (2, 200))

    def test_invalid_option_rejected_by_full_simulator(self):
        env = dict(os.environ, PUPPYBOT_SIM_DOCK_FLOOR_RETRY='invalid')
        done = subprocess.run([str(self.binary), '--help'], cwd=ROOT, env=env, text=True,
                              capture_output=True, timeout=30)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn('Invalid dock floor retry option', done.stderr)


if __name__ == '__main__':
    unittest.main()
