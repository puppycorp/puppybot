#!/usr/bin/env python3
"""CPU-only tests for exact heading-experiment data/map comparisons."""
import hashlib
import importlib.util
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'datasets/visual-control/chase-v1/levels/audit-heading-pairs.py'
spec = importlib.util.spec_from_file_location('heading_pairs', SCRIPT)
audit = importlib.util.module_from_spec(spec); spec.loader.exec_module(audit)


def make_pair(root, magic, games, fitting, horizon):
    result = []
    for side in ('left', 'right'):
        directory = root / side; directory.mkdir()
        for name, file_magic, width in (('data.bin', magic, 21212 if magic == b'PVDATA01' else 21224),
                                        ('map.bin', b'PVMAP001', 144)):
            with (directory / name).open('wb') as stream:
                stream.write(file_magic + struct.pack('<3q', games, fitting, horizon))
                stream.truncate(32 + games * horizon * width)
        result.append(directory)
    return result


def mutate(path, offset, data=b'X'):
    with path.open('r+b') as stream:
        stream.seek(offset); stream.write(data)


class HeadingPairsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.patch = mock.patch.object(audit, 'HORIZON', 3); self.patch.start(); self.addCleanup(self.patch.stop)

    def test_selected_shard_games_and_unspecified_differences(self):
        left, right = make_pair(self.root, b'PVDATA01', 4, 2, 3)
        mutate(right / 'data.bin', 32 + 3 * 21212 + 1)
        out = audit.compare_shard(left, right, [2, 3], 4, 2)
        self.assertEqual([r['split'] for r in out['episodes']], ['validation', 'validation'])
        self.assertEqual(out['episodes'][0]['dataSHA256'], hashlib.sha256(bytes(3 * 21212)).hexdigest())
        for name, width in (('data.bin', 21212), ('map.bin', 144)):
            mutate(right / name, 32 + 2 * 3 * width + 5)
            with self.subTest(name=name), self.assertRaises(ValueError):
                audit.compare_shard(left, right, [2, 3], 4, 2)
            mutate(left / name, 32 + 2 * 3 * width + 5)

    def test_complete_validation_but_not_fitting(self):
        left, right = make_pair(self.root, b'PVDATA04', 4, 2, 3)
        mutate(right / 'data.bin', 32 + 7)
        self.assertEqual(audit.compare_validation(left, right, 4, 2)['validationGames'], 2)
        for index in (2, 3):
            for name, width in (('data.bin', 21224), ('map.bin', 144)):
                offset = 32 + index * 3 * width + 2
                mutate(right / name, offset)
                with self.subTest(index=index, name=name), self.assertRaises(ValueError):
                    audit.compare_validation(left, right, 4, 2)
                mutate(left / name, offset)

    def test_wrong_magic_dimensions_horizon_and_trailing_bytes_rejected(self):
        left, right = make_pair(self.root, b'PVDATA04', 4, 2, 3)
        for name, offset, bad, original in (('data.bin', 0, b'PVDATA01', b'PVDATA04'),
                                             ('data.bin', 8, struct.pack('<q', 5), struct.pack('<q', 4)),
                                             ('map.bin', 16, struct.pack('<q', 1), struct.pack('<q', 2)),
                                             ('map.bin', 24, struct.pack('<q', 4), struct.pack('<q', 3))):
            mutate(right / name, offset, bad)
            with self.subTest(name=name, offset=offset), self.assertRaises(ValueError):
                audit.compare_validation(left, right, 4, 2)
            mutate(right / name, offset, original)
        with (right / 'map.bin').open('ab') as stream: stream.write(b'X')
        with self.assertRaises(ValueError): audit.compare_validation(left, right, 4, 2)

    def test_alias_bad_indices_and_invalid_dimensions_rejected(self):
        left, right = make_pair(self.root, b'PVDATA01', 4, 2, 3)
        for indices in ([], [4], [-1], [2, 2], [True]):
            with self.subTest(indices=indices), self.assertRaises(ValueError):
                audit.compare_shard(left, right, indices, 4, 2)
        for dimensions in ((1, 1), (4, 0), (4, 4), (129, 2)):
            with self.subTest(dimensions=dimensions), self.assertRaises(ValueError):
                audit.compare_shard(left, right, [0], *dimensions)
        (right / 'data.bin').unlink(); os.link(left / 'data.bin', right / 'data.bin')
        with self.assertRaisesRegex(ValueError, 'independent files'):
            audit.compare_shard(left, right, [2], 4, 2)

    def test_cli_requires_both_pilot_dimensions(self):
        left, right = make_pair(self.root, b'PVDATA04', 2, 1, 300)
        missing = subprocess.run([sys.executable, '-I', str(SCRIPT), 'aggregate', '--games', '2', str(left), str(right)], capture_output=True)
        self.assertNotEqual(missing.returncode, 0)
        default = subprocess.run([sys.executable, '-I', str(SCRIPT), 'aggregate', str(left), str(right)], capture_output=True)
        self.assertNotEqual(default.returncode, 0)
        pilot = subprocess.run([sys.executable, '-I', str(SCRIPT), 'aggregate', '--games', '2', '--fitting', '1', str(left), str(right)], capture_output=True)
        self.assertEqual(pilot.returncode, 0, pilot.stderr.decode())


if __name__ == '__main__':
    unittest.main()
