#!/usr/bin/env python3
"""Compile the real isolated transform and exercise it with CPU-only states."""
import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
COMPILER=ROOT/'build/flex/control/compiler'


class NativeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name);source=cls.root/'flex'
        shutil.copytree(ROOT/'flex',source,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        spec=importlib.util.spec_from_file_location('hys_transform',HERE/'transform.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        chase=source/'control/chase.flex';main=source/'control/main.flex'
        c,m=module.transform(chase.read_text(),main.read_text());chase.write_text(c);main.write_text(m)
        probe=source/'control/hysteresis-test-probe.flex';shutil.copyfile(HERE/'native-test-probe.flex',probe)
        cls.binary=cls.root/'probe';subprocess.run([str(COMPILER),str(probe),'-o',str(cls.binary)],check=True,timeout=120,cwd=ROOT,capture_output=True,text=True)
        cls.control=cls.root/'control';subprocess.run([str(COMPILER),str(main),'-o',str(cls.control)],check=True,timeout=120,cwd=ROOT,capture_output=True,text=True)

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def test_native_gate_and_bounded_actions(self):
        for mode in ('normal','inside-distance','at-distance','turn','at-turn','inside-turn','five-flips','six-flips','zero-history','negative-zero-history','subnormal-history','zero-action','carry-history','contact-history','no-kick','current-contact','cancel-contact','cancel-carry'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory(dir=self.root) as d:
                result=subprocess.run([str(self.binary),mode,d],capture_output=True,text=True,timeout=10)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_hysteresis_requires_kick_and_rejects_duplicate_flag(self):
        for flags in (['--steer-hysteresis'],['--steer-hysteresis','--steer-probe-control'],['--steer-hysteresis','--steer-hysteresis']):
            with self.subTest(flags=flags):
                result=subprocess.run([str(self.control),'run','--output',str(self.root/'invalid-output')]+flags,capture_output=True,text=True,timeout=10,cwd=ROOT)
                self.assertNotEqual(result.returncode,0)
                self.assertTrue('hysteresis requires kick mode' in result.stderr or 'duplicate hysteresis' in result.stderr,result.stderr)

    def test_stale_feedback_fails_closed(self):
        for mode in ('stale','truth-source'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory(dir=self.root) as d:
                result=subprocess.run([str(self.binary),mode,d],capture_output=True,text=True,timeout=10)
                self.assertNotEqual(result.returncode,0)


if __name__=='__main__':unittest.main()
