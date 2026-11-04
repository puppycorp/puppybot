#!/usr/bin/env python3
"""CPU-only archived simulator parser and v4 case transformation tests."""
import importlib.util
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT=Path(__file__).resolve().parents[2]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result
preflight=module('preflight',ROOT/'flex/tests/physical-case-preflight.py')
plan=module('plan',ROOT/'flex/tests/prepare-sim-visual-validation-v4.py')
reset=module('reset',ROOT/'flex/tests/physical-reset-preflight.py')
BASE=ROOT/'build/flex/sim/levels-v2/pitch82'
PILOT=BASE/'physical-visual-stop-pair-v1';V3=BASE/'visual-stop-validation-inputs-v3';V4=BASE/'visual-stop-validation-inputs-v4'


class CompatibilityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (PILOT/'inputs.json').is_file() or not (V3/'conditions.json').is_file() or not (V4/'conditions.json').is_file():
            raise AssertionError('required frozen pilot/v3/v4 evidence fixtures are unavailable')
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name);cls.probe=preflight.build_probe(PILOT,cls.root/'probe')
        cls.reset_probe,cls.asset=reset.build_probe(PILOT,cls.root/'reset')

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def test_all_v3_and_v4_modes_through_archived_parser(self):
        report=json.loads((V4/'conditions.json').read_text());self.assertEqual(len(report['conditions']),12)
        for row in report['conditions']:
            name=row['name'];old=preflight.check(self.probe,V3/name/'case.json',V3/name/'environment.bin')
            new=preflight.check(self.probe,V4/name/'case.json',V4/name/'environment.bin')
            self.assertEqual(old['accepted'],not name.startswith('room-'),name)
            self.assertTrue(new['accepted'],(name,new))
            self.assertEqual((V3/name/'environment.bin').read_bytes(),(V4/name/'environment.bin').read_bytes())
            if name.startswith('room-'):plan.verify_transformation((V3/name/'case.json').read_bytes(),(V4/name/'case.json').read_bytes())
            else:self.assertEqual((V3/name/'case.json').read_bytes(),(V4/name/'case.json').read_bytes())

    def test_bad_controllers_schema_and_environment_are_rejected(self):
        case=json.loads((V4/'room-13/case.json').read_text());env=V4/'room-13/environment.bin';bad=self.root/'case.json'
        for key,value in (('controller','rgb-find-return'),('controller','other'),('controller',None),('schema','not-a-case')):
            current=dict(case)
            if value is None:current.pop(key,None)
            else:current[key]=value
            bad.write_text(json.dumps(current));self.assertFalse(preflight.check(self.probe,bad,env)['accepted'],(key,value))
        bad.write_text(json.dumps(case));bad_env=self.root/'bad.bin';bad_env.write_bytes(b'PBENV001')
        self.assertEqual(preflight.check(self.probe,bad,bad_env)['returnCode'],4)

    def test_actual_cpu_reset_accepts_rooms_and_rejects_spawn_inside_wall(self):
        for layout in (13,15,17):
            scene=V4/f'room-{layout}'
            self.assertTrue(reset.check(self.reset_probe,self.asset,scene/'case.json',scene/'environment.bin')['accepted'])
        scene=V4/'room-13';raw=bytearray((scene/'environment.bin').read_bytes());count=struct.unpack_from('<q',raw,8)[0]
        for i in range(count):
            at=256+i*128;name=raw[at:at+48].split(b'\0')[0]
            if name==b'Wall.partition-a':
                x,y=struct.unpack_from('<2d',raw,at+48);struct.pack_into('<3d',raw,96,x,y,0);break
        else:self.fail('expected partition not found')
        colliding=self.root/'colliding.bin';colliding.write_bytes(raw)
        failed=reset.check(self.reset_probe,self.asset,scene/'case.json',colliding)
        self.assertFalse(failed['accepted']);self.assertEqual(failed['returnCode'],6,failed)

    def test_only_controller_change_is_allowed(self):
        source=(V3/'room-13/case.json').read_bytes();derived=json.loads(plan.adapt(source))
        derived['objects'][0]['position'][0]+=.1
        with self.assertRaisesRegex(ValueError,'beyond controller'):plan.verify_transformation(source,json.dumps(derived).encode())
        derived=json.loads(plan.adapt(source));derived['container']['position'][1]+=.1
        with self.assertRaisesRegex(ValueError,'beyond controller'):plan.verify_transformation(source,json.dumps(derived).encode())
        source_data=json.loads(source);source_data['schema']='bad'
        with self.assertRaises(ValueError):plan.adapt(json.dumps(source_data).encode())

    def test_refuses_overwrite_and_changed_archived_source(self):
        with self.assertRaisesRegex(ValueError,'destination exists'):plan.prepare(PILOT,V3,V4)
        original=preflight.sha;target=PILOT/'inputs/flex-source/sim/main.flex'
        with mock.patch.object(preflight,'sha',side_effect=lambda p:'0'*64 if Path(p)==target else original(Path(p))):
            with self.assertRaisesRegex(ValueError,'archived simulator input changed'):preflight.validate_archive(PILOT)


if __name__=='__main__':unittest.main()
