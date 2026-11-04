#!/usr/bin/env python3
"""Check the staged scene-ingestion preflight; it is not wired into control."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('guard', ROOT / 'datasets/visual-control/chase-v1/levels/preflight-training-scenes.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def sha(data):
    return hashlib.sha256(data).hexdigest()


class IngestionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.manifest = self.root / 'manifest.json'
        rows = []
        for level in range(1, 6):
            for i in range(32):
                layout = 226 + i if level < 4 else 227 + 2 * i
                rows.append({'level': level, 'index': i, 'seed': 1700000000 + level * 100 + i,
                             'layoutId': layout, 'scene': f'generated/{layout}/{i % 16}',
                             'caseSHA256': sha(b'reserved case'), 'environmentSHA256': sha(b'reserved environment')})
        self.manifest.write_text(json.dumps({'status': 'reserved_not_evaluated', 'task': 'virtual-fetch', 'gamesPerLevel': 32, 'rows': rows}))
        self.scene = self.root / 'train'
        self.scene.mkdir()
        (self.scene / 'layout.json').write_text('{}')
        (self.scene / 'case.json').write_bytes(b'training case')
        (self.scene / 'environment.bin').write_bytes(b'training environment')

    def tearDown(self):
        self.temp.cleanup()

    def test_training_scene_and_symlink_catalog(self):
        catalog = self.root / 'catalog'
        catalog.mkdir()
        (catalog / '0').symlink_to(self.scene)
        self.assertEqual(guard.verify(self.manifest, [catalog])['scenes'], 1)

    def test_reserved_role_rejected(self):
        (self.scene / 'layout.json').write_text('{"reservedHeldOut":true}')
        with self.assertRaises(ValueError):
            guard.verify(self.manifest, [self.scene])

    def test_copied_reserved_environment_rejected_even_without_role(self):
        (self.scene / 'environment.bin').write_bytes(b'reserved environment')
        with self.assertRaises(ValueError):
            guard.verify(self.manifest, [self.scene])

    def test_copied_reserved_case_rejected_even_without_role(self):
        (self.scene / 'case.json').write_bytes(b'reserved case')
        with self.assertRaises(ValueError):
            guard.verify(self.manifest, [self.scene])

    def test_missing_layout_fails_closed(self):
        (self.scene / 'layout.json').unlink()
        with self.assertRaises(ValueError):
            guard.verify(self.manifest, [self.scene])

    def test_missing_scene_file_fails_closed(self):
        (self.scene / 'environment.bin').unlink()
        with self.assertRaises(OSError):
            guard.verify(self.manifest, [self.scene])


if __name__ == '__main__':
    unittest.main()
