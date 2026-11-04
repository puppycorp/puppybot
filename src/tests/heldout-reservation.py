#!/usr/bin/env python3
"""Small synthetic reservation checks; does not generate or play held-out scenes."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / 'datasets/visual-control/chase-v1/levels/prepare-heldout.py'
FAKE = '''#!/usr/bin/env python3
import json,sys
from pathlib import Path
root=Path(sys.argv[1]);root.mkdir()
for layout in range(226,290):
    variants=set()
    if layout<258: variants.add((layout-226)%16)
    if layout%2: variants.add(((layout-227)//2)%16)
    for variant in variants:
        p=root/str(layout)/str(variant);p.mkdir(parents=True)
        (p/'layout.json').write_text(json.dumps({'layoutId':layout,'fit':False,'reservedHeldOut':True,'rooms':[[]]*(1+layout%2),'startPose':[layout/1000,0,0]}))
        (p/'case.json').write_text(f'case {layout} {variant}')
        (p/'environment.bin').write_text(f'env {layout}')
'''


class ReservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.generator = self.root / 'fake-generator'
        self.generator.write_text(FAKE)
        self.generator.chmod(0o755)
        self.prior = self.root / 'prior' / 'game'
        (self.prior / 'scene').mkdir(parents=True)
        (self.prior / 'scene' / 'case.json').write_text('prior case')
        (self.prior / 'scene' / 'environment.bin').write_text('prior environment')
        (self.prior / 'result.json').write_text(json.dumps({'seed': 42}))

    def tearDown(self):
        self.temp.cleanup()

    def run_tool(self):
        return subprocess.run(['python3', '-I', str(TOOL), str(self.generator), str(self.root / 'out'), str(self.prior.parent)],
                              text=True, capture_output=True)

    def test_reservation_without_policy_runs(self):
        result = self.run_tool()
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((self.root / 'out' / 'manifest.json').read_text())
        self.assertEqual(data['status'], 'reserved_not_evaluated')
        self.assertEqual(len(data['rows']), 160)
        self.assertEqual(len({r['seed'] for r in data['rows']}), 160)
        for level in range(1, 6):
            rows = [r for r in data['rows'] if r['level'] == level]
            self.assertEqual(len({r['environmentSHA256'] for r in rows}), 32)
            self.assertEqual(len({tuple(r['startPose']) for r in rows}), 32)
            if level >= 4:
                self.assertTrue(all(r['layoutId'] % 2 for r in rows))

    def test_prior_seed_overlap_fails_before_output(self):
        (self.prior / 'result.json').write_text(json.dumps({'seed': 1700000100}))
        self.assertNotEqual(self.run_tool().returncode, 0)
        self.assertFalse((self.root / 'out').exists())

    def test_prior_environment_overlap_has_no_manifest(self):
        (self.prior / 'scene' / 'environment.bin').write_text('env 226')
        self.assertNotEqual(self.run_tool().returncode, 0)
        self.assertFalse((self.root / 'out' / 'manifest.json').exists())

    def test_existing_output_is_preserved(self):
        out = self.root / 'out'
        out.mkdir()
        (out / 'keep').write_text('untouched')
        self.assertNotEqual(self.run_tool().returncode, 0)
        self.assertEqual((out / 'keep').read_text(), 'untouched')

    def test_seeded_prior_missing_scene_is_rejected(self):
        (self.prior / 'scene' / 'case.json').unlink()
        self.assertNotEqual(self.run_tool().returncode, 0)
        self.assertFalse((self.root / 'out').exists())

    def test_report_only_shard_is_rejected(self):
        (self.prior / 'report.json').write_text(json.dumps({'complete': True, 'seed': 1000, 'episodes': 2}))
        self.assertNotEqual(self.run_tool().returncode, 0)
        self.assertFalse((self.root / 'out').exists())


if __name__ == '__main__':
    unittest.main()
