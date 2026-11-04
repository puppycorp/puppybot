#!/usr/bin/env python3
"""Exercise 1,029-history native trainer host indexing without a GPU."""
import importlib.util
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location('outbound_capacity_transform', HERE / 'transform.py')
transform = importlib.util.module_from_spec(spec); spec.loader.exec_module(transform)


class TrainerOrderTest(unittest.TestCase):
    def test_native_fit_shuffle_and_last_validation_batch(self):
        with tempfile.TemporaryDirectory(prefix='puppy-outbound-order-') as tmp:
            root = Path(tmp); shutil.copytree(ROOT / 'flex', root / 'flex', symlinks=True)
            (root / 'build').symlink_to(ROOT / 'build', target_is_directory=True)
            dataset = root / 'flex/control/dataset.flex'; dataset.write_text(transform.transform(dataset.read_text()))
            trainer = root / 'flex/control/train.flex'; source = trainer.read_text()
            main = 'fn main(argc,argv) {'
            shuffle = ('i=training_count;while i>1 {i=i-1;let j=pt_random()%(i+1);'
                       'let a=load64(order+i*8);store64(order+i*8,load64(order+j*8));store64(order+j*8,a);}')
            if source.count(main) != 1 or source.count(shuffle) != 2:
                raise ValueError('unexpected trainer entrypoint or shuffle')
            probe = (HERE / 'order-probe.flex').read_text().replace('@@TRAINING_SHUFFLE@@', shuffle)
            trainer.write_text(source.replace(main, 'fn pt_original_train_main(argc,argv) {', 1) + '\n' + probe)
            binary = root / 'probe'
            built = subprocess.run([str(ROOT / 'build/flex/control/compiler'), str(trainer), '-o', str(binary)],
                                   cwd=ROOT, capture_output=True, text=True, timeout=120)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            maps = root / 'map.bin'
            maps.write_bytes(b'PVMAP001' + struct.pack('<3q', 1029, 933, 1) +
                             b''.join(bytes([i % 3]) * 144 for i in range(1029)))
            done = subprocess.run([str(binary), str(maps)], cwd=ROOT, capture_output=True, text=True, timeout=30)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertIn('1029-history fitting permutation and validation batch passed', done.stdout)


if __name__ == '__main__': unittest.main()
