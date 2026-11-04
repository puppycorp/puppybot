#!/usr/bin/env python3
"""Compile all private variants and exercise their actual injected fault hooks."""
import importlib.util
import shutil
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


inject = load('turn_rendered_transform', HERE / 'transform.py')
previous = load('turn_current_test', ROOT / 'experiments/dock-turn-reacquire-current-v1/test.py')


class ProbeTest(unittest.TestCase):
    def test_faults_and_full_compilation(self):
        baseline = (ROOT / 'experiments/dock-turn-reacquire-current-v1/baseline-case.flex').read_text()
        candidate = previous.candidate.transform(baseline)
        self.assertEqual(candidate, (ROOT / 'flex/sim/case.flex').read_text())
        original_dock = (ROOT / 'flex/sim/dock-vision.flex').read_text()
        with tempfile.TemporaryDirectory(prefix='dock-turn-rendered-probe-') as temp:
            root = Path(temp); source = root / 'flex'; library = root / 'build/flex/sim/library'
            shutil.copytree(ROOT / 'flex', source, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            shutil.copytree(ROOT / 'build/flex/sim/library', library)
            adapter = library / 'lib/f64.flex'
            adapter.write_text(inject.once(adapter.read_text(), f'import "{ROOT / "flex/core/words.flex"}";',
                                           f'import "{source / "core/words.flex"}";'))
            (library.parent / 'dependencies.flex').write_text(
                f'import "{library / "libs/render.flex"}";\nimport "{library / "libs/physics/physics.flex"}";\n')
            main = source / 'sim/main.flex'; original_main = main.read_text()
            compiler = ROOT / 'build/flex/control/compiler'
            for is_candidate, source_case in ((False, baseline), (True, candidate)):
                for duration in (0, 10, 60):
                    with self.subTest(candidate=is_candidate, duration=duration):
                        case, dock = inject.transform(source_case, original_dock, duration, is_candidate)
                        (source / 'sim/case.flex').write_text(case)
                        (source / 'sim/dock-vision.flex').write_text(dock)
                        compiled = subprocess.run([str(compiler), str(main), '-o', str(root / 'full')],
                                                  cwd=ROOT, capture_output=True, text=True, timeout=120)
                        self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            replacements = {
                'sim/brick-vision.flex': {'ps_rgb_sample': 'fn ps_rgb_sample() { return 1; }'},
                'sim/dock-vision.flex': {
                    'ps_dock_detect': 'fn ps_dock_detect() { return ps_dock_pose(0, 0, PB_ONE, 0, 4); }',
                    'ps_dock_attention': 'fn ps_dock_attention(found) { return 0; }',
                    'ps_dock_mark': 'fn ps_dock_mark() { return 0; }'},
                'sim/pickup.flex': {'ps_pickup_settled': 'fn ps_pickup_settled() { return 1; }',
                                    'ps_arm_move_timeout': 'fn ps_arm_move_timeout() { return 1000; }'},
                'sim/gripper.flex': {'ps_gripper_command': 'fn ps_gripper_command(open) { if open { probe_opens = probe_opens + 1; } return 1; }'},
                'runtime/app.flex': {'pr_apply': 'fn pr_apply(app, command, values, now) { if command == 5 { probe_commands = probe_commands + 1; } return 0; }'},
            }
            for name, funcs in replacements.items():
                if name == 'sim/dock-vision.flex':
                    continue
                path = source / name; text = path.read_text()
                for function, body in funcs.items():
                    text = previous.previous.replace_function(text, function, body)
                path.write_text(text)
            probe = (HERE / 'probe.flex').read_text(); globals_, functions = probe.split('fn main(argc, argv) {', 1)
            text = inject.once(original_main, 'global ps_robot = 0;', globals_ + '\nglobal ps_robot = 0;')
            text = inject.once(text, 'fn main(argc, argv) {', 'fn probe_original_main(argc, argv) {')
            for is_candidate, source_case in ((False, baseline), (True, candidate)):
                for duration in (0, 10, 60):
                    with self.subTest(probe_candidate=is_candidate, duration=duration):
                        case, dock = inject.transform(source_case, original_dock, duration, is_candidate)
                        for function, body in replacements['sim/dock-vision.flex'].items():
                            dock = previous.previous.replace_function(dock, function, body)
                        (source / 'sim/case.flex').write_text(case)
                        (source / 'sim/dock-vision.flex').write_text(dock)
                        probe_main = (text + '\nfn main(argc, argv) {' + functions).replace('@@CANDIDATE@@', str(int(is_candidate))).replace('@@DURATION@@', str(duration))
                        main.write_text(probe_main)
                        binary = root / 'probe'
                        compiled = subprocess.run([str(compiler), str(main), '-o', str(binary)], cwd=ROOT,
                                                  capture_output=True, text=True, timeout=120)
                        self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
                        done = subprocess.run([str(binary)], cwd=ROOT, capture_output=True, text=True, timeout=30)
                        self.assertEqual(done.returncode, 0, done.stdout + done.stderr + f' exit={done.returncode}')
                        self.assertIn('rendered fault probe passed', done.stdout)


if __name__ == '__main__':
    unittest.main()
