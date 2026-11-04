#!/usr/bin/env python3
"""CPU-only tests against the actual Flex dock detector in a copied tree."""
import importlib.util
import hashlib
import json
import os
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ARCHIVE = ROOT / 'build/flex/sim/levels-v2/pitch82/dock-clearance-build-v1'
RUNS = ROOT / 'build/flex/sim/levels-v2/pitch82'
COMPILER = ROOT / 'build/flex/control/compiler'
spec = importlib.util.spec_from_file_location('rim_transform', HERE / 'transform.py')
transform = importlib.util.module_from_spec(spec); spec.loader.exec_module(transform)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_inputs():
    receipt = json.loads((HERE / 'input-receipt.json').read_text())
    if receipt['schema'] != 'puppybot.rim-audit-inputs.v1':
        raise ValueError('unexpected input receipt schema')
    report_path = ARCHIVE / 'build.json'
    if digest(report_path) != receipt['archiveBuildSHA256'] or digest(COMPILER) != receipt['compilerSHA256']:
        raise ValueError('archive report or compiler differs from receipt')
    report = json.loads(report_path.read_text())
    if report['compilerSHA256'] != receipt['compilerSHA256']:
        raise ValueError('compiler differs from archived build')
    for key, directory in (('source', ARCHIVE / 'source'),
                           ('library', ARCHIVE / 'build/flex/sim/library')):
        current = {str(p.relative_to(directory)): digest(p) for p in directory.rglob('*') if p.is_file()}
        if current != report[key]:
            raise ValueError(f'archived {key} differs from build report')
    frames = json.loads((HERE / 'recorded-components.json').read_text())
    if len(frames) != 18 or len(receipt['cameraSHA256']) != 18:
        raise ValueError('saved frame inventory differs')
    for frame in frames:
        path = Path(frame['path']); camera = path.with_suffix('.sensor.camera.json')
        if digest(path) != frame['sha256'] or digest(camera) != receipt['cameraSHA256'].get(str(camera)):
            raise ValueError(f'RGB or calibration differs: {path}')


class DetectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        verify_inputs()
        cls.temp = tempfile.TemporaryDirectory(prefix='puppy-rim-cpu-')
        root = Path(cls.temp.name); source = root / 'source'; build = root / 'build'
        shutil.copytree(ARCHIVE / 'source', source)
        shutil.copytree(ARCHIVE / 'build', build)
        library = build / 'flex/sim/library'; adapter = library / 'lib/f64.flex'
        adapter.write_text(transform.once(adapter.read_text(),
                           f'import "{ARCHIVE / "source/core/words.flex"}";',
                           f'import "{source / "core/words.flex"}";'))
        (library.parent / 'dependencies.flex').write_text(
            f'import "{library / "libs/render.flex"}";\nimport "{library / "libs/physics/physics.flex"}";\n')
        dock = source / 'sim/dock-vision.flex'; main = source / 'sim/main.flex'
        original_dock, original_main = dock.read_text(), main.read_text()
        candidate_dock, candidate_main = transform.transform(original_dock, original_main)
        dock.write_text(candidate_dock)
        main.write_text(candidate_main)
        cls.native = root / 'simulator'
        result = subprocess.run([str(COMPILER), str(main), '-o', str(cls.native)], cwd=ROOT,
                                capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        main.write_text(transform.once(candidate_main, 'fn main(argc, argv) {',
                                        'fn rim_original_main(argc, argv) {') + '\n' +
                        (HERE / 'probe.flex').read_text())
        cls.probe = root / 'probe'; cls.root = root
        result = subprocess.run([str(COMPILER), str(main), '-o', str(cls.probe)], cwd=ROOT,
                                capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        # The baseline adds only the unused probe variable, leaving the old
        # component-size condition itself intact.
        dock.write_text(transform.once(original_dock, 'global ps_dock_count = 0;',
                                      'global ps_dock_count = 0;\nglobal ps_dock_small_components = 0;'))
        main.write_text(transform.once(original_main, 'fn main(argc, argv) {',
                                        'fn rim_original_main(argc, argv) {') + '\n' +
                        (HERE / 'probe.flex').read_text())
        cls.baseline = root / 'baseline'
        result = subprocess.run([str(COMPILER), str(main), '-o', str(cls.baseline)], cwd=ROOT,
                                capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_probe(self, rgb, camera, enabled, baseline=False):
        calibration = json.loads(camera.read_text())
        vals = sum((calibration[k] for k in ('eyeM', 'forward', 'right', 'down')), [])
        sidecar = self.root / 'camera.bin'; sidecar.write_bytes(struct.pack('<12d', *vals))
        setting = 'default' if enabled == 'default' else str(int(enabled))
        result = subprocess.run([str(self.baseline if baseline else self.probe), str(rgb), str(sidecar), setting],
                                cwd=ROOT, capture_output=True, text=True, timeout=15, check=True)
        return json.loads(result.stdout)

    def frame(self, run, n):
        base = RUNS / (run + '-monitored-v1/trial/candidate-search/diagnostic')
        return base / f'survey-{n}.rgb', base / f'survey-{n}.sensor.camera.json'

    def test_recorded_success_and_failed_views(self):
        success = self.frame('dock-survey-elevation', 49)
        first = self.frame('dock-clearance', 49)
        obscured = self.frame('dock-clearance', 54)
        third = self.frame('dock-clearance', 59)
        for pair in (success, first, obscured, third):
            print(pair[0].parent.parent.parent.parent.name, pair[0].name,
                  'off', self.run_probe(*pair, False), 'on', self.run_probe(*pair, True))
        self.assertTrue(self.run_probe(*success, False)['found'])
        self.assertTrue(self.run_probe(*success, True)['found'])
        self.assertEqual(self.run_probe(*first, False)['count'], 1)
        self.assertEqual(self.run_probe(*first, True)['count'], 5)
        self.assertTrue(self.run_probe(*first, True)['found'])
        self.assertFalse(self.run_probe(*obscured, True)['found'])
        self.assertEqual(self.run_probe(*third, False)['count'], 0)
        self.assertEqual(self.run_probe(*third, True)['count'], 6)
        self.assertTrue(self.run_probe(*third, True)['found'])

    def test_disabled_matches_unchanged_detector_on_recorded_frames(self):
        for run, frames in (('dock-survey-elevation', range(49, 52)),
                            ('dock-clearance', range(49, 64))):
            for frame in frames:
                pair = self.frame(run, frame)
                self.assertEqual(self.run_probe(*pair, False),
                                 self.run_probe(*pair, False, baseline=True), pair[0])
                self.assertEqual(self.run_probe(*pair, 'default'),
                                 self.run_probe(*pair, False, baseline=True), pair[0])

    def test_blank_and_two_partial_components_do_not_make_pose(self):
        _, camera = self.frame('dock-clearance', 59)
        data = bytearray(640 * 480 * 3); path = self.root / 'synthetic.rgb'
        path.write_bytes(data)
        self.assertFalse(self.run_probe(path, camera, True)['found'])
        for x in (141, 229):
            for dx in range(3):
                i = (369 * 640 + x + dx) * 3; data[i:i + 3] = bytes((220, 0, 220))
        path.write_bytes(data)
        partial = self.run_probe(path, camera, True)
        self.assertEqual(partial['count'], 2)
        self.assertFalse(partial['found'])
        # Several patches on one row cannot satisfy the full box geometry.
        for x in (155, 185, 205, 243):
            for dx in range(3):
                i = (369 * 640 + x + dx) * 3; data[i:i + 3] = bytes((220, 0, 220))
        path.write_bytes(data)
        self.assertFalse(self.run_probe(path, camera, True)['found'])

    def test_invalid_opt_in_rejected(self):
        env = dict(os.environ, PUPPYBOT_DOCK_SMALL_COMPONENTS='invalid')
        result = subprocess.run([str(self.native)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 2)
        self.assertIn('Invalid small component option', result.stderr)

    def test_matching_marker_colours_without_box_can_spoof_pose(self):
        # Synthetic adversarial scene: no box, only the six three-pixel
        # components at their recorded pixel coordinates. This is an explicit
        # false positive, not a claim about natural negative-scene rates.
        _, camera = self.frame('dock-clearance', 59)
        data = bytearray(640 * 480 * 3); path = self.root / 'spoof.rgb'
        for x, y in ((140, 369), (227, 369), (156, 385), (235, 385), (205, 398), (242, 398)):
            for dx in range(3):
                i = (y * 640 + x + dx) * 3; data[i:i + 3] = bytes((220, 0, 220))
        path.write_bytes(data)
        self.assertFalse(self.run_probe(path, camera, False)['found'])
        self.assertTrue(self.run_probe(path, camera, True)['found'])
        # Four-pixel lookalikes also expose the existing detector's broader
        # limitation; this is not specific to the candidate threshold.
        for x, y in ((140, 369), (227, 369), (156, 385), (235, 385), (205, 398), (242, 398)):
            i = (y * 640 + x + 3) * 3; data[i:i + 3] = bytes((220, 0, 220))
        path.write_bytes(data)
        self.assertTrue(self.run_probe(path, camera, False)['found'])

    def test_transform_requires_exact_source(self):
        dock = (ARCHIVE / 'source/sim/dock-vision.flex').read_text()
        main = (ARCHIVE / 'source/sim/main.flex').read_text()
        candidate = transform.transform(dock, main)
        self.assertIn('global ps_dock_small_components = 0;', candidate[0])
        with self.assertRaises(ValueError):
            transform.transform(*candidate)


if __name__ == '__main__':
    unittest.main()
