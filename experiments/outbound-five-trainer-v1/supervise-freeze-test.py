#!/usr/bin/env python3
"""Synthetic low-priority freeze supervisor checks."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('outbound_freeze_supervisor_test', HERE / 'supervise-freeze.py')
supervise = importlib.util.module_from_spec(spec); spec.loader.exec_module(supervise)


class FreezeSupervisorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='outbound-freeze-supervisor-')
        root = Path(self.temp.name); self.monitor = root / 'monitor'; self.plan = root / 'plan.json'; self.lock = root / 'lock'
        self.lock.write_text(''); self.frozen = {'inputs': {'a': 1}}
        self.patches = [mock.patch.object(supervise, 'P', root), mock.patch.object(supervise, 'MONITOR', self.monitor),
                        mock.patch.object(supervise, 'LOCK', self.lock), mock.patch.object(supervise.train, 'MANIFEST', self.plan),
                        mock.patch.object(supervise.train, 'MODEL', root / 'model'), mock.patch.object(supervise.train, 'PACKAGE', root / 'package'),
                        mock.patch.object(supervise.train, 'inputs', return_value=self.frozen['inputs']),
                        mock.patch.object(supervise.train, 'verify_manifest', return_value=self.frozen),
                        mock.patch.object(supervise.base.guard, 'require_dedicated_process'),
                        mock.patch.object(supervise.base, 'low_priority', return_value={'cpuNice': 19, 'ioClass': 'idle'}),
                        mock.patch.object(supervise.shutil, 'disk_usage', return_value=type('Disk', (), {'free': 50 * 1024**3})()),
                        mock.patch.object(supervise, 'source_pins', return_value={'source': 'hash'})]
        for patch in self.patches: patch.start()

    def tearDown(self):
        for patch in reversed(self.patches): patch.stop()
        self.temp.cleanup()

    def fake_worker(self, argv, output, env, timeout):
        self.plan.write_text(json.dumps(self.frozen))
        status = {'clientExit': 0, 'signal': None, 'timedOut': False, 'remainingWorkersTerminated': False, 'processGroup': 5}
        (self.monitor / 'supervisor-result.json').write_text(json.dumps(status))
        launch = json.loads((self.monitor / 'launch.json').read_text())
        result = {'status': 'plan_registered_only', 'sourcePins': {'source': 'hash'},
                  'planSHA256': supervise.train.sha(self.plan), 'inputsSHA256': launch['inputsSHA256'],
                  'cpuNice': 19, 'ioClass': 'idle'}
        (self.monitor / 'worker-result.json').write_text(json.dumps(result))
        return status

    def test_clean_worker_records_exact_plan_and_inputs(self):
        with mock.patch.object(supervise.base.hidden, 'supervise', side_effect=self.fake_worker):
            result = supervise.launch()
        self.assertEqual(result['status'], 'plan_registered_only')
        self.assertEqual(result['planSHA256'], supervise.train.sha(self.plan))
        self.assertEqual(result['inputsSHA256'], supervise.train.hashlib_json(self.frozen['inputs']))

    def test_existing_plan_and_low_disk_never_overwrite(self):
        self.plan.write_text('preserve')
        with self.assertRaises(FileExistsError): supervise.launch()
        self.assertEqual(self.plan.read_text(), 'preserve'); self.assertFalse(self.monitor.exists())
        self.plan.unlink()
        with mock.patch.object(supervise.shutil, 'disk_usage', return_value=type('Disk', (), {'free': 35 * 1024**3})()):
            with self.assertRaisesRegex(ValueError, 'disk'): supervise.launch()
        self.assertFalse(self.plan.exists()); self.assertFalse(self.monitor.exists())

    def test_worker_failure_keeps_partial_monitor(self):
        failed = {'clientExit': 1, 'signal': None, 'timedOut': False, 'remainingWorkersTerminated': False, 'processGroup': 5}
        with mock.patch.object(supervise.base.hidden, 'supervise', return_value=failed):
            with self.assertRaises(ValueError): supervise.launch()
        self.assertEqual(json.loads((self.monitor / 'result.json').read_text())['status'], 'failed')
        self.assertTrue((self.monitor / 'launch.json').is_file())


if __name__ == '__main__':
    unittest.main()
