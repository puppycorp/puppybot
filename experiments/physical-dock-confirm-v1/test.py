#!/usr/bin/env python3
"""CPU-only disposable native dispatch and state-machine tests."""
import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ARCHIVE = ROOT / 'build/flex/sim/levels-v2/pitch82/physical-search-fallback-build-v1'
COMPILER = ROOT / 'build/flex/control/compiler'
spec = importlib.util.spec_from_file_location('dock_transform', HERE / 'transform.py')
transform = importlib.util.module_from_spec(spec); spec.loader.exec_module(transform)
spec = importlib.util.spec_from_file_location('dock_build', HERE / 'build.py')
builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)


def replace_function(path, start, end, body):
    text = path.read_text(); a = text.index('fn ' + start + '('); b = text.index('fn ' + end + '(', a)
    path.write_text(text[:a] + body + '\n' + text[b:])


class NativeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='puppy-dock-confirm-')
        root = Path(cls.tmp.name); source = root / 'source'; build = root / 'build'
        shutil.copytree(ARCHIVE / 'source', source); shutil.copytree(ARCHIVE / 'build', build)
        library = build / 'flex/sim/library'; adapter = library / 'lib/f64.flex'
        text = adapter.read_text(); old = str(ARCHIVE / 'source/core/words.flex'); new = str(source / 'core/words.flex')
        if text.count(old) != 1: raise ValueError('unexpected adapter')
        adapter.write_text(text.replace(old, new))
        (library.parent / 'dependencies.flex').write_text(f'import "{library / "libs/render.flex"}";\nimport "{library / "libs/physics/physics.flex"}";\n')
        collect = source / 'sim/collect.flex'; discovery = source / 'sim/discovery.flex'; main = source / 'sim/main.flex'
        c, d, m = transform.transform(collect.read_text(), discovery.read_text(), main.read_text())
        collect.write_text(c); discovery.write_text(d); main.write_text(m)
        brick = source / 'sim/brick-vision.flex'
        replace_function(brick, 'ps_brick_detect', 'ps_rgb_sample', 'fn ps_brick_detect() { ps_brick_count = 0; return 1; }')
        replace_function(brick, 'ps_rgb_sample', 'ps_brick_sample', 'fn ps_rgb_sample() { dc_samples = dc_samples + 1; if dc_fail { return 0; } if !dc_stale { ps_brick_frame = ps_total; } return 1; }')
        dock = source / 'sim/dock-vision.flex'
        replace_function(dock, 'ps_dock_detect', 'ps_dock_mark', 'fn ps_dock_detect() { ps_dock_valid = 0; if dc_dropout { return 0; } let x = 0; if dc_jitter { x = ps_number(dc_samples * 4, 1000); } return ps_dock_pose(x, 0, PB_ONE, 0, 4); }')
        replace_function(dock, 'ps_dock_attention', 'ps_dock_sample', 'fn ps_dock_attention(found) { return found; }')
        floor = source / 'sim/floor-memory.flex'
        replace_function(floor, 'ps_floor_observe', 'ps_floor_forget', 'fn ps_floor_observe() { if dc_floor == 1 || (dc_floor == 2 && dc_samples >= 2) { ps_floor_changed = 1; } return 1; }')
        replace_function(collect, 'ps_collect_search_begin', 'ps_collect_attention', 'fn ps_collect_search_begin() { dc_replans = dc_replans + 1; return 1; }')
        camera = source / 'sim/camera.flex'
        replace_function(camera, 'ps_camera_still', 'ps_camera_observation', 'fn ps_camera_still() { return dc_still; }')
        drive = source / 'core/drive.flex'
        replace_function(drive, 'pb_drive_stop', 'pb_drive_init', 'fn pb_drive_stop(drive, now) { if !dc_stop_fail { pb_vset(drive, 6, 0); pb_vset(drive, 7, 0); } return 0; }')
        replace_function(discovery, 'ps_discovery_finish', 'ps_discovery_reset', 'fn ps_discovery_finish(reason, failed) { dc_finished = failed; return 0; }')
        text = main.read_text(); marker = 'global ps_robot = 0;'
        if text.count(marker) != 1 or text.count('fn main(argc, argv) {') != 1: raise ValueError('unexpected main')
        declarations = 'global dc_samples=0; global dc_fail=0; global dc_stale=0; global dc_dropout=0; global dc_jitter=0; global dc_still=1; global dc_finished=0; global dc_stop_fail=0; global dc_floor=0; global dc_replans=0;\n'
        text = text.replace(marker, declarations + marker, 1).replace('fn main(argc, argv) {', 'fn dc_original_main(argc, argv) {', 1)
        main.write_text(text + '\n' + (HERE / 'test-probe.flex').read_text())
        cls.binary = root / 'probe'
        result = subprocess.run([str(COMPILER), str(main), '-o', str(cls.binary)], cwd=ROOT, capture_output=True, text=True, timeout=120)
        if result.returncode: raise RuntimeError(result.stdout + result.stderr)

    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def test_state_and_real_discovery_dispatch(self):
        for mode in ('normal', 'travel', 'disabled', 'no-local', 'oracle', 'duplicate', 'stale', 'dropout', 'jitter', 'timeout', 'movement', 'blocked', 'camera', 'sensor-fail', 'stop-fail', 'budget', 'new-floor', 'floor-on-confirm', 'runs-limit'):
            with self.subTest(mode=mode):
                p = subprocess.run([str(self.binary), mode], cwd=ROOT, capture_output=True, text=True, timeout=10)
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_transform_rejects_changed_or_repeated_sources(self):
        src = ARCHIVE / 'source/sim'
        c, d, m = [(src / name).read_text() for name in ('collect.flex', 'discovery.flex', 'main.flex')]
        a, b, e = transform.transform(c, d, m)
        with self.assertRaises(ValueError): transform.transform(a, b, e)
        with self.assertRaises(ValueError): transform.transform(c.replace('fn ps_collect_travel_observe()', 'fn modified()'), d, m)


class BuildTest(unittest.TestCase):
    def test_full_simulator_build_and_existing_output_refusal(self):
        with tempfile.TemporaryDirectory(prefix='puppy-dock-build-') as temporary:
            output = Path(temporary) / 'candidate'
            report = builder.build(output)
            self.assertEqual(builder.search.sha(output / 'simulator'), report['simulatorSHA256'])
            self.assertEqual(builder.search.sha(output / 'client'), report['clientSHA256'])
            self.assertTrue((output / 'simulator').stat().st_mode & 0o111)
            before = (output / 'build.json').read_bytes()
            with self.assertRaises(ValueError): builder.build(output)
            self.assertEqual((output / 'build.json').read_bytes(), before)


if __name__ == '__main__': unittest.main()
