#!/usr/bin/env python3
"""Exercise cloning, layout, exclusion, masks and failure boundaries."""
import importlib.util
import shutil
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location('outbound_five_build', HERE / 'build.py')
b = importlib.util.module_from_spec(spec); spec.loader.exec_module(b)


class AggregateTests(unittest.TestCase):
    def setUp(self):
        # Workspace Btrfs is used deliberately: tmpfs need not support FICLONE.
        self.temp = tempfile.TemporaryDirectory(prefix='five-aggregate-test-', dir=ROOT / 'build')
        self.path = Path(self.temp.name)
        self.base = self.path / 'baseline'; self.base.mkdir()
        self.teacher = self.path / 'teacher'; self.teacher.mkdir()
        self.output = self.path / 'new'
        self.opts = dict(old_count=4, old_fit=2, teacher_count=5, teacher_fit=3,
                         length=4, image=7, raw_row=44, row=56, map_row=3,
                         min_free=0, reserve=0)
        self.selected = [(0,2),(2,3)]
        self.file(self.base/'data.bin',b'PVDATA04',4,2,4,7,56)
        self.file(self.base/'map.bin',b'PVMAP001',4,2,4,0,3)
        self.file(self.teacher/'data.bin',b'PVDATA01',5,3,4,7,44)
        self.file(self.teacher/'map.bin',b'PVMAP001',5,3,4,0,3)

    def tearDown(self): self.temp.cleanup()

    @staticmethod
    def file(path,magic,count,fit,length,image,row):
        with path.open('wb') as f:
            f.write(magic+struct.pack('<3q',count,fit,length))
            for e in range(count):
                f.write(bytes([e+10])*length*image)
                for t in range(length):
                    value=bytearray([((e*13+t)%240)+1]*row)
                    if row in (44,56): value[40:44]=b.ONE
                    f.write(value)

    def create(self):
        return b.create_data(self.base/'data.bin',self.base/'map.bin',self.teacher/'data.bin',self.teacher/'map.bin',
                             self.output,self.selected,**self.opts)

    def check(self):
        allowed = {k:v for k,v in self.opts.items() if k not in ('min_free','reserve')}
        return b.verify.verify(self.base/'data.bin',self.base/'map.bin',self.teacher/'data.bin',self.teacher/'map.bin',
                               self.output/'data.bin',self.output/'map.bin',self.selected,**allowed)

    def test_original_fitting_validation_and_selected_labels(self):
        paths = [self.base/'data.bin',self.base/'map.bin',self.teacher/'data.bin',self.teacher/'map.bin']
        before = [b.verify.sha(p) for p in paths]
        result = self.create()
        self.assertEqual((result['episodes'],result['fitting'],result['preservedEpisodes'],result['teacherEpisodes']), (6,4,4,2))
        self.assertEqual(result,self.check())
        self.assertEqual(before,[b.verify.sha(p) for p in paths])
        self.assertNotEqual((self.base/'data.bin').stat().st_ino,(self.output/'data.bin').stat().st_ino)
        with (self.output/'data.bin').open('rb') as f:
            f.seek(32+2*4*(7+56)+4*7+2*56+40)
            self.assertEqual(f.read(4),b.ZERO)

    def test_verifier_rejects_modified_preserved_validation_and_teacher_mask(self):
        self.create(); p=self.output/'data.bin'
        with p.open('r+b') as f:
            f.seek(32+4*4*(7+56));f.write(b'!')
        with self.assertRaises(ValueError): self.check()

    def test_verifier_rejects_changed_teacher_map(self):
        self.create(); p=self.output/'map.bin'
        with p.open('r+b') as f:
            f.seek(32+2*4*3);f.write(b'!')
        with self.assertRaises(ValueError): self.check()

    def test_existing_output_never_overwritten(self):
        self.output.mkdir();(self.output/'sentinel').write_text('preserve')
        with self.assertRaises(FileExistsError): self.create()
        self.assertEqual((self.output/'sentinel').read_text(),'preserve')

    def test_invalid_selection_or_source_alias_rejected_before_creation(self):
        self.selected=[(3,1)] # teacher validation is excluded
        with self.assertRaises(ValueError): self.create()
        self.assertFalse(self.output.exists())
        self.selected=[(0,1),(0,2)]
        with self.assertRaises(ValueError): self.create()
        self.assertFalse(self.output.exists())
        with self.assertRaises(ValueError):
            b.create_data(self.base/'data.bin',self.base/'data.bin',self.teacher/'data.bin',self.teacher/'map.bin',
                          self.output,[(0,1)],**self.opts)

    def test_output_inside_source_and_disk_shortage_rejected(self):
        with self.assertRaises(ValueError):
            b.create_data(self.base/'data.bin',self.base/'map.bin',self.teacher/'data.bin',self.teacher/'map.bin',
                          self.base/'nested',self.selected,**self.opts)
        with mock.patch.object(b.shutil,'disk_usage',return_value=shutil._ntuple_diskusage(10,9,1)):
            with self.assertRaises(ValueError): self.create()
        self.assertFalse(self.output.exists())

    def test_bad_teacher_mask_fails_without_modifying_input(self):
        p=self.teacher/'data.bin'
        with p.open('r+b') as f:
            f.seek(32+4*7+40);f.write(b'bad!')
        before=b.verify.sha(p)
        with self.assertRaises(ValueError): self.create()
        self.assertEqual(before,b.verify.sha(p))
        self.assertFalse((self.output/'report.json').exists())

    def test_reject_hardlinked_baseline(self):
        (self.path/'alias').hardlink_to(self.base/'data.bin')
        with self.assertRaises(ValueError): self.create()
        self.assertFalse((self.output/'report.json').exists())

    def test_source_pins_reject_changed_frozen_helper(self):
        helper = self.path/'frozen-helper.py'; helper.write_text('value = 1\n')
        frozen = {'sourceFiles': {str(helper): b.verify.sha(helper)}}
        with mock.patch.object(b, 'local_source_chain', return_value=[]):
            self.assertEqual(b.source_pins(frozen)[str(helper)], b.verify.sha(helper))
            helper.write_text('value = 2\n')
            with self.assertRaises(ValueError): b.source_pins(frozen)

    def test_direct_mask_and_supervisor_sources_are_pinned(self):
        frozen = {'sourceFiles': {}}
        pins = b.source_pins(frozen)
        self.assertIn(str(ROOT/'experiments/outbound-prefix-mask-v1/mask.py'), pins)
        self.assertIn(str(HERE/'build.py'), pins)
        self.assertIn(str(HERE/'verify.py'), pins)


if __name__ == '__main__': unittest.main()
