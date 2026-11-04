#!/usr/bin/env python3
"""Private journal trainer source/binary and Btrfs build checks on CPU."""
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location('mirror_builder', HERE / 'build.py')
builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)


class BuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='paired-mirror-build-', dir=ROOT / 'build/flex/sim')
        cls.output = Path(cls.temp.name) / 'private'
        cls.receipt = builder.build(cls.output)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_full_compilation_and_reproducible_source_binding(self):
        self.assertEqual(builder.verify(self.output), self.receipt)
        self.assertEqual(self.receipt['dimensions'], [1031, 935, 300])
        self.assertEqual(self.receipt['auxiliaryMaskEpisodeRange'], [928, 935])
        train = (self.output / 'flex-source/control/train.flex').read_text()
        workflow = (self.output / 'flex-source/control/workflow.flex').read_text()
        self.assertIn(f'vc_add(args,"{self.output / "trainer"}")', workflow)
        self.assertEqual(train.count('ptj_begin(vp_path(output,"batch-schedule.bin")'), 1)
        self.assertEqual(train.count('ptj_finish();'), 1)
        self.assertLess(train.index('ptj_begin(vp_path(output,"batch-schedule.bin")'), train.index('ptj_finish();'))
        self.assertLess(train.index('ptj_finish();'), train.index('let validation=0;let validation_batches=0;'))

    def test_changed_source_binary_fixture_or_receipt_rejected(self):
        for path in (self.output / 'trainer', self.output / 'flex-source/control/loss.flex',
                     self.output / 'clone-fixture/target'):
            with self.subTest(path=path.name):
                original = path.read_bytes()
                try:
                    path.write_bytes(original + b'\n')
                    with self.assertRaises(ValueError): builder.verify(self.output)
                finally:
                    if path.parent.name == 'clone-fixture':
                        path.unlink()
                        subprocess.run([str(self.output / 'reflink-probe'),
                                        str(self.output / 'clone-fixture/source'), str(path)],
                                       cwd=ROOT, capture_output=True, text=True, timeout=20, check=True)
                    else:
                        path.write_bytes(original)
        path = self.output / 'build.json'; original = path.read_bytes()
        try:
            receipt = json.loads(original); receipt['auxiliaryMaskEpisodeRange'] = [928, 934]
            path.write_text(json.dumps(receipt))
            with self.assertRaises(ValueError): builder.verify(self.output)
        finally:
            path.write_bytes(original)
        self.assertEqual(builder.verify(self.output), self.receipt)

    def test_existing_output_and_low_disk_rejected(self):
        with self.assertRaises(FileExistsError): builder.build(self.output)
        usage = type('Usage', (), {'free': 37 * 1024**3})()
        with mock.patch.object(builder.shutil, 'disk_usage', return_value=usage):
            with self.assertRaisesRegex(ValueError, '38 GiB'):
                builder.build(self.output.parent / 'other')
        self.assertFalse((self.output.parent / 'other').exists())

    def test_linked_private_files_extra_links_and_linked_source_root_rejected(self):
        for index, path in enumerate((self.output / 'trainer', self.output / 'build.json',
                                      self.output / 'flex-source/control/loss.flex')):
            with self.subTest(path=str(path)):
                original = path.read_bytes()
                external = self.output.parent / f'external-{index}'
                external.write_bytes(original)
                try:
                    path.unlink(); path.symlink_to(external)
                    with self.assertRaises(ValueError): builder.verify(self.output)
                finally:
                    path.unlink(); path.write_bytes(original)
                    if path.name == 'trainer': path.chmod(0o755)
                link = self.output.parent / f'hardlink-{index}'
                try:
                    os.link(path, link)
                    with self.assertRaises(ValueError): builder.verify(self.output)
                finally:
                    link.unlink(); external.unlink()
        extra = self.output / 'flex-source/control/unexpected.flex'
        try:
            extra.symlink_to(self.output / 'flex-source/control/loss.flex')
            with self.assertRaises(ValueError): builder.verify(self.output)
        finally:
            extra.unlink()
        source = self.output / 'flex-source'; moved = self.output / 'flex-source-moved'
        try:
            source.rename(moved); source.symlink_to(moved, target_is_directory=True)
            with self.assertRaises(ValueError): builder.verify(self.output)
        finally:
            source.unlink(); moved.rename(source)
        self.assertEqual(builder.verify(self.output), self.receipt)

    def test_linked_parent_or_outside_root_rejected(self):
        link = self.output.parent / 'linked-parent'
        try:
            link.symlink_to(self.output.parent, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'without symlinks'):
                builder.build(link / 'fresh')
        finally:
            link.unlink()
        with self.assertRaisesRegex(ValueError, 'workspace or /tmp'):
            builder.require_output_parent(Path('/usr/fresh'))

    def test_unshared_fixture_and_linked_fixture_directory_rejected(self):
        fixture = self.output / 'clone-fixture'; source = fixture / 'source'; target = fixture / 'target'
        original = target.read_bytes()
        try:
            target.unlink()
            with target.open('xb') as stream:
                stream.write(original); stream.flush(); os.fsync(stream.fileno())
            with self.assertRaisesRegex(ValueError, 'does not share extents'):
                builder.verify(self.output)
        finally:
            target.unlink()
            subprocess.run([str(self.output / 'reflink-probe'), str(source), str(target)],
                           cwd=ROOT, capture_output=True, text=True, timeout=20, check=True)
        moved = self.output / 'clone-fixture-moved'
        try:
            fixture.rename(moved); fixture.symlink_to(moved, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'fixture directory differs'):
                builder.verify(self.output)
        finally:
            fixture.unlink(); moved.rename(fixture)
        self.assertEqual(builder.verify(self.output), self.receipt)

    def test_unexpected_source_and_path_anchors_rejected(self):
        with self.assertRaises(ValueError): builder.transform.transform('unrelated')
        with self.assertRaises(ValueError): builder.expected_source({'control/train.flex': 'bad',
                                                                     'control/workflow.flex': 'bad'}, 'bad"path')


if __name__ == '__main__':
    unittest.main()
