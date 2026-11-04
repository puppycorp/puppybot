#!/usr/bin/env python3
"""Synthetic whole-process freeze deadline checks."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('outer_freeze_test', HERE / 'launch-freeze.py')
outer = importlib.util.module_from_spec(spec); spec.loader.exec_module(outer)


class OuterFreezeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='outer-freeze-')
        root = Path(self.temp.name); self.output = root / 'outer'; self.inner = root / 'inner'; self.plan = root / 'plan'
        self.patches = [mock.patch.object(outer, 'OUTER', self.output), mock.patch.object(outer, 'P', root),
                        mock.patch.object(outer.freeze, 'MONITOR', self.inner),
                        mock.patch.object(outer.freeze.train, 'MANIFEST', self.plan),
                        mock.patch.object(outer.freeze.train, 'MODEL', root / 'model'),
                        mock.patch.object(outer.freeze.train, 'PACKAGE', root / 'package'),
                        mock.patch.object(outer.base.guard, 'require_dedicated_process'),
                        mock.patch.object(outer.base, 'low_priority', return_value={'cpuNice': 19, 'ioClass': 'idle'}),
                        mock.patch.object(outer.shutil, 'disk_usage', return_value=type('Disk', (), {'free': 50 * 1024**3})()),
                        mock.patch.object(outer.freeze, 'source_pins', side_effect=lambda: {'source': 'hash'})]
        for patch in self.patches: patch.start()

    def tearDown(self):
        for patch in reversed(self.patches): patch.stop()
        self.temp.cleanup()

    def fake_supervisor(self, argv, output, env, timeout):
        self.assertEqual(timeout, 2400); self.assertEqual(output, self.output)
        self.inner.mkdir(); self.plan.write_text('frozen plan')
        (self.inner / 'launch.json').write_text('launch'); (self.inner / 'worker-result.json').write_text('worker')
        receipt = {'status': 'plan_registered_only', 'reason': None, 'planSHA256': outer.freeze.train.sha(self.plan),
                   'launchSHA256': outer.freeze.train.sha(self.inner / 'launch.json'),
                   'workerSHA256': outer.freeze.train.sha(self.inner / 'worker-result.json')}
        (self.inner / 'result.json').write_text(json.dumps(receipt))
        status = {'clientExit': 0, 'signal': None, 'timedOut': False, 'remainingWorkersTerminated': False, 'processGroup': 5}
        (self.output / 'supervisor-result.json').write_text(json.dumps(status))
        return status

    def test_clean_worker_records_plan(self):
        with mock.patch.object(outer.base.hidden, 'supervise', side_effect=self.fake_supervisor): result = outer.launch()
        self.assertEqual(result['status'], 'plan_registered_only')
        self.assertEqual(result['planSHA256'], outer.freeze.train.sha(self.plan))

    def test_existing_and_low_disk_leave_plan_alone(self):
        self.plan.write_text('preserve')
        with self.assertRaises(FileExistsError): outer.launch()
        self.assertEqual(self.plan.read_text(), 'preserve'); self.assertFalse(self.output.exists())
        self.plan.unlink()
        with mock.patch.object(outer.shutil, 'disk_usage', return_value=type('Disk', (), {'free': 35 * 1024**3})()):
            with self.assertRaisesRegex(ValueError, 'disk'): outer.launch()
        self.assertFalse(self.output.exists())

    def test_failed_supervision_retains_receipt(self):
        failed = {'clientExit': 1, 'signal': None, 'timedOut': True, 'remainingWorkersTerminated': True, 'processGroup': 5}
        with mock.patch.object(outer.base.hidden, 'supervise', return_value=failed):
            with self.assertRaises(ValueError): outer.launch()
        self.assertEqual(json.loads((self.output / 'result.json').read_text())['status'], 'failed')
        self.assertTrue((self.output / 'invocation.json').is_file())


if __name__ == '__main__': unittest.main()
