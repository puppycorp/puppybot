#!/usr/bin/env python3
"""Probe the exact current-source guard and its bounded-wait candidate."""
import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
COMPILER = ROOT / 'build/flex/control/compiler'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


candidate = load('current_turn_reacquire', HERE / 'transform.py')
previous = load('floor_test', ROOT / 'experiments/dock-floor-refresh-v1/test.py')


class CurrentTurnReacquireTest(unittest.TestCase):
    def test_current_and_reacquire(self):
        baseline = (HERE / 'baseline-case.flex').read_text()
        patched = candidate.transform(baseline)
        self.assertIn((ROOT / 'flex/sim/case.flex').read_text(), (baseline, patched),
                      'live case source no longer matches the tested versions')
        with tempfile.TemporaryDirectory(prefix='puppy-dock-current-reacquire-') as temp:
            root = Path(temp); source = root / 'flex'; library = root / 'build/flex/sim/library'
            shutil.copytree(ROOT / 'flex', source, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            shutil.copytree(ROOT / 'build/flex/sim/library', library)
            adapter = library / 'lib/f64.flex'
            adapter.write_text(candidate.candidate.once(adapter.read_text(),
                f'import "{ROOT / "flex/core/words.flex"}";', f'import "{source / "core/words.flex"}";'))
            (library.parent / 'dependencies.flex').write_text(
                f'import "{library / "libs/render.flex"}";\nimport "{library / "libs/physics/physics.flex"}";\n')
            case = source / 'sim/case.flex'
            for name, text in (('baseline', baseline), ('candidate', patched)):
                case.write_text(text)
                compiled = subprocess.run([str(COMPILER), str(source / 'sim/main.flex'), '-o', str(root / name)],
                                          cwd=ROOT, capture_output=True, text=True, timeout=120)
                self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            case.write_text(baseline)
            replacements = {
                'sim/dock-search.flex': {'ps_dock_search_stage': 'fn ps_dock_search_stage() { probe_stages = probe_stages + 1; return 1; }'},
                'sim/dock-vision.flex': {'ps_dock_sample': '''fn ps_dock_sample() {
                    probe_samples = probe_samples + 1;
                    if probe_sample_mode == 1 { ps_dock_pose(0, 0, PB_ONE, 0, 4); }
                    if probe_sample_mode == 2 { ps_dock_valid = 0; ps_dock_stable = 0; }
                    if probe_sample_mode == 3 { ps_dock_valid = 0; }
                    return 1; }'''},
                'sim/pickup.flex': {'ps_pickup_settled': 'fn ps_pickup_settled() { return probe_settled; }',
                                    'ps_arm_move_timeout': 'fn ps_arm_move_timeout() { return 1000; }'},
                'sim/gripper.flex': {'ps_gripper_command': 'fn ps_gripper_command(open) { if open { probe_opens = probe_opens + 1; } return 1; }'},
                'sim/case.flex': {'ps_case_tcp_survey': 'fn ps_case_tcp_survey() { probe_surveys = probe_surveys + 1; ps_case_phase(20); return 1; }',
                                  'ps_case_payload_stow': 'fn ps_case_payload_stow() { probe_stows = probe_stows + 1; return 1; }'},
                'runtime/app.flex': {'pr_apply': 'fn pr_apply(app, command, values, now) { if command == 5 { probe_commands = probe_commands + 1; } return 0; }'},
            }
            for name, functions in replacements.items():
                path = source / name; text = path.read_text()
                for function, body in functions.items():
                    text = previous.replace_function(text, function, body)
                path.write_text(text)
            main = source / 'sim/main.flex'; text = main.read_text()
            probe = (HERE / 'probe.flex').read_text(); globals_, functions = probe.split('fn probe_setup()', 1)
            text = candidate.candidate.once(text, 'global ps_robot = 0;', globals_ + '\nglobal ps_robot = 0;')
            text = candidate.candidate.once(text, 'fn main(argc, argv) {', 'fn probe_original_main(argc, argv) {')
            original_case = case.read_text()
            for enabled in (0, 1):
                control = candidate.candidate.once(original_case, 'global ps_case_drop_turning = 0;', '''global ps_case_drop_turning = 0;
global ps_case_drop_reacquire_started = -1;
global ps_case_drop_reacquire_last = -1;''')
                case.write_text(candidate.transform(original_case) if enabled else control)
                main.write_text((text + '\nfn probe_setup()' + functions).replace('@@PATCHED@@', str(enabled)))
                binary = root / ('probe-' + str(enabled))
                compiled = subprocess.run([str(COMPILER), str(main), '-o', str(binary)], cwd=ROOT,
                                          capture_output=True, text=True, timeout=120)
                self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
                done = subprocess.run([str(binary)], cwd=ROOT, capture_output=True, text=True, timeout=30)
                self.assertEqual(done.returncode, 0, f'enabled={enabled}, rc={done.returncode}\n{done.stdout}{done.stderr}')
                self.assertIn('turn reacquisition probe passed', done.stdout)


if __name__ == '__main__':
    unittest.main()
