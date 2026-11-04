#!/usr/bin/env python3
"""CPU-only virtual barrier checks; no renderer or policy execution."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
ARCHIVE = ROOT / 'build/flex/sim/levels-v2/pitch82/dock-survey-elevation-build-v1'
COMPILER = ROOT / 'build/flex/control/compiler'
spec = importlib.util.spec_from_file_location('barrier_transform', HERE / 'transform.py')
transform = importlib.util.module_from_spec(spec); spec.loader.exec_module(transform)


def run(argv, **kwargs):
    return subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=120, **kwargs)


class BarrierTests(unittest.TestCase):
    def test_frozen_tick_and_failure_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'probe.flex'; binary = Path(temp) / 'probe'
            source.write_text(transform.GLOBAL + (HERE / 'probe.flex').read_text() + transform.HELPER +
                              (HERE / 'probe-main.flex').read_text())
            built = run([str(COMPILER), str(source), '-o', str(binary)])
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            result = run([str(binary)])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('Virtual worker barrier probe passed.', result.stdout)

    def test_real_child_processes_do_not_advance_tick(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'probe.flex'; binary = Path(temp) / 'probe'
            host = ARCHIVE / 'build/flex/sim/library/scripts/lib/host.flex'
            source.write_text(f'import "{host}";\n' + transform.GLOBAL +
                              (HERE / 'process-probe.flex').read_text() + transform.HELPER +
                              (HERE / 'process-main.flex').read_text())
            built = run([str(COMPILER), str(source), '-o', str(binary)])
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            result = run([str(binary)])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('Real child process barrier probe passed.', result.stdout)

    def test_full_simulator_compiles_and_mode_is_guarded(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp); source = output / 'source'; build = output / 'build'
            shutil.copytree(ARCHIVE / 'source', source)
            shutil.copytree(ARCHIVE / 'build', build)
            library = build / 'flex/sim/library'; adapter = library / 'lib/f64.flex'
            old = f'import "{ARCHIVE / "source/core/words.flex"}";'
            new = f'import "{source / "core/words.flex"}";'
            adapter.write_text(transform.once(adapter.read_text(), old, new))
            (library.parent / 'dependencies.flex').write_text(
                f'import "{library / "libs/render.flex"}";\nimport "{library / "libs/physics/physics.flex"}";\n')
            discovery = source / 'sim/discovery.flex'; main = source / 'sim/main.flex'
            a, b = transform.transform(discovery.read_text(), main.read_text())
            discovery.write_text(a); main.write_text(b)
            binary = output / 'simulator'
            built = run([str(COMPILER), str(main), '-o', str(binary)])
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            read_fd, write_fd = os.pipe()
            try:
                fd = str(read_fd)
                invalid_modes = ([], ['--external-serial'], ['--agent-physical'],
                                 ['--agent-fd', fd],
                                 ['--agent-physical', '--agent-fd', fd, '--realtime'],
                                 ['--agent-physical', '--agent-fd', fd, '--external-serial'])
                for argv in invalid_modes:
                    env = dict(os.environ, PUPPYBOT_SIM_WORKER_BARRIER='1')
                    result = run([str(binary), *argv], env=env, pass_fds=(read_fd,))
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertIn('restricted to a non-realtime virtual', result.stderr)
            finally:
                os.close(read_fd); os.close(write_fd)

            driver = transform.once(b, 'fn main(argc, argv) {', 'fn simulator_main(argc, argv) {')
            main.write_text(driver + '\n' + (HERE / 'invalid-output-main.flex').read_text())
            built = run([str(COMPILER), str(main), '-o', str(binary)])
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            result = run([str(binary)])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('Malformed worker output rejected without applying map.', result.stdout)


if __name__ == '__main__':
    unittest.main()
