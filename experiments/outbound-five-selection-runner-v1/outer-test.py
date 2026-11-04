#!/usr/bin/env python3
"""CPU fixtures for the whole-registration deadline and receipts."""
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('selection_outer_test', HERE / 'launch-freeze.py')
outer = importlib.util.module_from_spec(spec); spec.loader.exec_module(outer)


class OuterTests(unittest.TestCase):
    def test_clean_outer_supervision_and_refusal_to_reuse(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); target = root / 'outer'; inner = root / 'inner'; plan = root / 'plan'
            status = {'clientExit': 0, 'signal': None, 'timedOut': False,
                      'remainingWorkersTerminated': False, 'processGroup': 42}
            def child(command, output, env, seconds):
                self.assertEqual(seconds, outer.WALL_SECONDS)
                (target / 'supervisor-result.json').write_text(json.dumps(status)); inner.mkdir(); plan.write_text('{}')
                (inner / 'launch.json').write_text('{}'); (inner / 'worker-result.json').write_text('{}')
                (inner / 'supervisor-result.json').write_text(json.dumps(status))
                receipt = {'status': 'plan_registered_only', 'reason': None, 'supervisorStatus': status,
                           'supervisorSHA256': outer.freeze.selection.sha(inner / 'supervisor-result.json'),
                           'planSHA256': outer.freeze.selection.sha(plan),
                           'launchSHA256': outer.freeze.selection.sha(inner / 'launch.json'),
                           'workerSHA256': outer.freeze.selection.sha(inner / 'worker-result.json')}
                (inner / 'result.json').write_text(json.dumps(receipt)); return status
            with (mock.patch.object(outer, 'OUTER', target), mock.patch.object(outer.freeze, 'MONITOR', inner),
                  mock.patch.object(outer.freeze.selection, 'MANIFEST', plan),
                  mock.patch.object(outer.base.guard, 'require_dedicated_process'),
                  mock.patch.object(outer.base, 'low_priority', return_value={'cpuNice': 19, 'ioClass': 'idle'}),
                  mock.patch.object(outer.freeze.selection.strict_inventory, 'require_fresh'),
                  mock.patch.object(outer, 'source_pins', return_value={'fixture': 'fixed'}),
                  mock.patch.object(outer.shutil, 'disk_usage', return_value=shutil._ntuple_diskusage(100*1024**3, 50*1024**3, 50*1024**3)),
                  mock.patch.object(outer.base.hidden, 'supervise', side_effect=child)):
                self.assertEqual(outer.launch()['status'], 'plan_registered_only')
                with self.assertRaises(FileExistsError): outer.launch()
                self.assertEqual(json.loads((target / 'result.json').read_text())['status'], 'plan_registered_only')

    def test_timeout_is_preserved_as_failure(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); target = root / 'outer'; inner = root / 'inner'
            status = {'clientExit': None, 'signal': 15, 'timedOut': True,
                      'remainingWorkersTerminated': True, 'processGroup': 42}
            def child(command, output, env, seconds):
                (target / 'supervisor-result.json').write_text(json.dumps(status)); return status
            with (mock.patch.object(outer, 'OUTER', target), mock.patch.object(outer.freeze, 'MONITOR', inner),
                  mock.patch.object(outer.base.guard, 'require_dedicated_process'),
                  mock.patch.object(outer.base, 'low_priority', return_value={}),
                  mock.patch.object(outer.freeze.selection.strict_inventory, 'require_fresh'),
                  mock.patch.object(outer, 'source_pins', return_value={'fixture': 'fixed'}),
                  mock.patch.object(outer.shutil, 'disk_usage', return_value=shutil._ntuple_diskusage(100*1024**3, 50*1024**3, 50*1024**3)),
                  mock.patch.object(outer.base.hidden, 'supervise', side_effect=child)):
                with self.assertRaisesRegex(ValueError, 'not clean'): outer.launch()
                self.assertEqual(json.loads((target / 'result.json').read_text())['status'], 'failed')


if __name__ == '__main__': unittest.main()
