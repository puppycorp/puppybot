#!/usr/bin/env python3
"""Scratch-only Btrfs comparison with native aggregate and teacher mask."""
import importlib.util
import json
import os
import random
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
S = ROOT / 'datasets/visual-control/chase-v1/levels'
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
AGG = P / '../../levels-v1/map-aggregate'
spec = importlib.util.spec_from_file_location('overlay', S / 'heading-reflink-overlay.py')
overlay = importlib.util.module_from_spec(spec); spec.loader.exec_module(overlay)
spec = importlib.util.spec_from_file_location('pair_verify', S / 'verify-heading-overlay-pair.py')
pair_verify = importlib.util.module_from_spec(spec); spec.loader.exec_module(pair_verify)


def physical_map(path):
    text = subprocess.run(['filefrag', '-v', str(path)], capture_output=True, text=True, check=True).stdout
    ranges = []
    for line in text.splitlines():
        match = re.match(r'^\s*\d+:\s*(\d+)\.\.\s*(\d+):\s*(\d+)\.\.\s*(\d+):', line)
        if not match: continue
        a, b, c, d = map(int, match.groups())
        if c <= 0 or b - a != d - c: raise ValueError('physical extent mapping unavailable')
        if ranges and ranges[-1][1] + 1 == a and ranges[-1][3] + 1 == c:
            ranges[-1] = (ranges[-1][0], b, ranges[-1][2], d)
        else:
            ranges.append((a, b, c, d))
    if not ranges: raise ValueError('no physical extents')
    return ranges


