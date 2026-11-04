#!/usr/bin/env python3
"""CPU checks for Btrfs-safe expected HIP mapping identity."""
import ctypes
import importlib.util
import mmap
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT=Path(__file__).resolve().parents[2]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


monitor=load('handoff_process',ROOT/'flex/tests/supervise-handoff-process.py')
base=load('selection_tests',ROOT/'flex/tests/selection-supervisor.py')
base.monitor=monitor;base.TOOL=ROOT/'flex/tests/supervise-handoff-process.py'


class ProcessMonitorTests(base.SupervisorTests):
    def test_executable_path_race_is_not_recorded_as_a_valid_observation(self):
        original=os.readlink;calls=[]
        def stale(path):
            if str(path)==f'/proc/{os.getpid()}/exe':
                calls.append(1)
                if len(calls)==1:return '/stale/previous-executable'
            return original(path)
        with mock.patch.object(monitor.os,'readlink',side_effect=stale):
            with self.assertRaises(monitor.ProcessRace):monitor.observe(os.getpid(),((0,0),0),{},(0,0,0,0))

    def test_real_hip_mapping_identity_and_stat_device(self):
        path=monitor.HIP;identity,signature=monitor.mapping_identity(path)
        with path.open('rb') as stream:
            with mmap.mmap(stream.fileno(),mmap.PAGESIZE,access=mmap.ACCESS_COPY) as view:
                address=ctypes.addressof(ctypes.c_char.from_buffer(view))
                rows=monitor.hip_maps(Path('/proc/self/maps'),identity,signature)
                self.assertTrue(rows);self.assertEqual(identity[1],os.fstat(stream.fileno()).st_ino)
                self.assertGreater(address,0)
                with self.assertRaisesRegex(ValueError,'file identity'):
                    monitor.hip_maps(Path('/proc/self/maps'),identity,(signature[0]+1,*signature[1:]))

    def test_rejects_mapped_inode_even_when_path_matches(self):
        path=self.root/'maps';path.write_text(f'1000-2000 r--p 00000000 00:01 42 {self.hip}\n')
        expected,signature=monitor.mapping_identity(self.hip)
        with self.assertRaisesRegex(ValueError,'unexpected HIP mapping'):monitor.hip_maps(path,expected,signature)
        path.write_text(f'1000-2000 r--p 00000000 {expected[0][0]:02x}:{expected[0][1]:02x} {expected[1]} {self.hip} (deleted)\n')
        with self.assertRaisesRegex(ValueError,'deleted HIP mapping'):monitor.hip_maps(path,expected,signature)


if __name__=='__main__':unittest.main()
