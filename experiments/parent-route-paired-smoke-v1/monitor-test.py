#!/usr/bin/env python3
"""CPU-only resource and stop-path tests for the disabled smoke monitor."""
import importlib.util
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('monitor', HERE / 'monitor.py')
monitor = importlib.util.module_from_spec(spec); spec.loader.exec_module(monitor)


class Checks(unittest.TestCase):
    def test_full_copy_reservation(self):
        size = 6564583232; needed = 34 * monitor.GIB + size + monitor.HEADROOM
        self.assertEqual(monitor.reserve(needed, size)['requiredBytes'], needed)
        with self.assertRaises(ValueError): monitor.reserve(needed - 1, size)
        with self.assertRaises(ValueError): monitor.reserve(needed, 0)

    def test_idle_baseline_and_faults(self):
        rows = [{'monotonicSeconds': float(i), 'phase': 'baseline', 'busyPercent': 0,
                 'totalBytes': 10 * monitor.GIB, 'usedBytes': monitor.GIB, 'freeBytes': 9 * monitor.GIB}
                for i in range(31)]
        monitor.check_baseline(rows)
        missing = rows[:5] + rows[8:]
        with self.assertRaises(ValueError): monitor.check_baseline(missing)
        busy = [dict(row, busyPercent=80) for row in rows]
        with self.assertRaises(ValueError): monitor.check_baseline(busy)
        low = [dict(row, freeBytes=monitor.GIB, usedBytes=9 * monitor.GIB) for row in rows]
        with self.assertRaises(ValueError): monitor.check_baseline(low)

    def test_second_reservation_failure_retains_first_and_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); output = root / 'output'; output.mkdir(); data = root / 'data'
            for arm in ('control', 'treatment'):
                (data / arm).mkdir(parents=True); (data / arm / 'data.bin').write_bytes(b'x')
            planfile = root / 'plan'; planfile.write_text('{}')
            status = {'clientExit': 0, 'signal': None, 'timedOut': False,
                      'remainingWorkersTerminated': False, 'processGroup': 7}
            called = []
            def supervise(argv, directory, env, seconds):
                called.append(argv); (directory / 'supervisor-result.json').write_text(json.dumps(status))
                (output / 'control').mkdir(); (output / 'control/evidence').write_text('retained')
                return status
            free = [40 * monitor.GIB] * 3 + [34 * monitor.GIB] * 3
            with mock.patch.object(monitor.plan, 'OUTPUT', output), mock.patch.object(monitor.plan, 'DATA', data), \
                    mock.patch.object(monitor.plan, 'PLAN', planfile), mock.patch.object(monitor.plan, 'ROOT', root), \
                    mock.patch.object(monitor.plan, 'verify', return_value={'fixed': True}), \
                    mock.patch.object(monitor.plan, 'command', side_effect=lambda arm: [arm]), \
                    mock.patch.object(monitor.plan.design, 'parent_receipt', return_value={}), \
                    mock.patch.object(monitor, 'baseline'), mock.patch.object(monitor.audit, 'audit_model'), \
                    mock.patch.object(monitor.hidden, 'supervise', side_effect=supervise), \
                    mock.patch.object(monitor.shutil, 'disk_usage', side_effect=[SimpleNamespace(free=n) for n in free]):
                with self.assertRaises(ValueError): monitor.coordinator()
            self.assertEqual(called, [['control']])
            self.assertEqual((output / 'control/evidence').read_text(), 'retained')
            self.assertFalse((output / 'treatment').exists())

    def test_copy_evidence_rejects_hardlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / 'data/control'; target = root / 'output/control'
            source.mkdir(parents=True); target.mkdir(parents=True)
            (source / 'data.bin').write_bytes(b'paired data'); (target / 'data.bin').write_bytes(b'paired data')
            digest = hashlib.sha256(b'paired data').hexdigest()
            fake = SimpleNamespace(stdout='Total Exclusive Shared Filename\n4096 0 4096 a\n4096 0 4096 b\n')
            with mock.patch.object(monitor.plan, 'DATA', root / 'data'), \
                    mock.patch.object(monitor.plan, 'OUTPUT', root / 'output'), \
                    mock.patch.dict(monitor.audit.DATA, {'control': digest}), \
                    mock.patch.object(monitor.subprocess, 'run', return_value=fake):
                evidence = monitor.clone_evidence('control')
                self.assertNotEqual(evidence['sourceInode'], evidence['targetInode'])
                (target / 'data.bin').unlink(); os.link(source / 'data.bin', target / 'data.bin')
                with self.assertRaises(ValueError): monitor.clone_evidence('control')


if __name__ == '__main__': unittest.main()
