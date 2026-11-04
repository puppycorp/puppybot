#!/usr/bin/env python3
"""Test an isolated trainer's episode-specific auxiliary masking on CPU."""
import importlib.util
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


transform = load('outbound_aux_transform', HERE / 'transform.py')
host = load('previous_host_loss_probe', ROOT / 'experiments/outbound-mask-host-loss-v1/test.py')
capacity = load('candidate_episode_capacity', ROOT / 'experiments/outbound-episode-cap-v1/transform.py')


class AuxiliaryMaskTest(unittest.TestCase):
    def test_range_and_source_anchors_are_strict(self):
        source = (ROOT / 'flex/control/train.flex').read_text()
        for start, end in ((-1, 2), (2, 2), (0, 1031), (True, 3)):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError): transform.transform(source, start, end)
        with self.assertRaises(ValueError): transform.transform('unexpected', 1, 2)

    def test_actual_batch_and_host_loss_preserve_baselines(self):
        with tempfile.TemporaryDirectory(prefix='puppy-outbound-aux-') as tmp:
            root = Path(tmp); shutil.copytree(ROOT / 'flex', root / 'flex', symlinks=True)
            (root / 'build').symlink_to(ROOT / 'build', target_is_directory=True)
            trainer = root / 'flex/control/train.flex'
            dataset = root / 'flex/control/dataset.flex'
            dataset.write_text(capacity.transform(dataset.read_text()))
            original = trainer.read_text()
            trainer.write_text(transform.transform(original, 928, 933))
            compiled = subprocess.run([str(ROOT / 'build/flex/control/compiler'), str(trainer), '-o', str(root / 'trainer')],
                                      cwd=ROOT, capture_output=True, text=True, timeout=120)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            source = transform.transform(original, 1, 2)
            source = host.host_source(source)
            trainer.write_text(source + '\nfn pt_loss(training,rate) { return pt_loss_host(training,rate); }\n' +
                               (HERE / 'probe.flex').read_text())
            binary = root / 'probe'
            built = subprocess.run([str(ROOT / 'build/flex/control/compiler'), str(trainer), '-o', str(binary)],
                                   cwd=ROOT, capture_output=True, text=True, timeout=120)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            done = subprocess.run([str(binary)], cwd=ROOT, capture_output=True, text=True, timeout=30)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertIn('outbound auxiliary batch and host-loss masks passed', done.stdout)

    def test_actual_trainer_rejects_wrong_episode_split_before_gpu(self):
        with tempfile.TemporaryDirectory(prefix='puppy-outbound-aux-split-') as tmp:
            root = Path(tmp); shutil.copytree(ROOT / 'flex', root / 'flex', symlinks=True)
            (root / 'build').symlink_to(ROOT / 'build', target_is_directory=True)
            dataset = root / 'flex/control/dataset.flex'; dataset.write_text(capacity.transform(dataset.read_text()))
            trainer = root / 'flex/control/train.flex'; source = transform.transform(trainer.read_text(), 928, 933)
            anchor = '"outbound auxiliary range does not match dataset split");'
            if source.count(anchor) != 1: raise ValueError('unexpected split guard')
            trainer.write_text(source.replace(anchor, anchor + 'pl_print(1,"split check passed\\n");return 0;', 1))
            binary = root / 'probe'
            built = subprocess.run([str(ROOT / 'build/flex/control/compiler'), str(trainer), '-o', str(binary)],
                                   cwd=ROOT, capture_output=True, text=True, timeout=120)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            data = root / 'sparse.bin'
            for total, fit, length, accepted in ((1029, 933, 300, True), (1029, 928, 300, False),
                                                  (1029, 934, 300, False), (1028, 933, 300, False),
                                                  (1031, 933, 300, False), (1029, 933, 299, False)):
                with self.subTest(total=total, fit=fit, length=length):
                    with data.open('wb') as stream:
                        stream.write(b'PVDATA04' + struct.pack('<3q', total, fit, length))
                        stream.truncate(32 + total * length * (21168 + 56))
                    self.assertLess(data.stat().st_blocks * 512, 1024 * 1024)
                    done = subprocess.run([str(binary), 'unused', 'unused', 'unused', str(data),
                                           'unused', '0', '1', '100', '7'], cwd=ROOT,
                                          capture_output=True, text=True, timeout=20)
                    self.assertEqual(done.returncode == 0, accepted, done.stderr)
                    self.assertEqual('split check passed' in done.stdout, accepted)


if __name__ == '__main__': unittest.main()
