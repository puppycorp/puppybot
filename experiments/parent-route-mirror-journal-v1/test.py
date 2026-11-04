#!/usr/bin/env python3
"""Compile the instrumented trainer and exercise its real CPU batch filling."""
import importlib.util
import os
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREVIOUS = ROOT / 'build/flex/sim/levels-v2/pitch82/parent-route-paired-trainer-build-v1/flex-source'
COMPILER = ROOT / 'build/flex/control/compiler'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


transform = load('paired_mirror_transform', HERE / 'transform.py')
audit = load('paired_mirror_audit', HERE / 'audit.py')


class JournalProbe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='paired-mirror-native-')
        cls.root = Path(cls.temp.name); source = cls.root / 'flex-source'
        shutil.copytree(PREVIOUS, source, symlinks=True)
        (cls.root / 'build').symlink_to(ROOT / 'build', target_is_directory=True)
        train = source / 'control/train.flex'; patched = transform.transform(train.read_text())
        train.write_text(patched)
        cls.full = cls.root / 'trainer'
        subprocess.run([str(COMPILER), str(train), '-o', str(cls.full)], cwd=ROOT,
                       capture_output=True, text=True, timeout=120, check=True)
        test = transform.once(patched, 'fn main(argc,argv) {', 'fn pt_original_main(argc,argv) {')
        test = transform.once(test, 'fn pt_batch_send() {\n    ptj_send();',
                              'fn pt_batch_send() {\n    ptj_send();return 0;')
        train.write_text(test + '\n' + (HERE / 'probe.flex').read_text())
        cls.probe = cls.root / 'probe'
        subprocess.run([str(COMPILER), str(train), '-o', str(cls.probe)], cwd=ROOT,
                       capture_output=True, text=True, timeout=120, check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def generate(self, name, mode=0):
        path = self.root / name
        result = subprocess.run([str(self.probe), str(path), str(mode)], cwd=ROOT,
                                capture_output=True, text=True, timeout=30)
        return path, result

    def write_order(self, name, *, bad=False):
        order = [(i * 7) % 935 for i in range(935)] + list(range(935, 1031))
        if bad:
            order[0], order[1] = order[1], order[0]
        path = self.root / name; path.write_bytes(struct.pack('<1031Q', *order))
        return path

    def test_native_prefetch_and_final_partial_batch_match_full_order(self):
        left, result = self.generate('control.bin'); self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        right, result = self.generate('treatment.bin'); self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        a, b = self.write_order('control-order.bin'), self.write_order('treatment-order.bin')
        af, bf = self.write_order('control-final.bin'), self.write_order('treatment-final.bin')
        result = audit.verify(left, a, af, right, b, bf)
        self.assertEqual((result['batches'], result['lastBatchCount']), (468, 1))
        self.assertEqual(result['controlJournalSHA256'], result['treatmentJournalSHA256'])

    def test_native_send_rejects_mask_mismatch_and_duplicate_send(self):
        for mode in (1, 2):
            with self.subTest(mode=mode):
                path, result = self.generate(f'bad-native-{mode}.bin', mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('mirror journal send differs', result.stderr)
                self.assertTrue(path.exists())

    def test_missing_footer_and_mutated_rows_are_rejected(self):
        left, result = self.generate('good.bin'); self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        incomplete, result = self.generate('incomplete.bin', 3); self.assertEqual(result.returncode, 0)
        a, b = self.write_order('order-a.bin'), self.write_order('order-b.bin')
        af, bf = self.write_order('final-a.bin'), self.write_order('final-b.bin')
        with self.assertRaisesRegex(ValueError, 'wrong size'):
            audit.verify(left, a, af, incomplete, b, bf)
        original = left.read_bytes()
        for offset in (40, 48, 56, 64, 72, 80, len(original) - 1):
            with self.subTest(offset=offset):
                bad = bytearray(original); bad[offset] ^= 1
                path = self.root / f'mutated-{offset}.bin'; path.write_bytes(bad)
                with self.assertRaises(ValueError): audit.verify(path, a, af, left, b, bf)

    def test_changed_order_or_wrong_seed_is_rejected(self):
        journal, result = self.generate('for-order.bin'); self.assertEqual(result.returncode, 0)
        other, result = self.generate('other-journal.bin'); self.assertEqual(result.returncode, 0)
        a, b = self.write_order('correct.bin'), self.write_order('different.bin', bad=True)
        af, bf = self.write_order('correct-final.bin'), self.write_order('different-final.bin', bad=True)
        with self.assertRaisesRegex(ValueError, 'paired training orders differ'):
            audit.verify(journal, a, af, other, b, bf)
        invalid = bytearray(journal.read_bytes()); invalid[16] ^= 1
        path = self.root / 'bad-header.bin'; path.write_bytes(invalid)
        with self.assertRaisesRegex(ValueError, 'header differs'):
            audit.verify(path, a, af, other, self.write_order('same-order.bin'), self.write_order('same-final.bin'))
        with self.assertRaisesRegex(ValueError, 'first and final order differ'):
            audit.verify(journal, a, b, other, self.write_order('same-order-2.bin'), self.write_order('same-final-2.bin'))
        link = self.root / 'linked-journal.bin'; os.link(journal, link)
        with self.assertRaisesRegex(ValueError, 'alias'):
            audit.verify(journal, a, af, link, self.write_order('same-order-3.bin'), self.write_order('same-final-3.bin'))

    def test_transform_requires_unique_unmodified_source(self):
        with self.assertRaises(ValueError): transform.transform('unrelated')
        with self.assertRaises(ValueError): transform.once('same same', 'same', 'new')


if __name__ == '__main__':
    unittest.main()
