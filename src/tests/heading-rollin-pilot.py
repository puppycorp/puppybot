#!/usr/bin/env python3
"""CPU controls for the four-game roll-in pairing gates."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
p = ROOT / 'datasets/visual-control/chase-v1/levels/run-heading-rollin.py'
s = importlib.util.spec_from_file_location('rollin', p); r = importlib.util.module_from_spec(s); s.loader.exec_module(r)


class PilotPairTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.manifest = {'rows': r.catalogs.design('pilot')}
        for arm in ('control', 'treatment'):
            path = self.root / f'{arm}-L5/shard-0'; path.mkdir(parents=True)
            with (path / 'data.bin').open('wb') as f:
                f.seek(32); f.write((b'A' if arm == 'control' else b'B') * 21168)
        self.left = {'starts': [{'seed': 6700000, 'robot': [-.04, -.04, .42], 'brick': [2.5, 0]},
                                {'seed': 6700001, 'robot': [-.04, -.04, .42], 'brick': [2.7, 0]}]}
        self.right = {'starts': [{'seed': 6700000, 'robot': [-.04, -.04, .35], 'brick': [2.5, 0]},
                                 {'seed': 6700001, 'robot': [-.04, -.04, .42], 'brick': [2.7, 0]}]}

    def validate(self):
        with mock.patch.object(r, 'validate_shard', side_effect=[self.left, self.right]), \
                mock.patch.object(r.pairs, 'compare_shard', return_value={'status': 'passed'}):
            return r.validate_matched(self.root, 'pilot', self.manifest)

    def test_changed_heading_changes_frame(self):
        report = self.validate()
        self.assertEqual(report['changedHeadingInitialFrames']['0.35'], 1)

    def test_wrong_target_or_unchanged_image_rejected(self):
        self.right['starts'][0]['brick'] = [2.6, 0]
        with self.assertRaises(ValueError): self.validate()
        self.right['starts'][0]['brick'] = [2.5, 0]
        path = self.root / 'treatment-L5/shard-0/data.bin'
        with path.open('r+b') as f: f.seek(32); f.write(b'A' * 21168)
        with self.assertRaises(ValueError): self.validate()


if __name__ == '__main__': unittest.main()
