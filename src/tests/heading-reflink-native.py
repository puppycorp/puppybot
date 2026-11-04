#!/usr/bin/env python3
"""Compile/run isolated trainer-copy probe against Btrfs scratch files only."""
import importlib.util
import os
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
S = ROOT / 'datasets/visual-control/chase-v1/levels'
COMPILER = ROOT / 'build/flex/control/compiler'
s = importlib.util.spec_from_file_location('transform', S / 'heading-reflink-source.py')
transform = importlib.util.module_from_spec(s); s.loader.exec_module(transform)
s = importlib.util.spec_from_file_location('overlay_tests', ROOT / 'flex/tests/heading-reflink-overlay.py')
helpers = importlib.util.module_from_spec(s); s.loader.exec_module(helpers)


class NativeCloneTest(unittest.TestCase):
    def test_isolated_compiled_clone_and_failure_paths(self):
        with tempfile.TemporaryDirectory(prefix='heading-trainer-build-') as build, \
                tempfile.TemporaryDirectory(prefix='.heading-trainer-fixture-', dir=P) as scratch:
            work = Path(build); saved = Path(scratch)
            shutil.copytree(ROOT / 'flex', work / 'flex', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            dataset = work / 'flex/control/dataset.flex'; dataset.write_text(transform.transform(dataset.read_text()))
            shutil.copyfile(ROOT / 'flex/tests/heading-reflink-native.flex', work / 'flex/control/reflink-probe.flex')
            binary = work / 'probe'
            subprocess.run([str(COMPILER), str(work / 'flex/control/reflink-probe.flex'), '-o', str(binary)],
                           cwd=ROOT, check=True, timeout=60)
            data = b'PVDATA01' + struct.pack('<qqq', 2, 1, 1) + os.urandom(2 * 21212)
            source, target = saved / 'source', saved / 'target'
            with source.open('wb') as f:
                f.write(data); f.flush(); os.fsync(f.fileno())
            before = helpers.physical_map(source)
            subprocess.run([str(binary), str(source), str(target)], cwd=ROOT, check=True, timeout=20, stdout=subprocess.DEVNULL)
            self.assertEqual(source.read_bytes(), data); self.assertEqual(target.read_bytes(), data)
            self.assertEqual(helpers.physical_map(source), before)
            with target.open('r+b') as f:
                f.seek(4096); f.write(b'changed!'); f.flush(); os.fsync(f.fileno())
            self.assertEqual(source.read_bytes(), data); self.assertNotEqual(target.read_bytes(), data)
            after = target.read_bytes()
            refused = subprocess.run([str(binary), str(source), str(target)], cwd=ROOT, capture_output=True, timeout=20)
            self.assertNotEqual(refused.returncode, 0); self.assertEqual(target.read_bytes(), after)
            foreign = work / 'other-filesystem'; foreign.write_bytes(data)
            if os.stat(foreign).st_dev == os.stat(saved).st_dev:
                self.fail('cross-filesystem refusal test requires /tmp and scratch on different filesystems')
            partial = saved / 'partial'
            failed = subprocess.run([str(binary), str(foreign), str(partial)], cwd=ROOT, capture_output=True, timeout=20)
            self.assertNotEqual(failed.returncode, 0)
            self.assertTrue(partial.exists()); self.assertEqual(partial.stat().st_size, 0)
            self.assertEqual(foreign.read_bytes(), data)
            link = saved / 'source-link'; link.symlink_to(source)
            refused = subprocess.run([str(binary), str(link), str(saved / 'link-target')], cwd=ROOT, capture_output=True, timeout=20)
            self.assertNotEqual(refused.returncode, 0); self.assertFalse((saved / 'link-target').exists())
            # Test-only pause after the source fd and digest are fixed. Rename
            # the path while the native probe is paused; path/FD identity must
            # reject the swap instead of publishing a successful copy.
            text = dataset.read_text()
            anchor = '    let dst=syscall(2,target,0x800c2,384,0,0,0);'
            self.assertEqual(text.count(anchor), 1)
            text = text.replace(anchor, '    pl_print(1,"source-opened\\n");let wait=alloc(16);store64(wait,0);store64(wait+8,500000000);syscall(35,wait,0,0,0,0,0);\n' + anchor)
            dataset.write_text(text); race_binary = work / 'race-probe'
            subprocess.run([str(COMPILER), str(work / 'flex/control/reflink-probe.flex'), '-o', str(race_binary)],
                           cwd=ROOT, check=True, timeout=60)
            race_source, parked, race_target = saved / 'race-source', saved / 'parked', saved / 'race-target'
            race_source.write_bytes(data)
            process = subprocess.Popen([str(race_binary), str(race_source), str(race_target)], cwd=ROOT,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(process.stdout.readline().strip(), 'source-opened')
                race_source.rename(parked); race_source.write_bytes(data)
                _, error = process.communicate(timeout=10)
                self.assertNotEqual(process.returncode, 0, error)
                self.assertTrue(race_target.exists()); self.assertEqual(parked.read_bytes(), data)
            finally:
                if process.poll() is None: process.kill(); process.wait()
            symlink_source, symlink_parked, symlink_target = saved / 'swap-source', saved / 'swap-parked', saved / 'swap-target'
            symlink_source.write_bytes(data)
            process = subprocess.Popen([str(race_binary), str(symlink_source), str(symlink_target)], cwd=ROOT,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(process.stdout.readline().strip(), 'source-opened')
                symlink_source.rename(symlink_parked); symlink_source.symlink_to(symlink_parked)
                _, error = process.communicate(timeout=10)
                self.assertNotEqual(process.returncode, 0, error)
                self.assertEqual(symlink_parked.read_bytes(), data)
            finally:
                if process.poll() is None: process.kill(); process.wait()
            text = transform.transform((ROOT / 'flex/control/dataset.flex').read_text())
            anchor = '    let dstpath=vc_concat("/proc/self/fd/",vc_int(dst));'
            self.assertEqual(text.count(anchor), 1)
            text = text.replace(anchor, '    pl_print(1,"target-opened\\n");let wait=alloc(16);store64(wait,0);store64(wait+8,500000000);syscall(35,wait,0,0,0,0,0);\n' + anchor)
            dataset.write_text(text); target_race_binary = work / 'target-race-probe'
            subprocess.run([str(COMPILER), str(work / 'flex/control/reflink-probe.flex'), '-o', str(target_race_binary)],
                           cwd=ROOT, check=True, timeout=60)
            target_race, target_parked = saved / 'target-race', saved / 'target-parked'
            process = subprocess.Popen([str(target_race_binary), str(source), str(target_race)], cwd=ROOT,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(process.stdout.readline().strip(), 'target-opened')
                target_race.rename(target_parked); target_race.write_bytes(data)
                _, error = process.communicate(timeout=10)
                self.assertNotEqual(process.returncode, 0, error)
                self.assertEqual(source.read_bytes(), data); self.assertEqual(target_parked.read_bytes(), data)
            finally:
                if process.poll() is None: process.kill(); process.wait()


if __name__ == '__main__': unittest.main()
