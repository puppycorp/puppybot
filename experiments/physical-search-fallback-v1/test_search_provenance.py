#!/usr/bin/env python3
"""CPU-only corruption and copy-race checks against disposable archives."""
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('search_provenance_builder',HERE/'prepare.py')
prepare=importlib.util.module_from_spec(spec);spec.loader.exec_module(prepare)


class ProvenanceTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='puppy-search-provenance-');self.root=Path(self.temp.name)
        self.archive=self.root/'archive';shutil.copytree(prepare.ARCHIVE,self.archive)
        library=self.archive/'inputs/build/flex/sim/library';adapter=library/'lib/f64.flex';text=adapter.read_text()
        old=str(prepare.ARCHIVE/'inputs/flex-source/core/words.flex');new=str(self.archive/'inputs/flex-source/core/words.flex')
        if text.count(old)!=1:raise ValueError('archive adapter shape changed')
        adapter.write_text(text.replace(old,new,1));receipt=self.archive/'build.json';data=json.loads(receipt.read_text())
        data['library']=prepare.hashes(library);receipt.write_text(json.dumps(data))
        self.output=self.root/'output'

    def tearDown(self):self.temp.cleanup()

    def test_tampered_archived_baseline_is_rejected(self):
        binary=self.archive/'inputs/client';binary.write_bytes(binary.read_bytes()+b'corrupt')
        with mock.patch.object(prepare,'ARCHIVE',self.archive),self.assertRaisesRegex(ValueError,'archived compiler or baseline binary changed'):prepare.build(self.output)
        self.assertFalse((self.output/'build.json').exists())

    def test_baseline_copy_corruption_is_rejected(self):
        original=shutil.copyfile;source=self.archive/'inputs/client';reached=[]
        def corrupt(src,dst,*args,**kwargs):
            result=original(src,dst,*args,**kwargs)
            if Path(src)==source:
                reached.append(True)
                target=Path(dst);target.write_bytes(target.read_bytes()+b'corrupt')
            return result
        with mock.patch.object(prepare,'ARCHIVE',self.archive),mock.patch.object(prepare.shutil,'copyfile',side_effect=corrupt),self.assertRaisesRegex(ValueError,'baseline changed while copying'):prepare.build(self.output)
        self.assertEqual(reached,[True])
        self.assertFalse((self.output/'build.json').exists())

    def test_archive_change_during_copy_is_rejected(self):
        original=shutil.copyfile;source=self.archive/'inputs/client';reached=[]
        def change(src,dst,*args,**kwargs):
            result=original(src,dst,*args,**kwargs)
            if Path(src)==source:reached.append(True);source.write_bytes(source.read_bytes()+b'changed')
            return result
        with mock.patch.object(prepare,'ARCHIVE',self.archive),mock.patch.object(prepare.shutil,'copyfile',side_effect=change),self.assertRaisesRegex(ValueError,'baseline changed while copying'):prepare.build(self.output)
        self.assertEqual(reached,[True])
        self.assertFalse((self.output/'build.json').exists())

    def test_corrupted_copied_simulator_library_is_rejected(self):
        original=shutil.copytree;source=self.archive/'inputs/build/flex/sim/library';reached=[]
        def corrupt(src,dst,*args,**kwargs):
            result=original(src,dst,*args,**kwargs)
            if Path(src)==source:
                reached.append(True)
                adapter=Path(dst)/'lib/f64.flex';adapter.write_text(adapter.read_text()+'\n// corrupt copy\n')
            return result
        with mock.patch.object(prepare,'ARCHIVE',self.archive),mock.patch.object(prepare.shutil,'copytree',side_effect=corrupt),self.assertRaisesRegex(ValueError,'simulator library changed while copying'):prepare.build(self.output)
        self.assertEqual(reached,[True])
        self.assertFalse((self.output/'build.json').exists())


if __name__=='__main__':unittest.main()
