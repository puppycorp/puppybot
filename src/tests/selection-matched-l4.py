#!/usr/bin/env python3
"""CPU fixtures for the L4 whole-game matched-data audit."""
import importlib.util
import json
import struct
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('matched', ROOT / 'datasets/visual-control/chase-v1/levels/audit-matched-l4.py')
matched = importlib.util.module_from_spec(spec)
spec.loader.exec_module(matched)


class MatchedAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.old, self.new, self.common = [self.root / n for n in ('old', 'new', 'common')]
        for path in (self.old, self.new, self.common):
            path.mkdir()
            (path / 'report.json').write_text(json.dumps({'episodes': 2, 'trainingEpisodes': 1}))
        self.pairs = [(self.common, self.common), (self.old, self.new)]
        self.a, self.b = self.root / 'a', self.root / 'b'
        for directory in (self.a, self.b):
            directory.mkdir()
            for name, magic, width in (('data.bin', b'PVDATA04', 21224), ('map.bin', b'PVMAP001', 144)):
                with (directory / name).open('wb') as f:
                    f.write(magic + struct.pack('<qqq', 4, 2, 300))
                    f.truncate(32 + 4 * 300 * width)

    def change(self, directory, name, game, width):
        with (directory / name).open('r+b') as f:
            f.seek(32 + game * 300 * width + 50)
            f.write(b'X')

    def test_replacement_differences_allowed(self):
        self.change(self.b, 'data.bin', 1, 21224)
        self.change(self.b, 'map.bin', 3, 144)
        self.assertEqual(matched.compare(self.a, self.b, self.pairs)['unchangedGames'], 2)

    def test_unaffected_fitting_and_validation_data_rejected(self):
        for game in (0, 2):
            with self.subTest(game=game):
                self.change(self.b, 'data.bin', game, 21224)
                with self.assertRaises(ValueError):
                    matched.compare(self.a, self.b, self.pairs)
                self.change(self.a, 'data.bin', game, 21224)

    def test_unaffected_map_rejected(self):
        self.change(self.b, 'map.bin', 2, 144)
        with self.assertRaises(ValueError):
            matched.compare(self.a, self.b, self.pairs)

    def test_mismatched_slot_split_rejected(self):
        (self.new / 'report.json').write_text(json.dumps({'episodes': 2, 'trainingEpisodes': 2}))
        with self.assertRaises(ValueError):
            matched.compare(self.a, self.b, self.pairs)

    def test_truncated_aggregate_rejected(self):
        with (self.b / 'data.bin').open('r+b') as f:
            f.truncate(40)
        with self.assertRaises(ValueError):
            matched.compare(self.a, self.b, self.pairs)


if __name__ == '__main__':
    unittest.main()