def shard(path, images, student, maps):
    path.mkdir(); data = path / 'data.bin'; map_file = path / 'map.bin'
    with data.open('wb') as f:
        f.write(b'PVDATA01' + struct.pack('<qqq', 2, 1, 300))
        for episode in range(2):
            f.write(images[episode]); rows = bytearray()
            for t in range(300):
                speed = 1.0 if t % 2 else -1.0
                rows.extend(struct.pack('<11f', 0, 0, 0, 0, 0, 0, 0, 0, speed, 0, 1))
            f.write(rows)
        f.flush(); os.fsync(f.fileno())
    with map_file.open('wb') as f:
        f.write(b'PVMAP001' + struct.pack('<qqq', 2, 1, 300)); f.write(maps[0]); f.write(maps[1]); f.flush(); os.fsync(f.fileno())
    report = {'complete': True, 'studentDriven': student, 'episodes': 2, 'trainingEpisodes': 1,
              'sequenceLength': 300, 'dataSHA256': overlay.digest(data), 'mapSHA256': overlay.digest(map_file)}
    (path / 'report.json').write_text(json.dumps(report))
    if not student:
        for i in range(2):
            game = path / f'expert-{i}'; (game / 'scene').mkdir(parents=True)
            (game / 'scene/case.json').write_text(json.dumps({'container': {'position': [-2, 0, 0]}}))
            (game / 'chase.jsonl').write_text(json.dumps({'event': 'start', 'robot': [0, 0, 0]}) + '\n')
            rows = [{'action': [0, 1 if t % 2 else -1], 'state': {'pose': [0, 0, 0], 'ball': [2, 0, 0]}} for t in range(300)]
            (game / 'decisions.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))


def native(out, teacher, student):
    subprocess.run([str(AGG), str(out), '300', '0', str(teacher / 'data.bin'), str(student / 'data.bin')],
                   cwd=ROOT, check=True, stdout=subprocess.DEVNULL, timeout=60)
    subprocess.run([sys.executable, '-I', str(S / 'mask-stuck.py'), str(out / 'data.bin'), '--teacher-only', str(teacher), str(student)],
                   cwd=ROOT, check=True, stdout=subprocess.DEVNULL, timeout=60)


class OverlayTest(unittest.TestCase):
    def test_native_equivalence_mask_and_source_extents(self):
        with tempfile.TemporaryDirectory(prefix='.heading-overlay-fixture-', dir=P) as tmp:
            d = Path(tmp); rng = random.Random(31415); image_size = 300 * 21168; map_size = 300 * 144
            imgs = [rng.randbytes(image_size) for _ in range(5)]
            maps = [rng.randbytes(map_size) for _ in range(5)]
            teacher, control, treatment = d / 'teacher', d / 'control', d / 'treatment'
            shard(teacher, imgs[:2], False, maps[:2]); shard(control, imgs[2:4], True, maps[2:4])
            shard(treatment, [imgs[4], imgs[3]], True, [maps[4], maps[3]])
            base, expected, output = d / 'base', d / 'native-treatment', d / 'overlay'
            native(base, teacher, control); native(expected, teacher, treatment)
            with (base / 'data.bin').open('rb') as f:
                f.seek(32 + 300 * 21168 + 40); self.assertEqual(struct.unpack('<f', f.read(4))[0], 0)
            before_hash = overlay.digest(base / 'data.bin'); before_extents = physical_map(base / 'data.bin')
            report = overlay.overlay(base, [treatment], output, 1, 3, 0, validation_peer=base)
            self.assertEqual(report['unchangedGames'], 2); self.assertEqual(report['pairedValidation'], 'byte_equal_at_check')
            self.assertEqual((output / 'data.bin').read_bytes(), (expected / 'data.bin').read_bytes())
            self.assertEqual((output / 'map.bin').read_bytes(), (expected / 'map.bin').read_bytes())
            self.assertEqual(overlay.digest(base / 'data.bin'), before_hash)
            self.assertEqual(physical_map(base / 'data.bin'), before_extents)
            manifest = json.loads((output / 'manifest.json').read_text())
            self.assertEqual([r['target'] for r in manifest['slotMapping']], [1, 3])
            with self.assertRaises(ValueError): overlay.overlay(base, [treatment], output, 1, 3, 0)
            paired_control = d / 'paired-control'
            overlay.overlay(base, [control], paired_control, 1, 3, 0)
            plan = {'totalGames': 4, 'fittingGames': 2, 'fitOffset': 1, 'validationOffset': 3, 'unaffectedGames': 2}
            paired = pair_verify.check_pair(base, paired_control, output, [control], [treatment], plan, 2, 1)
            self.assertEqual(paired['aggregateValidation']['validationGames'], 2)
            forged_plan = dict(plan, replacedSlots=[0, 3])
            with self.assertRaises(ValueError): pair_verify.check_pair(base, paired_control, output, [control], [treatment], forged_plan, 2, 1)
            receipt = d / 'pair-ready.json'; pair_verify.publish_new(receipt, paired)
            with self.assertRaises(ValueError): pair_verify.publish_new(receipt, paired)
            output_manifest = output / 'manifest.json'; original_manifest = output_manifest.read_bytes()
            forged = json.loads(original_manifest); forged['slotMapping'][0]['target'] = 0
            output_manifest.write_text(json.dumps(forged))
            with self.assertRaises(ValueError): pair_verify.check_pair(base, paired_control, output, [control], [treatment], plan, 2, 1)
            output_manifest.write_bytes(original_manifest)
            failed = d / 'failed'
            with mock.patch.object(overlay, 'audit', side_effect=ValueError('injected audit failure')):
                with self.assertRaises(RuntimeError): overlay.overlay(base, [treatment], failed, 1, 3, 0)
            self.assertFalse(failed.exists()); self.assertTrue(list(d.glob('.failed.partial-*')))
            self.assertEqual(overlay.digest(base / 'data.bin'), before_hash)
            race = d / 'race'
            class RefuseRename:
                def renameat2(self, *args): return -1
            with mock.patch.object(overlay.ctypes, 'CDLL', return_value=RefuseRename()):
                with self.assertRaises(RuntimeError): overlay.overlay(base, [treatment], race, 1, 3, 0)
            self.assertFalse(race.exists()); self.assertTrue(list(d.glob('.race.partial-*')))
            self.assertEqual(overlay.digest(base / 'data.bin'), before_hash)
            # Hardlink creation changes the source inode metadata, so run this
            # negative fixture after the manifest-bound source comparisons.
            linked = d / 'linked'; linked.mkdir()
            os.link(treatment / 'data.bin', linked / 'data.bin')
            shutil.copyfile(treatment / 'map.bin', linked / 'map.bin'); shutil.copyfile(treatment / 'report.json', linked / 'report.json')
            with self.assertRaises(ValueError): overlay.overlay(base, [treatment, linked], d / 'hardlink', 0, 2, 0)
            self.assertFalse((d / 'hardlink').exists())


if __name__ == '__main__': unittest.main()
