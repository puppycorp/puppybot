#!/usr/bin/env python3
"""Compile and test the exact copied trainer on CPU without running a GPU graph."""
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
PREVIOUS = ROOT / 'build/flex/sim/levels-v2/pitch82/outbound-five-trainer-build-v1/flex-source'
COMPILER = ROOT / 'build/flex/control/compiler'
IMAGE = 21168
ROW = 56
LENGTH = 300
CUTOFFS = {928: 162, 929: 107, 930: 171, 931: 43, 932: 38, 933: 163, 934: 189}


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


transform = load('paired_trainer_transform', HERE / 'transform.py')
host = load('prior_host_loss', ROOT / 'experiments/outbound-mask-host-loss-v1/test.py')


def row_offset(episode, step, length=LENGTH):
    return 32 + episode * length * (IMAGE + ROW) + length * IMAGE + step * ROW


def make_data(path):
    """Sparse 1,031-history file with the seven selected histories populated."""
    with Path(path).open('wb') as data:
        data.write(struct.pack('<8s3q', b'PVDATA04', 1031, 935, LENGTH))
        data.truncate(32 + 1031 * LENGTH * (IMAGE + ROW))
        for episode, cutoff in CUTOFFS.items():
            data.seek(row_offset(episode, 0))
            for step in range(LENGTH):
                label = (.6, 1.) if episode < 933 or step < cutoff else (0., 0.)
                executed = (.6, 1.) if episode < 933 else (0., 1.)
                row = struct.pack('<7f2f3f2f', *([0.] * 7), *label, 0., float(step < cutoff), 1., *executed)
                data.write(row)
    if Path(path).stat().st_blocks * 512 >= 4 * 1024 * 1024:
        raise RuntimeError('sparse test unexpectedly allocated too much physical disk')


class PairedTrainerProbe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='paired-trainer-cpu-probe-')
        cls.root = Path(cls.temp.name); source = cls.root / 'flex-source'
        shutil.copytree(PREVIOUS, source, symlinks=True)
        (cls.root / 'build').symlink_to(ROOT / 'build', target_is_directory=True)
        trainer = source / 'control/train.flex'; dataset = source / 'control/dataset.flex'
        original_trainer = trainer.read_text(); original_dataset = dataset.read_text()
        dataset.write_text(transform.dataset(original_dataset))
        patched = transform.train(original_trainer); trainer.write_text(patched)
        cls.full = cls.root / 'trainer'
        subprocess.run([str(COMPILER), str(trainer), '-o', str(cls.full)], cwd=ROOT,
                       check=True, capture_output=True, text=True, timeout=120)
        host_source = host.host_source(patched)
        trainer.write_text(host_source + '\nfn pt_loss(training,rate) { return pt_loss_host(training,rate); }\n' +
                           (HERE / 'probe.flex').read_text())
        cls.host = cls.root / 'host-probe'
        subprocess.run([str(COMPILER), str(trainer), '-o', str(cls.host)], cwd=ROOT,
                       check=True, capture_output=True, text=True, timeout=120)
        anchor = '    pt_check_rows(episodes);\n    // Longer unrolled GRU episodes need more nodes than detector inference.'
        if patched.count(anchor) != 1:
            raise ValueError('pre-GPU row check anchor differs')
        early = ('    pt_check_rows(episodes);pl_print(1,"paired pre-GPU guards passed\\n");return 0;\n'
                 '    // Longer unrolled GRU episodes need more nodes than detector inference.')
        trainer.write_text(patched.replace(anchor, early, 1))
        cls.guard = cls.root / 'guard-probe'
        subprocess.run([str(COMPILER), str(trainer), '-o', str(cls.guard)], cwd=ROOT,
                       check=True, capture_output=True, text=True, timeout=120)
        cls.data = cls.root / 'data.bin'; make_data(cls.data)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def invoke(self):
        return subprocess.run([str(self.guard), 'unused', 'unused', 'unused', str(self.data),
                               'unused', '0', '1', '100', '7', '--carry-cue', '--categorical'],
                              cwd=ROOT, capture_output=True, text=True, timeout=30)

    def change(self, offset, replacement, accepted, text=None):
        with self.data.open('r+b') as data:
            data.seek(offset); original = data.read(len(replacement)); data.seek(offset); data.write(replacement)
        try:
            result = self.invoke()
            self.assertEqual(result.returncode == 0, accepted, result.stdout + result.stderr)
            self.assertEqual('paired pre-GPU guards passed' in result.stdout, accepted)
            if text:
                self.assertIn(text, result.stderr)
        finally:
            with self.data.open('r+b') as data:
                data.seek(offset); data.write(original)

    def test_exact_range_batch_and_host_loss(self):
        result = subprocess.run([str(self.host)], cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('paired trainer exact-range batch and host-loss masks passed', result.stdout)

    def test_correct_sparse_data_and_paired_label_variants_pass_before_gpu(self):
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('paired pre-GPU guards passed', result.stdout)
        # Either paired prefix may carry the teacher or the executed action.
        for episode in (933, 934):
            with self.subTest(episode=episode):
                self.change(row_offset(episode, 0) + 28, struct.pack('<2f', 0., 1.), True)

    def test_wrong_header_split_horizon_and_magic_rejected_before_gpu(self):
        for offset, value in ((0, b'PVDATA03'), (8, struct.pack('<q', 1030)),
                              (16, struct.pack('<q', 934)), (16, struct.pack('<q', 936)),
                              (24, struct.pack('<q', 299)), (24, struct.pack('<q', 301))):
            with self.subTest(offset=offset, value=value):
                self.change(offset, value, False)

    def test_each_selected_prefix_and_suffix_boundary_is_checked(self):
        for episode, cutoff in CUTOFFS.items():
            with self.subTest(episode=episode, boundary='last prefix'):
                self.change(row_offset(episode, cutoff - 1) + 40, struct.pack('<f', 0.), False,
                            'paired fitting validity or prefix mask differs')
            with self.subTest(episode=episode, boundary='first suffix'):
                self.change(row_offset(episode, cutoff) + 40, struct.pack('<f', 1.), False,
                            'paired fitting validity or prefix mask differs')
            with self.subTest(episode=episode, boundary='validity'):
                self.change(row_offset(episode, cutoff) + 44, struct.pack('<f', 0.), False,
                            'paired fitting validity or prefix mask differs')

    def test_pair_label_action_and_legacy_identity_guards(self):
        self.change(row_offset(933, 0) + 28, struct.pack('<2f', .5, 1.), False,
                    'paired fitting action is outside joint-seven codec')
        self.change(row_offset(934, 0) + 48, struct.pack('<2f', .5, 1.), False,
                    'paired fitting action is outside joint-seven codec')
        self.change(row_offset(928, 0) + 28, struct.pack('<2f', 0., 1.), False,
                    'original teacher labels or executed actions differ')
        self.change(row_offset(933, CUTOFFS[933]) + 28, struct.pack('<2f', 0., 1.), False,
                    'paired fitting suffix action label must be zero')
        self.change(row_offset(934, CUTOFFS[934]) + 28, struct.pack('<2f', -.6, 1.), False,
                    'paired fitting suffix action label must be zero')

    def test_adjacent_baseline_and_validation_are_not_subject_to_pair_codec(self):
        for episode in (927, 935, 1030):
            with self.subTest(episode=episode):
                self.change(row_offset(episode, 0) + 28, struct.pack('<2f', .5, 1.), True)


if __name__ == '__main__':
    unittest.main()
