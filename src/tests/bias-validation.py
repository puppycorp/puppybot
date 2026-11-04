#!/usr/bin/env python3
"""CPU guards for fresh-seed recorded-source inventory."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

root = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('validation', root / 'datasets/visual-control/chase-v1/levels/prepare-bias-validation.py')
validation = importlib.util.module_from_spec(spec); spec.loader.exec_module(validation)


class InventoryTest(unittest.TestCase):
    def test_actual_recorded_sources_disjoint(self):
        self.assertEqual(len(validation.inventory()), 60)

    def test_overlap_and_missing_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp); o = p / 'search-dagger-l4-matched'
            shards = [p / f'kturn-L{level}' / f'shard-{i}' for level in range(6) for i in range(8)]
            for parent in (p / 'search-dagger-4workers/dagger-L3', p / 'search-dagger-l35-4workers/dagger-L5', o / 'dagger-L4'):
                shards.extend(parent / f'shard-{i}' for i in range(4))
            for i, shard in enumerate(shards):
                shard.mkdir(parents=True); (shard / 'report.json').write_text(json.dumps({'seed': i * 100, 'episodes': 32}))
            with mock.patch.object(validation, 'P', p), mock.patch.object(validation, 'O', o):
                self.assertEqual(len(validation.inventory()), 60)
                (shards[0] / 'report.json').write_text(json.dumps({'seed': validation.SEEDS[0], 'episodes': 32}))
                with self.assertRaises(ValueError): validation.inventory()
                (shards[0] / 'report.json').unlink()
                with self.assertRaises(ValueError): validation.inventory()


if __name__ == '__main__': unittest.main()
