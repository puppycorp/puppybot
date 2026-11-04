#!/usr/bin/env python3
"""Synthetic-only parity, corruption and race fixtures; no production reads."""
import hashlib
import importlib.util
import math
import os
import shutil
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('fused_overlay_fixture',HERE/'audit.py')
fused=importlib.util.module_from_spec(spec);spec.loader.exec_module(fused)


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def header(magic,n,fit,fmt):return fused.HEADER.pack(magic,n,fit,fmt.horizon)


def student_game(fmt,marker):
    images=bytes([marker])*(fmt.horizon*fmt.image);rows=[]
    for i in range(fmt.horizon):
        row=bytearray(44);row[0]=marker+i;struct.pack_into('<2f4xf',row,28,-.5,.75,1.);rows.append(row)
    return images+b''.join(rows)


def convert_reference(data,episode,fmt):
    offset=32+episode*fmt.horizon*fmt.old_width;image_size=fmt.horizon*fmt.image
    images=data[offset:offset+image_size];rows=data[offset+image_size:offset+fmt.horizon*fmt.old_width]
    result=bytearray(fmt.horizon*fmt.new_width);result[:image_size]=images
    for i in range(fmt.horizon):
        old=rows[i*44:(i+1)*44];position=image_size+i*56
        steer,speed,weight=struct.unpack_from('<2f4xf',old,28)
        if not all(math.isfinite(v) and abs(v)<=1 for v in (steer,speed)) or weight!=1:raise ValueError('invalid student label')
        result[position:position+44]=old;result[position+44:position+48]=struct.pack('<f',1);result[position+48:position+56]=old[28:36]
    return bytes(result)


def legacy_check(base,stage,mapping,pins,fmt,kind):
    # Separate pre-hash, exact slot audit and separate post-hash on stable test
    # inputs, matching the relevant legacy validation phases.
    for path,expected in pins.items():
        if digest(path)!=expected:raise ValueError('pre hash')
    a=Path(base).read_bytes();b=Path(stage).read_bytes();width=fmt.new_width if kind=='data' else fmt.map_width
    magic=b'PVDATA04' if kind=='data' else b'PVMAP001';n,fit=fused.parse_header(a[:32],magic,fmt,width,len(a))
    if fused.parse_header(b[:32],magic,fmt,width,len(b))!=(n,fit) or a[:32]!=b[:32]:raise ValueError('header')
    size=fmt.horizon*width
    for i in range(n):
        old=a[32+i*size:32+(i+1)*size];new=b[32+i*size:32+(i+1)*size]
        if i not in mapping:
            if old!=new:raise ValueError('unchanged')
        else:
            source,episode=mapping[i];raw=Path(source).read_bytes()
            expected=convert_reference(raw,episode,fmt) if kind=='data' else raw[32+episode*size:32+(episode+1)*size]
            if new!=expected:raise ValueError('replaced')
    for path,expected in pins.items():
        if digest(path)!=expected:raise ValueError('post hash')
    return True


class FusedTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.fmt=fused.Format(horizon=2,image=3,map_width=4)

    def make(self,kind='data',slots=(1,)):
        fmt=self.fmt;n=4;self.kind=kind;self.base=self.root/'base';self.stage=self.root/'stage';self.source=self.root/'source'
        if kind=='data':
            chunk=fmt.horizon*fmt.new_width;old=[bytes([i+1])*chunk for i in range(n)]
            source=header(b'PVDATA01',2,1,fmt)+student_game(fmt,8)+student_game(fmt,15)
            replacement=convert_reference(source,1,fmt);magic=b'PVDATA04'
        else:
            chunk=fmt.horizon*fmt.map_width;old=[bytes([i+1])*chunk for i in range(n)]
            source=header(b'PVMAP001',2,1,fmt)+bytes([8])*chunk+bytes([15])*chunk;replacement=bytes([15])*chunk;magic=b'PVMAP001'
        self.source.write_bytes(source);self.base.write_bytes(header(magic,n,2,fmt)+b''.join(old));new=old.copy()
        for i in slots:new[i]=replacement
        self.stage.write_bytes(header(magic,n,2,fmt)+b''.join(new));self.mapping={i:(self.source,1) for i in slots}
        self.pins={self.base:digest(self.base),self.stage:digest(self.stage),self.source:digest(self.source)}

    def run_audit(self,hook=None):
        return fused.audit(self.base,self.stage,self.mapping,self.pins[self.base],self.pins[self.stage],{self.source:self.pins[self.source]},kind=self.kind,fmt=self.fmt,_hook=hook)

    def test_data_and_map_match_legacy_with_full_byte_counts(self):
        for kind in ('data','map'):
            with self.subTest(kind=kind):
                self.make(kind,slots=(0,3));self.assertTrue(legacy_check(self.base,self.stage,self.mapping,self.pins,self.fmt,kind));result=self.run_audit()
                self.assertEqual(result['status'],'synthetic_diagnostic_only');self.assertEqual(result['baseSHA256'],self.pins[self.base]);self.assertEqual(result['stageSHA256'],self.pins[self.stage])
                self.assertEqual(result['fusedAggregateBytes'],self.base.stat().st_size+self.stage.stat().st_size)
                self.assertEqual(result['postAggregateBytes'],result['fusedAggregateBytes']);self.assertEqual(result['sourceDigestBytes'],2*self.source.stat().st_size)

    def test_archived_auditor_accepts_same_synthetic_bytes(self):
        root=HERE.parents[1];path=root/'datasets/visual-control/chase-v1/levels/heading-reflink-overlay.py'
        spec=importlib.util.spec_from_file_location('real_legacy_overlay',path);legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)
        self.assertEqual((legacy.HORIZON,legacy.IMAGE,legacy.MAP_WIDTH),(fused.PRODUCTION.horizon,fused.PRODUCTION.image,fused.PRODUCTION.map_width))
        base=self.root/'base-dir';stage=self.root/'stage-dir';source=self.root/'shard-dir'
        for folder in (base,stage,source):folder.mkdir()
        for kind in ('data','map'):
            self.make(kind);name=kind+'.bin'
            for origin,dest in ((self.base,base/name),(self.stage,stage/name),(self.source,source/name)):shutil.copyfile(origin,dest)
        with mock.patch.multiple(legacy,HORIZON=self.fmt.horizon,IMAGE=self.fmt.image,OLD_WIDTH=self.fmt.old_width,NEW_WIDTH=self.fmt.new_width,MAP_WIDTH=self.fmt.map_width):
            legacy.audit(base,stage,{1:(source,1)},4)
            for kind in ('data','map'):
                old=base/(kind+'.bin');new=stage/(kind+'.bin');shard=source/(kind+'.bin')
                fused.audit(old,new,{1:(shard,1)},digest(old),digest(new),{shard:digest(shard)},kind=kind,fmt=self.fmt)
            damaged=bytearray((stage/'data.bin').read_bytes());damaged[32+self.fmt.horizon*self.fmt.new_width]^=1;(stage/'data.bin').write_bytes(damaged)
            with self.assertRaises(ValueError):legacy.audit(base,stage,{1:(source,1)},4)
            with self.assertRaises(ValueError):fused.audit(base/'data.bin',stage/'data.bin',{1:(source/'data.bin',1)},digest(base/'data.bin'),digest(stage/'data.bin'),{source/'data.bin':digest(source/'data.bin')},kind='data',fmt=self.fmt)
            damaged[32+self.fmt.horizon*self.fmt.new_width]^=1;(stage/'data.bin').write_bytes(damaged)
            shard=source/'data.bin';bad=bytearray(shard.read_bytes());offset=32+self.fmt.horizon*self.fmt.old_width+self.fmt.horizon*self.fmt.image
            struct.pack_into('<f',bad,offset+40,0.);shard.write_bytes(bad)
            with self.assertRaises(ValueError):legacy.audit(base,stage,{1:(source,1)},4)
            with self.assertRaises(ValueError):fused.audit(base/'data.bin',stage/'data.bin',{1:(shard,1)},digest(base/'data.bin'),digest(stage/'data.bin'),{shard:digest(shard)},kind='data',fmt=self.fmt)

    def test_wrong_pins_and_truncated_or_extended_files_fail(self):
        for name in ('base','stage','source','short','extra'):
            with self.subTest(name=name):
                self.make();path=getattr(self,name,None)
                if name in ('base','stage','source'):self.pins[path]='0'*64
                elif name=='short':self.stage.write_bytes(self.stage.read_bytes()[:-1]);self.pins[self.stage]=digest(self.stage)
                else:self.stage.write_bytes(self.stage.read_bytes()+b'x');self.pins[self.stage]=digest(self.stage)
                with self.assertRaises((ValueError,OSError)):self.run_audit()
                if name in ('base','stage','source'):
                    with self.assertRaises(ValueError):legacy_check(self.base,self.stage,self.mapping,self.pins,self.fmt,'data')

    def test_wrong_identical_headers_and_game_corruption_fail(self):
        for kind in ('header','unchanged','replacement','label'):
            with self.subTest(kind=kind):
                self.make();path=self.source if kind=='label' else self.stage;data=bytearray(path.read_bytes())
                if kind=='header':
                    data[0]=0;self.stage.write_bytes(data);old=bytearray(self.base.read_bytes());old[0]=0;self.base.write_bytes(old);self.pins[self.base]=digest(self.base)
                elif kind=='unchanged':data[32]^=1;self.stage.write_bytes(data)
                elif kind=='replacement':data[32+self.fmt.horizon*self.fmt.new_width]^=1;self.stage.write_bytes(data)
                else:
                    row=32+self.fmt.horizon*self.fmt.old_width+self.fmt.horizon*self.fmt.image
                    struct.pack_into('<f',data,row+40,0.);self.source.write_bytes(data)
                self.pins[path]=digest(path)
                with self.assertRaises(ValueError):self.run_audit()
                with self.assertRaises(ValueError):legacy_check(self.base,self.stage,self.mapping,self.pins,self.fmt,'data')

    def test_slot_and_source_inventory_boundaries(self):
        self.make(slots=(0,3));self.run_audit()
        for index,episode in ((-1,0),(4,0),(0,2),(0,-1)):
            with self.subTest(index=index,episode=episode):
                self.mapping={index:(self.source,episode)}
                with self.assertRaises(ValueError):self.run_audit()
        self.make();extra=self.root/'extra';extra.write_bytes(self.source.read_bytes())
        with self.assertRaisesRegex(ValueError,'inventory'):
            fused.audit(self.base,self.stage,self.mapping,self.pins[self.base],self.pins[self.stage],{self.source:self.pins[self.source],extra:digest(extra)},kind='data',fmt=self.fmt)

    def test_symlink_alias_and_swapped_source_rejected(self):
        self.make();link=self.root/'link';link.symlink_to(self.source)
        with self.assertRaises(ValueError):fused.audit(self.base,self.stage,{1:(link,1)},self.pins[self.base],self.pins[self.stage],{link:self.pins[self.source]},kind='data',fmt=self.fmt)
        with self.assertRaises(ValueError):fused.audit(self.base,self.base,{},self.pins[self.base],self.pins[self.base],{},kind='data',fmt=self.fmt)
        def swap(label,index):
            if label=='after_source_prepass':
                other=self.root/'other';other.write_bytes(self.source.read_bytes());os.replace(other,self.source)
        with self.assertRaisesRegex(ValueError,'changed or path was replaced'):self.run_audit(swap)

    def test_mutation_during_or_between_passes_fails(self):
        for when in ('stream','between','source'):
            with self.subTest(when=when):
                self.make()
                def change(label,index):
                    if (when=='stream' and label=='after_game' and index==0) or (when=='between' and label=='before_postpass') or (when=='source' and label=='after_source_prepass'):
                        path=self.source if when=='source' else self.stage
                        data=bytearray(path.read_bytes());data[-1]^=1;path.write_bytes(data)
                with self.assertRaises(ValueError):self.run_audit(change)

    def test_change_then_restore_is_not_hidden_by_same_bytes(self):
        self.make();original=self.stage.read_bytes()
        def change(label,index):
            if label=='before_postpass':self.stage.write_bytes(original+b'x');self.stage.write_bytes(original)
        with self.assertRaisesRegex(ValueError,'changed or path was replaced'):self.run_audit(change)

    def test_disabled_production_cli(self):
        import subprocess,sys
        result=subprocess.run([sys.executable,'-I',str(HERE/'audit.py')],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0);self.assertIn('proof of concept',result.stderr.lower())


if __name__=='__main__':unittest.main()
