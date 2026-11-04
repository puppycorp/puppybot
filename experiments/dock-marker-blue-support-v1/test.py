#!/usr/bin/env python3
"""Replay saved and synthetic marker images through a copied native detector."""
import importlib.util
import hashlib
import json
import shutil
import subprocess
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prior = load('blue_support_prior_tests', ROOT / 'experiments/dock-rim-raster-audit-v1/test.py')
transform = load('blue_support_transform', HERE / 'transform.py')


class BlueSupportTests(prior.DetectorTests):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ungated = cls.root / 'ungated'
        shutil.copyfile(cls.probe, cls.ungated)
        cls.ungated.chmod(0o755)
        source = cls.root / 'source'
        dock = source / 'sim/dock-vision.flex'; main = source / 'sim/main.flex'
        original_dock = (prior.ARCHIVE / 'source/sim/dock-vision.flex').read_text()
        original_main = (prior.ARCHIVE / 'source/sim/main.flex').read_text()
        candidate_dock, candidate_main = transform.transform(original_dock, original_main)
        dock.write_text(candidate_dock)
        main.write_text(transform.BASE.once(candidate_main, 'fn main(argc, argv) {',
                                             'fn rim_original_main(argc, argv) {') + '\n' +
                        (prior.HERE / 'probe.flex').read_text())
        result = subprocess.run([str(prior.COMPILER), str(main), '-o', str(cls.probe)], cwd=ROOT,
                                capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        main.write_text(transform.BASE.once(candidate_main, 'fn main(argc, argv) {',
                                             'fn rim_original_main(argc, argv) {') + '\n' +
                        (HERE / 'sequence-probe.flex').read_text())
        cls.sequence = cls.root / 'sequence-probe'
        result = subprocess.run([str(prior.COMPILER), str(main), '-o', str(cls.sequence)], cwd=ROOT,
                                capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)

    def test_blank_and_two_partial_components_do_not_make_pose(self):
        _, camera = self.frame('dock-clearance', 59)
        data = bytearray(640 * 480 * 3); path = self.root / 'partial-black.rgb'
        path.write_bytes(data)
        self.assertFalse(self.run_probe(path, camera, True)['found'])
        for x in (141, 229):
            for dx in range(3):
                i = (369 * 640 + x + dx) * 3; data[i:i + 3] = bytes((220, 0, 220))
        path.write_bytes(data)
        partial = self.run_probe(path, camera, True)
        self.assertEqual(partial['count'], 0)
        self.assertFalse(partial['found'])

    def test_matching_marker_colours_without_box_can_spoof_pose(self):
        _, camera = self.frame('dock-clearance', 59)
        black = bytearray(640 * 480 * 3); path = self.root / 'colour-context-spoof.rgb'
        positions = ((140, 369), (227, 369), (156, 385), (235, 385), (205, 398), (242, 398))
        for x, y in positions:
            for dx in range(3):
                i = (y * 640 + x + dx) * 3; black[i:i + 3] = bytes((220, 0, 220))
        path.write_bytes(black)
        self.assertFalse(self.run_probe(path, camera, True)['found'])
        self.assertEqual(self.run_probe(path, camera, True)['count'], 0)
        # Solid blue fields around all six markers have no local boundary.
        for x, y in positions:
            for dy in range(-5, 6):
                for dx in range(-5, 6):
                    if dy == 0 and 0 <= dx < 3: continue
                    i = ((y + dy) * 640 + x + dx) * 3
                    black[i:i + 3] = bytes((50, 81, 102))
        path.write_bytes(black)
        self.assertFalse(self.run_probe(path, camera, True)['found'])
        # Artificial blue/nonblue boundaries around the same markers can
        # still fit even though the image contains no box.
        for x, y in positions:
            for dy in range(1, 6):
                for dx in range(-5, 6):
                    i = ((y + dy) * 640 + x + dx) * 3
                    black[i:i + 3] = b'\0\0\0'
        path.write_bytes(black)
        self.assertTrue(self.run_probe(path, camera, True)['found'])

    def test_positive_frames_lose_pose_without_blue_context(self):
        # Preserve magenta marker pixels and replace blue context with black.
        # This shows the experimental gate is active on real recorded input.
        for pair in (self.frame('dock-clearance', 49), self.frame('dock-clearance', 59)):
            data = bytearray(pair[0].read_bytes())
            for i in range(0, len(data), 3):
                r, g, b = data[i:i + 3]
                if b > 35 and b > g + 10 and g > r + 10:
                    data[i:i + 3] = b'\0\0\0'
            path = self.root / 'blue-removed.rgb'; path.write_bytes(data)
            self.assertFalse(self.run_probe(path, pair[1], True)['found'])

    def test_barrier_survey_views(self):
        receipt = json.loads((HERE / 'barrier-inputs.json').read_text())
        self.assertEqual(receipt['schema'], 'puppybot.barrier-survey-local-inputs.v1')
        files = receipt['files']; self.assertEqual(len(files), 90)
        counts = {}; ungated_counts = {}
        for name in sorted(path for path in files if path.endswith('.rgb')):
            image = Path(name); camera = image.with_suffix('.sensor.camera.json')
            for path in (image, camera):
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), files[str(path)])
            result = self.run_probe(image, camera, True)
            arm = image.parent.parent.name
            counts.setdefault(arm, []).append((result['found'], result['count']))
            if arm == 'candidate-search' and result['found']:
                print('positive barrier image', image.name, json.loads(camera.read_text())['frameId'],
                      hashlib.sha256(image.read_bytes()).hexdigest(), result['position'])
            guarded_probe = self.probe
            try:
                self.probe = self.ungated
                ungated = self.run_probe(image, camera, True)
            finally:
                self.probe = guarded_probe
            ungated_counts.setdefault(arm, []).append((ungated['found'], ungated['count']))
        print('barrier survey candidate', counts)
        print('barrier survey ungated', ungated_counts)
        self.assertEqual(sorted(map(len, counts.values())), [15, 15, 15])
        self.assertEqual({arm: sum(found for found, _ in values) for arm, values in counts.items()},
                         {'baseline': 0, 'candidate-disabled': 0, 'candidate-search': 5})

    def test_barrier_consecutive_frames_one_detector_state(self):
        import struct
        base = prior.RUNS / 'dock-barrier-rendered-monitored-v1/trial/candidate-search'
        images = [base / 'diagnostic' / f'survey-{n}.rgb' for n in range(60, 65)]
        cameras = [json.loads(path.with_suffix('.sensor.camera.json').read_text()) for path in images]
        self.assertEqual([c['frameId'] for c in cameras], [11477, 11487, 11497, 11507, 11517])
        fields = ('eyeM', 'forward', 'right', 'down')
        self.assertTrue(all([c[k] for k in fields] == [cameras[0][k] for k in fields] for c in cameras))
        trace = base / 'run/trace.jsonl'
        with trace.open('rb') as stream:
            trace_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
        receipt = json.loads((HERE / 'barrier-inputs.json').read_text())
        self.assertEqual(trace_hash, receipt['candidateTraceSHA256'])
        wanted = {c['frameId'] for c in cameras}; observed = {}
        with trace.open() as stream:
            for line in stream:
                row = json.loads(line); tick = row.get('step')
                if tick in wanted:
                    self.assertNotIn(tick, observed)
                    observed[tick] = (row['camera']['armSettled'], row['ticks'])
        self.assertEqual(set(observed), wanted)
        self.assertTrue(all(value == (True, [1467, 257, 3027, 2967]) for value in observed.values()))
        sidecar = self.root / 'sequence-camera.bin'
        sidecar.write_bytes(struct.pack('<12d', *sum((cameras[0][k] for k in fields), [])))
        result = subprocess.run([str(self.sequence), *map(str, images), str(sidecar)], cwd=ROOT,
                                capture_output=True, text=True, timeout=15, check=True)
        rows = json.loads(result.stdout)
        self.assertEqual([row['found'] for row in rows], [1] * 5)
        self.assertEqual([row['stable'] for row in rows], [1, 2, 3, 4, 5])
        self.assertTrue(all(row['position'] == rows[0]['position'] for row in rows))
        print('consecutive detector rows', rows)


if __name__ == '__main__': unittest.main()
