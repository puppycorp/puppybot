#!/usr/bin/env python3
"""CPU-only freeze supervisor failure/receipt fixtures."""
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('selection_freeze_test', HERE / 'supervise-freeze.py')
s = importlib.util.module_from_spec(spec); spec.loader.exec_module(s)


class FreezeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name); self.monitor = root / 'freeze-monitor'; self.manifest = root / 'plan.json'
        self.output = root / 'output'; self.selection_monitor = root / 'selection-monitor'
        patches = [mock.patch.object(s, 'MONITOR', self.monitor),
                   mock.patch.object(s.selection, 'MANIFEST', self.manifest),
                   mock.patch.object(s.selection, 'OUTPUT', self.output),
                   mock.patch.object(s.selection, 'MONITOR', self.selection_monitor),
                   mock.patch.object(s.base.guard, 'require_dedicated_process'),
                   mock.patch.object(s.base, 'low_priority', return_value={'cpuNice': 19, 'ioClass': 'idle'}),
                   mock.patch.object(s.selection.strict_inventory, 'require_fresh'),
                   mock.patch.object(s, 'source_pins', return_value={'fixture': 'fixed'}),
                   mock.patch.object(s.shutil, 'disk_usage', return_value=shutil._ntuple_diskusage(100*1024**3, 50*1024**3, 50*1024**3))]
        for patch in patches:
            patch.start(); self.addCleanup(patch.stop)

    @staticmethod
    def status():
        return {'clientExit': 0, 'signal': None, 'timedOut': False,
                'remainingWorkersTerminated': False, 'processGroup': 42}

    def test_supervisor_requires_clean_worker_and_matching_plan(self):
        frozen = {'schema': 'puppybot.outbound-five-selection-plan.v1'}
        self.manifest.write_text(json.dumps(frozen))
        def child(command, output, env, seconds):
            output = Path(output); status = self.status()
            (output / 'supervisor-result.json').write_text(json.dumps(status))
            (output / 'worker-result.json').write_text(json.dumps({'status': 'plan_registered_only',
                'planSHA256': s.selection.sha(self.manifest), 'sourcePins': {'fixture': 'fixed'},
                'cpuNice': 19, 'ioClass': 'idle'}))
            return status
        with (mock.patch.object(s.base.hidden, 'supervise', side_effect=child),
              mock.patch.object(s.selection, 'verify', return_value=frozen)):
            result = s.launch()
        self.assertEqual(result['status'], 'plan_registered_only')
        self.assertEqual(json.loads((self.monitor / 'result.json').read_text()), result)
        self.assertEqual(result['planSHA256'], s.selection.sha(self.manifest))

    def test_low_disk_and_existing_monitor_refuse_creation(self):
        with mock.patch.object(s.shutil, 'disk_usage', return_value=shutil._ntuple_diskusage(40*1024**3, 20*1024**3, 20*1024**3)):
            with self.assertRaisesRegex(ValueError, 'disk below'):
                s.launch()
        self.assertFalse(self.monitor.exists())
        self.monitor.mkdir(); (self.monitor / 'keep').write_text('preserved')
        with self.assertRaises(FileExistsError): s.launch()
        self.assertEqual((self.monitor / 'keep').read_text(), 'preserved')

    def test_worker_failure_is_recorded_and_never_overwritten(self):
        failed = dict(self.status(), clientExit=1)
        def child(command, output, env, seconds):
            (Path(output) / 'supervisor-result.json').write_text(json.dumps(failed)); return failed
        with mock.patch.object(s.base.hidden, 'supervise', side_effect=child):
            with self.assertRaisesRegex(ValueError, 'did not exit cleanly'): s.launch()
        self.assertEqual(json.loads((self.monitor / 'result.json').read_text())['status'], 'failed')
        with self.assertRaises(FileExistsError): s.launch()

    def test_worker_requires_priority_and_revalidates(self):
        self.monitor.mkdir(); (self.monitor / 'launch.json').write_text(json.dumps({'sourcePins': {'fixture': 'fixed'}}))
        self.manifest.write_text('{}'); frozen = {'schema': 'puppybot.outbound-five-selection-plan.v1'}
        with (mock.patch.object(s.os, 'getpriority', return_value=19),
              mock.patch.object(s.subprocess, 'run', return_value=SimpleNamespace(stdout='idle\n')),
              mock.patch.object(s.selection, 'freeze', return_value=frozen),
              mock.patch.object(s.selection, 'verify', return_value=frozen)):
            s.worker()
        row = json.loads((self.monitor / 'worker-result.json').read_text())
        self.assertEqual((row['status'], row['cpuNice'], row['ioClass']), ('plan_registered_only', 19, 'idle'))


if __name__ == '__main__': unittest.main()
