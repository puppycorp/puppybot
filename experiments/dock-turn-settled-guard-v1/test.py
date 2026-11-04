#!/usr/bin/env python3
"""Test the settled-only turn guard using private native CPU copies."""
import importlib.util
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
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load('waypoint_builder', ROOT / 'experiments/dock-short-waypoint-v1/build.py')
previous = load('floor_test', ROOT / 'experiments/dock-floor-refresh-v1/test.py')
transform = builder.transform
candidate = load('settled_turn_guard', HERE / 'transform.py')


class TurnFreshnessTest(unittest.TestCase):
    def test_native_original_and_guarded(self):
        builder.verify(ARCHIVE)
        with tempfile.TemporaryDirectory(prefix='puppy-dock-turn-freshness-') as temp:
            root = Path(temp); source = root / 'source'; build = root / 'build'
            shutil.copytree(ARCHIVE / 'source', source); shutil.copytree(ARCHIVE / 'build', build)
            library = build / 'flex/sim/library'; adapter = library / 'lib/f64.flex'
            adapter.write_text(transform.once(adapter.read_text(),
                f'import "{ARCHIVE / "source/core/words.flex"}";', f'import "{source / "core/words.flex"}";'))
            (library.parent / 'dependencies.flex').write_text(
                f'import "{library / "libs/render.flex"}";\nimport "{library / "libs/physics/physics.flex"}";\n')
            replacements = {
                'sim/dock-search.flex': {'ps_dock_search_stage': 'fn ps_dock_search_stage() { probe_stages = probe_stages + 1; return 1; }'},
                'sim/dock-vision.flex': {'ps_dock_sample': '''fn ps_dock_sample() {
                    probe_samples = probe_samples + 1;
                    if probe_sample_mode == 1 { ps_dock_valid = 1; ps_dock_seen = ps_total; ps_dock_stable = 3; }
                    if probe_sample_mode == 2 { ps_dock_valid = 0; }
                    return 1; }'''},
                'sim/pickup.flex': {'ps_pickup_settled': 'fn ps_pickup_settled() { return probe_settled; }',
                                    'ps_arm_move_timeout': 'fn ps_arm_move_timeout() { return 1000; }'},
                'sim/gripper.flex': {'ps_gripper_command': 'fn ps_gripper_command(open) { if open { probe_opens = probe_opens + 1; } return 1; }'},
                'sim/case.flex': {'ps_case_tcp_survey': 'fn ps_case_tcp_survey() { probe_surveys = probe_surveys + 1; ps_case_phase(20); return 1; }'},
                'runtime/app.flex': {'pr_apply': 'fn pr_apply(app, command, values, now) { if command == 5 { probe_commands = probe_commands + 1; } return 0; }'},
            }
            for name, functions in replacements.items():
                path = source / name; text = path.read_text()
                for function, body in functions.items():
                    text = previous.replace_function(text, function, body)
                path.write_text(text)
            main = source / 'sim/main.flex'; text = main.read_text()
            probe = (HERE / 'probe.flex').read_text(); globals_, functions = probe.split('fn probe_setup()', 1)
            text = transform.once(text, 'global ps_robot = 0;', globals_ + '\nglobal ps_robot = 0;')
            text = transform.once(text, 'fn main(argc, argv) {', 'fn probe_original_main(argc, argv) {')
            original_case = (source / 'sim/case.flex').read_text()
            for patched in (0, 1):
                (source / 'sim/case.flex').write_text(candidate.transform(original_case) if patched else original_case)
                main.write_text((text + '\nfn probe_setup()' + functions).replace('@@PATCHED@@', str(patched)))
                binary = root / ('probe-' + str(patched))
                compiled = subprocess.run([str(COMPILER), str(main), '-o', str(binary)], cwd=ROOT,
                                          capture_output=True, text=True, timeout=120)
                self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
                done = subprocess.run([str(binary)], cwd=ROOT, capture_output=True, text=True, timeout=30)
                self.assertEqual(done.returncode, 0, f'patched={patched}, rc={done.returncode}\n{done.stdout}{done.stderr}')
                self.assertIn('turn freshness probe passed', done.stdout)
        builder.verify(ARCHIVE)


if __name__ == '__main__':
    unittest.main()
