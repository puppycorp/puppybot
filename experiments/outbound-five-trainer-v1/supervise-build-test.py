#!/usr/bin/env python3
"""Synthetic tests for low-priority trainer build supervision."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('outbound_trainer_supervise_test', HERE / 'supervise-build.py')
supervise = importlib.util.module_from_spec(spec); spec.loader.exec_module(supervise)


class SupervisorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='outbound-build-supervisor-')
        root = Path(self.temp.name); self.output = root / 'build'; self.monitor = root / 'monitor'; self.lock = root / 'lock'
        self.lock.write_text('')
        self.patches = [mock.patch.object(supervise.builder, 'DEFAULT', self.output),
                        mock.patch.object(supervise, 'MONITOR', self.monitor), mock.patch.object(supervise, 'LOCK', self.lock),
                        mock.patch.object(supervise.base.guard, 'require_dedicated_process'),
                        mock.patch.object(supervise.base, 'low_priority', return_value={'cpuNice': 19, 'ioClass': 'idle'}),
                        mock.patch.object(supervise.shutil, 'disk_usage', return_value=type('Disk', (), {'free': 50 * 1024**3})()),
                        mock.patch.object(supervise, 'source_pins', return_value={'source': 'hash'}),
                        mock.patch.object(supervise.builder, 'verify', return_value={'binaries': {'control': 'a', 'trainer': 'b'}})]
        for patch in self.patches: patch.start()

    def tearDown(self):
        for patch in reversed(self.patches): patch.stop()
        self.temp.cleanup()

    def fake_supervise(self, argv, output, env, timeout):
        self.output.mkdir(); (self.output / 'build.json').write_text('{}')
        status = {'clientExit': 0, 'signal': None, 'timedOut': False, 'remainingWorkersTerminated': False, 'processGroup': 5}
        (self.monitor / 'supervisor-result.json').write_text(json.dumps(status))
        worker = {'status': 'isolated_build_only', 'sourcePins': {'source': 'hash'},
                  'buildSHA256': supervise.builder.sha(self.output / 'build.json'),
                  'binaries': {'control': 'a', 'trainer': 'b'}, 'cpuNice': 19, 'ioClass': 'idle'}
        (self.monitor / 'worker-result.json').write_text(json.dumps(worker))
        return status

    def test_clean_build_emits_receipt(self):
        with mock.patch.object(supervise.base.hidden, 'supervise', side_effect=self.fake_supervise):
            result = supervise.launch()
        self.assertEqual(result['status'], 'isolated_build_only')
        self.assertEqual(result['launchSHA256'], supervise.builder.sha(self.monitor / 'launch.json'))
        self.assertEqual(result['workerSHA256'], supervise.builder.sha(self.monitor / 'worker-result.json'))
        self.assertEqual(result['buildSHA256'], supervise.builder.sha(self.output / 'build.json'))

    def test_existing_output_and_low_disk_fail_before_creation(self):
        self.output.mkdir()
        with self.assertRaises(FileExistsError): supervise.launch()
        self.assertFalse(self.monitor.exists())
        self.output.rmdir()
        with mock.patch.object(supervise.shutil, 'disk_usage', return_value=type('Disk', (), {'free': 35 * 1024**3})()):
            with self.assertRaisesRegex(ValueError, 'disk'): supervise.launch()
        self.assertFalse(self.output.exists()); self.assertFalse(self.monitor.exists())

    def test_failed_child_is_retained_and_not_accepted(self):
        def failed(*_):
            return {'clientExit': 1, 'signal': None, 'timedOut': False, 'remainingWorkersTerminated': False, 'processGroup': 5}
        with mock.patch.object(supervise.base.hidden, 'supervise', side_effect=failed):
            with self.assertRaises(ValueError): supervise.launch()
        self.assertEqual(json.loads((self.monitor / 'result.json').read_text())['status'], 'failed')
        self.assertTrue((self.monitor / 'launch.json').is_file())


if __name__ == '__main__':
    unittest.main()
