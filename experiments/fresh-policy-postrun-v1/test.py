#!/usr/bin/env python3
"""CPU fixtures for the read-only catalog-aware postrun verifier."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('postrun', HERE / 'verify.py')
postrun = importlib.util.module_from_spec(spec)
spec.loader.exec_module(postrun)


def fixture(root):
    root = Path(root); scenes = root / 'scenes'; output = root / 'output'
    scenes.mkdir(); output.mkdir(); tasks = []
    for level in range(1, 6):
        rows = []
        for i in range(32):
            layout = 13 + 2 * (i % 3) if level >= 4 else 12 + i % 6
            scene = scenes / str(layout) / str(i % 16)
            scene.mkdir(parents=True, exist_ok=True)
            rows.append({'index': i, 'scene': str(scene), 'layout': layout, 'variant': i % 16})
        tasks.append({'name': f'L{level}', 'level': level, 'rows': rows})
    frozen = {'design': {'tasks': tasks, 'gamesPerArmPerLevel': 32}}
    expected = postrun.expected_catalogs(frozen)
    for relative, target in expected.items():
        link = output / relative
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target, target_is_directory=True)
    (output / 'report.json').write_text('{"status":"diagnostic_only"}\n')
    return output, expected, frozen


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output, self.expected, self.frozen = fixture(self.temp.name)

    def test_exact_catalogs_are_counted_without_traversal(self):
        target = Path(next(iter(self.expected.values())))
        (target / 'outside-output').write_text('not part of output')
        actual = postrun.inventory(self.output, self.expected)
        self.assertEqual(len(actual['links']), 160)
        self.assertEqual(set(actual['files']), {'report.json'})
        self.assertEqual(postrun.sha_json(actual), postrun.sha_json(postrun.inventory(self.output, self.expected)))

    def test_missing_retargeted_and_replaced_links_rejected(self):
        relative = next(iter(self.expected)); path = self.output / relative
        path.unlink()
        with self.assertRaisesRegex(ValueError, 'missing expected'):
            postrun.inventory(self.output, self.expected)
        path.symlink_to(self.output, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'retargeted'):
            postrun.inventory(self.output, self.expected)
        path.unlink(); path.mkdir()
        with self.assertRaisesRegex(ValueError, 'not a link'):
            postrun.inventory(self.output, self.expected)

    def test_unexpected_directory_and_file_links_rejected(self):
        for name, target, directory in (('rogue-dir', self.output, True),
                                        ('rogue-file', self.output / 'report.json', False)):
            path = self.output / name
            path.symlink_to(target, target_is_directory=directory)
            with self.assertRaisesRegex(ValueError, 'unexpected'):
                postrun.inventory(self.output, self.expected)
            path.unlink()

    def test_bad_design_rejected(self):
        self.frozen['design']['tasks'][0]['rows'][0]['index'] = 1
        with self.assertRaisesRegex(ValueError, 'unordered'):
            postrun.expected_catalogs(self.frozen)

    def test_nonregular_file_rejected(self):
        os.mkfifo(self.output / 'fifo')
        with self.assertRaisesRegex(ValueError, 'unsupported'):
            postrun.inventory(self.output, self.expected)

    def test_changed_regular_file_changes_inventory(self):
        before = postrun.inventory(self.output, self.expected)
        (self.output / 'report.json').write_text('{"changed":true}\n')
        self.assertNotEqual(before, postrun.inventory(self.output, self.expected))

    def test_audit_retains_failed_monitor_and_rejects_changed_inventory(self):
        monitor = Path(self.temp.name) / 'monitor'; (monitor / 'outer-monitor').mkdir(parents=True)
        (monitor / 'frozen-manifest.json').write_text(json.dumps(self.frozen))
        (monitor / 'monitor-result.json').write_text(json.dumps(
            {'status': 'failed', 'reason': 'unsafe or vanished output directory'}))
        (monitor / 'outer-monitor/supervisor-result.json').write_text(json.dumps(
            {'clientExit': 1, 'signal': None, 'timedOut': False, 'remainingWorkersTerminated': False}))
        saved = {'status': 'diagnostic_only'}
        files = {'directories': ['.'], 'links': self.expected, 'files': {'report.json': {'sha256': 'x', 'size': 1}}}
        with (mock.patch.object(postrun.retry, 'MONITOR', monitor),
              mock.patch.object(postrun.retry, 'OUTPUT', self.output),
              mock.patch.object(postrun.retry, 'verify', return_value=self.frozen),
              mock.patch.object(postrun.retry.base, 'reaudit', return_value=saved),
              mock.patch.object(postrun.retry.base.monitor, 'verify_logs'),
              mock.patch.object(postrun, 'monitor_snapshot', return_value={'log': 'unchanged'}),
              mock.patch.object(postrun, 'inventory', side_effect=[files, files])):
            result = postrun.audit()
        self.assertEqual(result['status'], 'postrun_consistent_original_monitor_failed')
        self.assertEqual(result['originalMonitor']['status'], 'failed')
        changed = {**files, 'files': {}}
        with (mock.patch.object(postrun.retry, 'MONITOR', monitor),
              mock.patch.object(postrun.retry, 'OUTPUT', self.output),
              mock.patch.object(postrun.retry, 'verify', return_value=self.frozen),
              mock.patch.object(postrun.retry.base, 'reaudit', return_value=saved),
              mock.patch.object(postrun.retry.base.monitor, 'verify_logs'),
              mock.patch.object(postrun, 'monitor_snapshot', return_value={'log': 'unchanged'}),
              mock.patch.object(postrun, 'inventory', side_effect=[files, changed])):
            with self.assertRaisesRegex(ValueError, 'changed during'):
                postrun.audit()


if __name__ == '__main__':
    unittest.main()
