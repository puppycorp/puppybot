#!/usr/bin/env python3
"""CPU checks of matched heading-distribution DAgger catalogs."""
import importlib.util
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

root = Path(__file__).resolve().parents[2]
p = root / 'datasets/visual-control/chase-v1/levels/prepare-heading-rollin.py'
spec = importlib.util.spec_from_file_location('heading', p)
heading = importlib.util.module_from_spec(spec); spec.loader.exec_module(heading)


class CatalogTest(unittest.TestCase):
    def test_balanced_fit_and_identical_validation(self):
        rows = heading.design('full')
        self.assertEqual(Counter(r['treatmentYaw'] for r in rows if r['fitting']), {.35: 40, .42: 40, .49: 40})
        self.assertEqual(sum(not r['fitting'] and r['controlYaw'] == r['treatmentYaw'] for r in rows), 8)
        self.assertEqual(len({r['seed'] for r in rows}), 128)
        for shard in range(4):
            self.assertEqual(sum(r['fitting'] for r in rows if r['shard'] == shard), 30)

    def test_pilot_and_full_catalogs_and_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            for mode in ('pilot', 'full'):
                out = Path(tmp) / mode; manifest = heading.prepare(mode, out); heading.verify(out, manifest)
                for r in manifest['rows']:
                    a = out / 'control-L5/catalogs' / f'shard-{r["shard"]}' / str(r['index'])
                    b = out / 'treatment-L5/catalogs' / f'shard-{r["shard"]}' / str(r['index'])
                    self.assertEqual((a / 'case.json').read_bytes(), (b / 'case.json').read_bytes())
                    if not r['fitting'] or r['treatmentYaw'] == .42:
                        self.assertEqual((a / 'environment.bin').read_bytes(), (b / 'environment.bin').read_bytes())
                r = manifest['rows'][0]; f = out / 'control-L5/catalogs/shard-0/0/environment.bin'
                b = bytearray(f.read_bytes()); b[-1] ^= 1; f.write_bytes(b)
                with self.assertRaises(ValueError): heading.verify(out, manifest)
                with self.assertRaises(ValueError): heading.prepare(mode, out)

    def test_source_seed_overlap_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / 'report.json'; f.write_text(json.dumps({'seed': heading.BASE_SEED, 'episodes': 32}))
            with mock.patch.object(heading.validation, 'inventory', return_value=[f]):
                with self.assertRaises(ValueError): heading.check_inventory(heading.design('full'))


if __name__ == '__main__': unittest.main()
