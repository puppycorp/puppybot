#!/usr/bin/env python3
"""Btrfs scratch-only tests for the narrow dedupe mechanics."""
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

root = Path(__file__).resolve().parents[2]
p = root / 'datasets/visual-control/chase-v1/levels/dedupe-heading-prereq.py'
spec = importlib.util.spec_from_file_location('dedupe', p)
dedupe = importlib.util.module_from_spec(spec); spec.loader.exec_module(dedupe)


class DedupeTest(unittest.TestCase):
    def test_rejects_sandbox_pid_namespace(self):
        dedupe.verify_host_visibility('pid:[4026531836]', 'pid:[4026531836]', 'systemd', 0, ['123'], 0)
        for values in [('pid:[4026533316]', 'pid:[4026533316]', 'codex', 1000, ['1'], 0),
                       ('pid:[4026531836]', 'pid:[4026531836]', 'systemd', 0, ['5', '1'], 0),
                       ('pid:[4026531836]', 'pid:[4026531836]', 'codex', 0, ['1'], 0),
                       ('pid:[4026531836]', 'pid:[4026531836]', 'systemd', 0, ['1'], 1000)]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                dedupe.verify_host_visibility(*values)

    def test_equal_and_different_scratch_files(self):
        with tempfile.TemporaryDirectory(prefix='.dedupe-test-', dir=dedupe.P) as tmp:
            a, b, c = (Path(tmp) / n for n in ('a', 'b', 'c'))
            data = os.urandom(2 * 1024 * 1024 + 32); a.write_bytes(data); b.write_bytes(data)
            different = bytearray(data); different[1234] ^= 1; c.write_bytes(different)
            with mock.patch.object(dedupe, 'SIZE', len(data)):
                with a.open('rb') as x, b.open('r+b') as y:
                    self.assertEqual(dedupe.dedupe(x, y), len(data))
                self.assertEqual(a.read_bytes(), data); self.assertEqual(b.read_bytes(), data)
                with a.open('rb') as x, c.open('r+b') as y:
                    with self.assertRaises(ValueError): dedupe.dedupe(x, y)
                self.assertEqual(c.read_bytes(), different)

    def test_detects_open_file(self):
        with tempfile.TemporaryDirectory(prefix='.dedupe-test-', dir=dedupe.P) as tmp:
            target = Path(tmp) / 'target'; target.write_bytes(b'x')
            program = 'import sys,time; f=open(sys.argv[1],"rb"); print("ready",flush=True); time.sleep(30)'
            child = subprocess.Popen([sys.executable, '-c', program, str(target)], stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(child.stdout.readline().strip(), 'ready')
                st = target.stat()
                with self.assertRaises(ValueError): dedupe.process_check([target], [(st.st_dev, st.st_ino)])
            finally:
                child.terminate(); child.wait(timeout=5); child.stdout.close()
            dedupe.process_check([target], [(st.st_dev, st.st_ino)])


if __name__ == '__main__': unittest.main()
