#!/usr/bin/env python3
"""Synthetic tests for the explicit parent-shard ancestry inventory."""
import hashlib
import importlib.util
import json
import os
import struct
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('ancestry', HERE / 'ancestry.py')
ancestry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ancestry)


def environment():
    data = bytearray(256 + 128 + 3 * 72)
    data[:8] = b'PBENV001'
    struct.pack_into('<3q', data, 8, 1, 3, 3)
    struct.pack_into('<4d', data, 64, -2, -2, 2, 2)
    struct.pack_into('<3d', data, 96, 0, 0, 0)
    data[256:260] = b'wall'
    struct.pack_into('<7d', data, 304, 1, 0, 1, .1, 1, 1, 0)
    return bytes(data)


class AncestryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.shard = self.root / 'shard-0'
        self.shard.mkdir()
        report = {'complete': True, 'seed': 50, 'episodes': 2, 'trainingEpisodes': 1,
                  'validationEpisodes': 1, 'sequenceLength': 300, 'studentDriven': False}
        (self.shard / 'report.json').write_text(json.dumps(report))
        provenance = hashlib.sha256()
        for index in range(2):
            game = self.shard / f'expert-{index}'
            scene = game / 'scene'
            scene.mkdir(parents=True)
            (game / 'result.json').write_text(json.dumps({'seed': 50 + index, 'game': 'fetch', 'steps': 300}))
            case = json.dumps({'object': index}).encode()
            world = environment()
            first = json.dumps({'event': 'start', 'step': 0, 'robot': [0, 0, 0]}).encode() + b'\n'
            for name, data in (('case.json', case), ('environment.bin', world)):
                (scene / name).write_bytes(data)
                provenance.update(str(scene / name).encode() + b'\0' + data)
            (game / 'chase.jsonl').write_bytes(first)
            provenance.update(first)
        self.source = self.root / 'source-audit.json'
        value = {'status': 'passed', 'orderedShards': [str(self.shard)], 'games': 2,
                 'trainingGames': 1, 'validationGames': 1, 'sceneStartSHA256': provenance.hexdigest()}
        self.source.write_text(json.dumps(value))
        self.source_sha = ancestry.digest(self.source.read_bytes())

    def tearDown(self):
        self.temporary.cleanup()

    def inventory(self):
        return ancestry.inventory(self.source, self.source_sha, allowed_root=self.root,
                                  expected_shards=1, expected_games=2, expected_fit=1)

    def test_complete_fit_and_validation_inventory(self):
        result = self.inventory()
        self.assertEqual(result['counts'], {'shards': 1, 'games': 2, 'fit': 1, 'validation': 1,
            'uniqueSeeds': 2, 'uniqueCases': 2, 'uniqueEnvironments': 1, 'uniqueColliderGeometries': 1,
            'uniqueProjectedPhysics': 1})
        self.assertEqual([row['split'] for row in result['games']], ['fit', 'validation'])

    def test_changed_scene_or_start_rejected_by_archived_provenance(self):
        path = self.shard / 'expert-0/scene/case.json'
        path.write_text('{"object":"different"}')
        with self.assertRaisesRegex(ValueError, 'source scene/start'):
            self.inventory()

    def test_wrong_result_seed_rejected(self):
        (self.shard / 'expert-1/result.json').write_text(json.dumps({'seed': 50, 'game': 'fetch', 'steps': 300}))
        with self.assertRaisesRegex(ValueError, 'identity'):
            self.inventory()

    def test_missing_or_symlinked_prior_scene_rejected(self):
        path = self.shard / 'expert-0/scene/environment.bin'
        moved = self.root / 'moved.bin'
        path.rename(moved)
        os.symlink(moved, path)
        with self.assertRaisesRegex(ValueError, 'symlinked'):
            self.inventory()
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.inventory()

    def test_source_audit_digest_and_split_rejected(self):
        self.source.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'digest'):
            self.inventory()


if __name__ == '__main__':
    unittest.main()
