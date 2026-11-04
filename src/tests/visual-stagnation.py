#!/usr/bin/env python3
"""CPU-only controls for the experimental image-only stagnation detector."""
import importlib.util
import hashlib
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

path = Path(__file__).resolve().parents[2] / 'datasets/visual-control/chase-v1/levels/visual-stagnation.py'
spec = importlib.util.spec_from_file_location('visual_stagnation', path)
detector = importlib.util.module_from_spec(spec); spec.loader.exec_module(detector)
history_spec = importlib.util.spec_from_file_location('visual_stagnation_history', path.with_name('visual-stagnation-historical-audit.py'))
history = importlib.util.module_from_spec(history_spec); history_spec.loader.exec_module(history)


class StagnationTest(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(27)
        self.image = rng.integers(40, 180, size=(3, 84, 84), dtype=np.uint8)
        self.speeds = [1.0] * 9
        self.ticks = list(range(0, 100, 10))

    def check(self, images, expected, speeds=None, ticks=None):
        result = detector.classify(np.stack(images), speeds or self.speeds, ticks or self.ticks)
        self.assertEqual(result['state'], expected, result)

    def test_static_and_additive_lighting(self):
        self.check([self.image.copy() for _ in range(10)], 'visual_stagnation')
        self.check([(self.image + i).astype(np.uint8) for i in range(10)], 'visual_stagnation')

    def test_translation_and_rotation_are_not_stagnant(self):
        self.check([np.roll(self.image, i, axis=2) for i in range(10)], 'no_evidence')
        self.check([np.rot90(self.image, i % 4, axes=(1, 2)) for i in range(10)], 'no_evidence')

    def test_local_scene_change_is_conservatively_not_stagnant(self):
        images = [self.image.copy() for _ in range(10)]
        for i in range(1, 10):
            images[i][:, 30:38, 30:38] = 240 if i % 2 else 0
        self.check(images, 'no_evidence')

    def test_periodic_texture_exposes_aliasing_limit(self):
        # A translating periodic pattern can render identical images. The
        # detector necessarily flags the images; that is not proof of a stop.
        stripe = np.tile(np.array([50] * 3 + [170] * 4, dtype=np.uint8), 12)
        image = np.broadcast_to(stripe, (3, 84, 84)).copy()
        self.check([np.roll(image, i * 7, axis=2) for i in range(10)], 'visual_stagnation')

    def test_low_texture_is_unreliable_not_a_recovery_trigger(self):
        self.check([np.full((3, 84, 84), 100, np.uint8) for _ in range(10)], 'unreliable_texture')

    def test_stopped_command_and_timing_gap_are_ineligible(self):
        self.check([self.image] * 10, 'not_continuously_commanded', speeds=[1.0] * 4 + [0.0] + [1.0] * 4)
        self.check([self.image] * 10, 'unreliable_timing', ticks=[0, 10, 20, 30, 40, 60, 70, 80, 90, 100])

    def test_invalid_or_nonfinite_data_is_rejected(self):
        with self.assertRaises(ValueError):
            detector.classify(np.zeros((10, 84, 84), dtype=np.uint8), self.speeds, self.ticks)
        with self.assertRaises(ValueError):
            detector.classify(np.stack([self.image] * 10), [1.0] * 8 + [float('nan')], self.ticks)

    def test_loader_requires_fresh_camera_and_applied_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp); actors = run / 'actors'; actors.mkdir()
            rows = []
            for seq in range(1, 12):
                tick = 100 + 10 * (seq - 1)
                rows.append({'sequence': seq, 'owner': 0, 'ack': 0 if seq == 1 else 1,
                             'imageValid': True, 'cameraDriving': True, 'cameraStill': True,
                             'cameraFrame': tick, 'totalSteps': tick,
                             'driveCommand': [0, 0, 90] if seq == 1 else [60, 60, 90]})
                if seq <= 10:
                    (actors / f'actor-{seq}.rgb').write_bytes(self.image.tobytes())
                    (actors / f'actor-{seq}.action').write_bytes(struct.pack('<2f', 0, 1))
            journal = run / 'physical-agent.jsonl'
            def save(): journal.write_text(''.join(json.dumps(row) + '\n' for row in rows))
            save(); self.assertEqual(len(detector.load(run)[1]), 10)
            rows[5]['ack'] = 2; save()
            with self.assertRaises(ValueError): detector.load(run)
            rows[5]['ack'] = 1; rows[2]['cameraStill'] = False; save()
            with self.assertRaises(ValueError): detector.load(run)
            rows[2]['cameraStill'] = True; rows[5]['driveCommand'] = [0, 0, 90]; save()
            with self.assertRaises(ValueError): detector.load(run)

    def test_post_run_truth_audit_rejects_stale_actor_or_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp); actors = run / 'actors'; actors.mkdir(); rows = []
            for seq in range(1, 12):
                tick = 10 * (seq - 1)
                rows.append({'sequence': seq, 'owner': 0, 'ack': 0 if seq == 1 else 1,
                             'imageValid': True, 'cameraDriving': True, 'cameraStill': True,
                             'cameraFrame': tick, 'totalSteps': tick,
                             'driveCommand': [0, 0, 90] if seq == 1 else [60, 60, 90]})
                if seq <= 10:
                    (actors / f'actor-{seq}.rgb').write_bytes(self.image.tobytes())
                    (actors / f'actor-{seq}.action').write_bytes(struct.pack('<2f', 0, 1))
            (run / 'physical-agent.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
            trace = run / 'trace.jsonl'
            trace.write_text(''.join(json.dumps({'totalSteps': tick, 'pose': [0, 0, 0]}) + '\n' for tick in range(91)))
            (run / 'result.json').write_text(json.dumps({'traceSHA256': hashlib.sha256(trace.read_bytes()).hexdigest()}))
            report = run / 'detector.json'
            report.write_text(subprocess.check_output([sys.executable, '-I', str(path), str(run)], text=True))
            auditor = path.with_name('visual-stagnation-truth-audit.py')
            output = json.loads(subprocess.check_output([sys.executable, '-I', str(auditor), str(run), str(report)], text=True))
            self.assertEqual(output['counts']['stagnantAndStationary'], 1)
            altered = json.loads(report.read_text()); altered['windows'][0]['state'] = 'no_evidence'
            report.write_text(json.dumps(altered))
            self.assertNotEqual(subprocess.run([sys.executable, '-I', str(auditor), str(run), str(report)], capture_output=True).returncode, 0)
            altered['windows'][0]['state'] = 'visual_stagnation'; report.write_text(json.dumps(altered))
            (actors / 'actor-1.action').write_bytes(struct.pack('<2f', 0, -1))
            self.assertNotEqual(subprocess.run([sys.executable, '-I', str(auditor), str(run), str(report)], capture_output=True).returncode, 0)
            (actors / 'actor-1.action').write_bytes(struct.pack('<2f', 0, 1))
            bad = ''.join(json.dumps({'totalSteps': tick, 'pose': [float('nan') if tick == 40 else 0, 0, 0]}) + '\n' for tick in range(91))
            trace.write_text(bad); (run / 'result.json').write_text(json.dumps({'traceSHA256': hashlib.sha256(trace.read_bytes()).hexdigest()}))
            self.assertNotEqual(subprocess.run([sys.executable, '-I', str(auditor), str(run), str(report)], capture_output=True).returncode, 0)

    def test_retrospective_stationary_delay_and_missing_tick(self):
        poses = {tick: [max(0, 20 - tick) * .02, 0, 0] for tick in range(111)}
        self.assertEqual(history.stationary_delay_ticks(poses, 0, 110), 90)
        del poses[50]
        with self.assertRaises(ValueError): history.stationary_delay_ticks(poses, 0, 110)


if __name__ == '__main__':
    unittest.main()
