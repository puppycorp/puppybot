#!/usr/bin/env python3
"""Small Btrfs fixtures for sequential pair creation and disk reservation."""
import hashlib
import importlib.util
import json
import os
import shutil
import struct
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location('parent_pair_build', HERE / 'build.py')
build = importlib.util.module_from_spec(spec); spec.loader.exec_module(build)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class PairTest(unittest.TestCase):
    def setUp(self):
        # FICLONE must be tested on the same filesystem as project outputs.
        self.temp = tempfile.TemporaryDirectory(prefix='.parent-pair-test-', dir=ROOT)
        self.root = Path(self.temp.name); self.image = 5; self.length = 3; self.map_row = 2
        self.base = self.root / 'base'; self.base.mkdir()
        self.shards = [self.root / 'shard-0', self.root / 'shard-1']
        old = []
        for episode in range(4):
            images = bytes([episode + 1]) * self.image * self.length
            rows = b''.join(struct.pack('<7f2f4f', *([0] * 7), 0, 1, 0, 1, 1, 0) + struct.pack('<f', 1)
                            for _ in range(self.length))
            self.assertEqual(len(rows), self.length * 56)
            old.append(images + rows)
        (self.base / 'data.bin').write_bytes(struct.pack('<8s3q', b'PVDATA04', 4, 2, 3) + b''.join(old))
        (self.base / 'map.bin').write_bytes(struct.pack('<8s3q', b'PVMAP001', 4, 2, 3) +
                                            b''.join(bytes([episode % 3]) * self.length * self.map_row for episode in range(4)))
        self.selected = [(0, 2, 7820010), (0, 1, 7820025)]
        for shard, selected in zip(self.shards, self.selected):
            shard.mkdir(); game = shard / 'expert-0'; game.mkdir()
            records = []
            for episode in range(2):
                images = bytes([10 + episode]) * self.image * self.length
                rows = b''.join(struct.pack('<11f', *([0] * 7), .6, 1, 0, 1) for _ in range(self.length))
                records.append(images + rows)
            (shard / 'data.bin').write_bytes(struct.pack('<8s3q', b'PVDATA01', 2, 1, 3) + b''.join(records))
            (shard / 'map.bin').write_bytes(struct.pack('<8s3q', b'PVMAP001', 2, 1, 3) +
                                            bytes(range(12)))
            (game / 'decisions.jsonl').write_text(''.join(json.dumps({'action': [0, 1]}) + '\n' for _ in range(3)))
            (game / 'result.json').write_text(json.dumps({'seed': selected[2], 'steps': self.length}))
            (game / 'chase.jsonl').write_text(json.dumps({'event': 'start', 'step': 0}) + '\n' +
                                               json.dumps({'event': 'delivery', 'step': selected[1]}) + '\n')
        self.kwargs = {'old_count': 4, 'old_fit': 2, 'length': self.length, 'image': self.image,
                       'raw_row': 44, 'row': 56, 'map_row': self.map_row, 'minimum': 0}

    def tearDown(self):
        self.temp.cleanup()

    def run_pair(self, output):
        return build.create_pair(self.base / 'data.bin', self.base / 'map.bin', self.shards,
                                 output, self.selected, **self.kwargs)

    def test_pair_preserves_baseline_and_changes_only_prefix_labels(self):
        source_hashes = [sha(self.base / name) for name in ('data.bin', 'map.bin')]
        output = self.root / 'pair'; report = self.run_pair(output)
        self.assertEqual(report['treatment']['labelChanges'], 3)
        self.assertEqual([sha(self.base / name) for name in ('data.bin', 'map.bin')], source_hashes)
        control = (output / 'control/data.bin').read_bytes(); treatment = (output / 'treatment/data.bin').read_bytes()
        self.assertEqual(control[:32], struct.pack('<8s3q', b'PVDATA04', 6, 4, 3))
        self.assertEqual((output / 'control/map.bin').read_bytes(), (output / 'treatment/map.bin').read_bytes())
        stride = self.length * (self.image + 56); differences = []
        for index, (a, b) in enumerate(zip(control, treatment)):
            if a != b:
                differences.append(index)
        allowed = set()
        for episode, cutoff in ((2, 2), (3, 1)):
            for step in range(cutoff):
                offset = 32 + episode * stride + self.length * self.image + step * 56 + 28
                allowed.update(range(offset, offset + 8))
        self.assertTrue(differences); self.assertTrue(set(differences) <= allowed)
        self.assertNotEqual(os.stat(self.base / 'data.bin').st_ino, os.stat(output / 'control/data.bin').st_ino)

    def test_second_reservation_failure_keeps_control_and_no_treatment(self):
        output = self.root / 'pair'; calls = []
        def available(path):
            after_first = (output / 'control/data.bin').exists()
            calls.append(after_first)
            return types.SimpleNamespace(free=(37 if after_first else 40) * build.GIB)
        with mock.patch.object(build.shutil, 'disk_usage', side_effect=available):
            with self.assertRaisesRegex(ValueError, 'insufficient free space'):
                self.run_pair(output)
        self.assertIn(False, calls); self.assertIn(True, calls)
        self.assertTrue((output / 'control/data.bin').is_file())
        self.assertFalse((output / 'treatment').exists())

    def test_reservation_includes_full_unshared_one_output(self):
        output = self.root / 'new'
        # 7 GiB logical size needs 34 + 7 GiB even on a reflink filesystem.
        with mock.patch.object(build.shutil, 'disk_usage', return_value=types.SimpleNamespace(free=40 * build.GIB)):
            with self.assertRaisesRegex(ValueError, 'insufficient free space'):
                build.reservation(output, 7, 1, build.GIB - 64, 0, 0)
        with mock.patch.object(build.shutil, 'disk_usage', return_value=types.SimpleNamespace(free=42 * build.GIB)):
            result = build.reservation(output, 7, 1, build.GIB - 64, 0, 0)
        self.assertGreater(result['minimumFreeBytes'], 40 * build.GIB)

    def test_existing_output_companion_alias_and_source_nesting_rejected(self):
        output = self.root / 'pair'; output.mkdir()
        with self.assertRaises(FileExistsError): self.run_pair(output)
        with self.assertRaisesRegex(ValueError, 'selection'):
            build.selected_inputs(self.shards, [(1, 2, 1), (0, 1, 2)], 3, 5, 44, 2)
        with self.assertRaisesRegex(ValueError, 'episode count'):
            build.selected_inputs([self.shards[0]] * 2, self.selected, 3, 5, 44, 2)
        with self.assertRaisesRegex(ValueError, 'inside source'):
            self.run_pair(self.base / 'nested')

    def test_real_writer_outputs_pass_independent_native_boundary_verifier(self):
        spec = importlib.util.spec_from_file_location('paired_verify_fixture', HERE / 'verify-test.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        fixture = module.PairedVerificationTest('test_matching_pair_preserves_baseline_and_fit_split')
        fixture.setUp()
        try:
            baseline = self.root / 'native-base'; baseline.mkdir()
            shutil.copyfile(fixture.base, baseline / 'data.bin'); shutil.copyfile(fixture.base_map, baseline / 'map.bin')
            shards = []; inputs = []
            for index, original in enumerate(fixture.sources):
                shard = self.root / f'native-shard-{index}'; shard.mkdir()
                game = shard / 'expert-0'; game.mkdir()
                for key, target in (('data', shard / 'data.bin'), ('map', shard / 'map.bin'),
                                    ('actor', game / 'actor-boundary.bin'), ('boundary', game / 'map-label-boundary.bin'),
                                    ('decisions', game / 'decisions.jsonl'), ('events', game / 'chase.jsonl')):
                    shutil.copyfile(original[key], target)
                (game / 'result.json').write_text(json.dumps({'seed': original['seed'], 'steps': module.LENGTH}))
                shards.append(shard)
                inputs.append({'seed': original['seed'], 'episode': 0, 'cutoff': module.CUTOFF,
                               'data': shard / 'data.bin', 'map': shard / 'map.bin',
                               'actor': game / 'actor-boundary.bin', 'boundary': game / 'map-label-boundary.bin',
                               'decisions': game / 'decisions.jsonl', 'events': game / 'chase.jsonl'})
            output = self.root / 'integrated'
            build.create_pair(baseline / 'data.bin', baseline / 'map.bin', shards, output,
                              [(0, module.CUTOFF, 100), (0, module.CUTOFF, 101)], old_count=module.OLD,
                              old_fit=module.FIT, length=module.LENGTH, image=module.IMAGE, map_row=module.MAP,
                              minimum=0)
            report = module.verify.verify(baseline / 'data.bin', baseline / 'map.bin', inputs,
                                          output / 'control/data.bin', output / 'control/map.bin',
                                          output / 'treatment/data.bin', output / 'treatment/map.bin',
                                          old_count=module.OLD, old_fit=module.FIT, length=module.LENGTH,
                                          image=module.IMAGE, map_row=module.MAP, memory=module.MEMORY,
                                          expected_sources=((100, 0, 2), (101, 0, 2)), aux_mask_begin=1)
            self.assertEqual(report['prefixLabelDifferences'], [1, 1])
            self.assertFalse(report['trainingAuthorized'])
        finally:
            fixture.tearDown()


if __name__ == '__main__':
    unittest.main()
