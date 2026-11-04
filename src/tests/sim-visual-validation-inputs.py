#!/usr/bin/env python3
"""CPU-only tests for the predeclared validation environment matrix."""
import importlib.util
import json
import struct
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('scenes', ROOT/'flex/tests/prepare-sim-visual-validation.py')
scenes = importlib.util.module_from_spec(spec); spec.loader.exec_module(scenes)


def environment():
    count, vertices = 1, 6
    data = bytearray(256+count*128+vertices*72); data[:8]=b'PBENV001'
    struct.pack_into('<3q',data,8,count,vertices,vertices)
    struct.pack_into('<7d',data,64,-3,-3,3,3,0,0,0)
    data[128:133]=b'test\0'; data[256:261]=b'wall\0'
    for offset in range(256+128,len(data),36): struct.pack_into('<9f',data,offset,0,0,0,0,0,1,.2,.3,.4)
    return bytes(data)


class SceneTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.pilot=self.root/'pilot'; src=self.pilot/'inputs';src.mkdir(parents=True)
        rooms=self.root/'rooms'
        for layout in scenes.ROOM_LAYOUTS:
            room=rooms/str(layout)/'1';room.mkdir(parents=True);(room/'environment.bin').write_bytes(environment());(room/'case.json').write_text('{\"objects\":[{}]}')
        patch=mock.patch.object(scenes,'ROOMS',rooms);patch.start();self.addCleanup(patch.stop)
        self.raw=environment();(src/'environment.bin').write_bytes(self.raw);(src/'case.json').write_text('{"objects":[{}]}')
        files={str(p):scenes.digest(p.read_bytes()) for p in src.iterdir()}
        (self.pilot/'inputs.json').write_text(json.dumps({'schema':'puppybot.sim-visual-stop-pair.v1','paths':{'case':str(src/'case.json'),'environment':str(src/'environment.bin')},'files':files}))

    def test_variants_preserve_colliders_and_mutate_only_intended_parts(self):
        old_header,old_full,old_overview=scenes.split_environment(self.raw)
        for family in scenes.FAMILIES:
            result=scenes.variant(self.raw,.35,family); header,full,overview=scenes.split_environment(result)
            self.assertEqual(header[256:],old_header[256:]);self.assertEqual(struct.unpack_from('<d',header,112)[0],.35)
            if family=='natural': self.assertEqual((full,overview),(old_full,old_overview))
            if family=='uniform':
                self.assertEqual(full[:24],old_full[:24]);self.assertEqual(struct.unpack_from('<3f',full,24),(.5,.5,.5))
            if family=='periodic':
                self.assertEqual(full[:len(old_full)],old_full);self.assertEqual(len(full),len(old_full)+120*36)
                self.assertEqual(len(full),len(overview))
                # First triangle faces the negative-x starting camera.
                a=struct.unpack_from('<3f',full,len(old_full));b=struct.unpack_from('<3f',full,len(old_full)+36);c=struct.unpack_from('<3f',full,len(old_full)+72)
                self.assertLess((b[1]-a[1])*(c[2]-a[2])-(b[2]-a[2])*(c[1]-a[1]),0)

    def test_fixed_complete_matrix_and_no_overwrite(self):
        output=self.root/'out'; report=scenes.prepare(self.pilot,output)
        self.assertEqual(len(report['conditions']),12); self.assertEqual(len({c['environmentSHA256'] for c in report['conditions']}),10)
        with self.assertRaises(FileExistsError): scenes.prepare(self.pilot,output)

    def test_bad_source_and_malformed_binary_rejected(self):
        (self.pilot/'inputs/case.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'pilot scene changed'): scenes.prepare(self.pilot,self.root/'bad')
        with self.assertRaises(ValueError): scenes.variant(self.raw[:-1],.3,'periodic')


if __name__=='__main__': unittest.main()
