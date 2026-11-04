#!/usr/bin/env python3
"""Synthetic receipt-chain tests; no aggregate or GPU work."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('parent_pair_plan_tested', HERE / 'plan.py')
plan = importlib.util.module_from_spec(spec); spec.loader.exec_module(plan)


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.plan_path = self.root / 'plan.json'; self.plan_path.write_text('{}')
        self.collection = self.root / 'collection'; self.collection.mkdir()
        self.env = {'PATH': '/usr/bin:/bin'}; self.saved_plan = {'environment': self.env}
        for name in ('worker-supervisor', 'final-supervisor'):
            (self.collection / name).mkdir()
        (self.collection / 'report.json').write_text('{}')
        (self.collection / 'inventory.json').write_text('{}')
        report_sha = plan.sha(self.collection / 'report.json'); inventory_sha = plan.sha(self.collection / 'inventory.json')
        worker = {'status': 'collection_diagnostic_only', 'reportSHA256': report_sha, 'inventorySHA256': inventory_sha}
        (self.collection / 'worker-result.json').write_text(json.dumps(worker))
        hashes = {'planSHA256': plan.sha(self.plan_path), 'workerSHA256': plan.sha(self.collection / 'worker-result.json'),
                  'reportSHA256': report_sha, 'inventorySHA256': inventory_sha}
        final = {'status': 'final_inventory_verified', **hashes}
        (self.collection / 'final-supervisor/client.log').write_text(json.dumps(final))
        (self.collection / 'worker-supervisor/client.log').write_text('')
        clean = {'clientExit': 0, 'timedOut': False, 'remainingWorkersTerminated': False, 'signal': None, 'processGroup': 42}
        for name, function, seconds in (('worker-supervisor', 'worker', 4000), ('final-supervisor', 'final_check', 1200)):
            root = self.collection / name
            (root / 'supervisor-result.json').write_text(json.dumps(clean))
            (root / 'invocation.json').write_text(json.dumps({'argv': plan.collector.worker_command(function),
                                                              'environment': self.env, 'wallSeconds': seconds}))
        with mock.patch.object(plan.collector, 'OUTPUT', self.collection):
            supervisor_hashes = plan.collector.supervisor_hashes()
        self.coordinator = {'status': 'collection_diagnostic_only', **hashes, **supervisor_hashes}
        (self.collection / 'coordinator-result.json').write_text(json.dumps(self.coordinator))
        self.completion = {'planSHA256': hashes['planSHA256'], 'workerSHA256': hashes['workerSHA256']}

    def tearDown(self):
        self.temp.cleanup()

    def check(self):
        with mock.patch.object(plan, 'COLLECTION', self.collection), \
                mock.patch.object(plan.collector, 'OUTPUT', self.collection), \
                mock.patch.object(plan.collector.registration, 'PLAN', self.plan_path):
            return plan.collection_receipts(self.saved_plan, self.completion)

    def test_complete_receipt_chain(self):
        self.assertEqual(self.check()['planSHA256'], self.completion['planSHA256'])

    def test_resealed_but_false_final_status_rejected(self):
        path = self.collection / 'final-supervisor/client.log'
        final = json.loads(path.read_text()); final['status'] = 'failed'; path.write_text(json.dumps(final))
        self.coordinator['finalLogSHA256'] = plan.sha(path)
        (self.collection / 'coordinator-result.json').write_text(json.dumps(self.coordinator))
        with self.assertRaisesRegex(ValueError, 'receipt differs'):
            self.check()

    def test_changed_worker_receipt_or_invocation_rejected(self):
        path = self.collection / 'worker-result.json'
        worker = json.loads(path.read_text()); worker['inventorySHA256'] = '0' * 64; path.write_text(json.dumps(worker))
        with self.assertRaisesRegex(ValueError, 'receipt differs'):
            self.check()


if __name__ == '__main__':
    unittest.main()
