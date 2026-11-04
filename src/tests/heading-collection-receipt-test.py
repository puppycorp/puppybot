#!/usr/bin/env python3
"""CPU-only receipt and downstream gate fixtures for full collection."""
import importlib.util
import json
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
S = ROOT / 'datasets/visual-control/chase-v1/levels'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


r = load('receipt_fixture', S / 'heading-collection-receipt.py')


class ReceiptTest(unittest.TestCase):
    def test_missing_changed_and_unclean_receipt_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp); out = p / 'search-dagger-heading'; out.mkdir()
            mon = p / 'heading-full-collection-monitored-v1'; mon.mkdir(); (mon / 'outer-monitor').mkdir()
            catalogs = p / 'heading-rollin-full-catalogs'; catalogs.mkdir()
            (catalogs / 'catalogs.json').write_text('{}')
            (out / 'inputs.json').write_text('{}'); (out / 'collection-report.json').write_text('{"status":"passed","mode":"full"}')
            (mon / 'monitor-result.json').write_text('{"status":"passed"}'); (mon / 'telemetry.jsonl').write_text('{}\n')
            tests = p / 'flex/tests'; tests.mkdir(parents=True)
            for name in ('monitored-visual-v4-smoke.py', 'run-physical-hidden-trial.py',
                         'run-physical-rescan-trial.py', 'run-physical-hybrid-trial.py'):
                (tests / name).write_text(name)
            collector = p / 'datasets/visual-control/chase-v1/levels'; collector.mkdir(parents=True)
            (collector / 'run-heading-rollin.py').write_text('collector')
            clean = {'clientExit': 0, 'signal': None, 'timedOut': False,
                     'remainingWorkersTerminated': False, 'processGroup': 123}
            (mon / 'outer-monitor/supervisor-result.json').write_text(json.dumps(clean))
            wrapper = p / 'wrapper.py'; wrapper.write_text('wrapper')
            for arm in ('control', 'treatment'):
                for i in range(4):
                    root = out / f'{arm}-L5'; shard = root / f'shard-{i}'; shard.mkdir(parents=True)
                    monitor = root / f'monitor-{i}'; monitor.mkdir()
                    (monitor / 'supervisor-result.json').write_text(json.dumps(clean))
                    for name in ('data.bin', 'map.bin', 'report.json'): (shard / name).write_bytes(b'fixture')
                    policy = shard / 'policy'; (policy / 'kernels').mkdir(parents=True)
                    for name in ('weights.bin', 'policy', 'receipt.json', 'kernels/kernel'): (policy / name).write_bytes(b'fixture')
                    for episode in range(32):
                        game = shard / f'expert-{episode}'; (game / 'scene').mkdir(parents=True)
                        for name in ('result.json', 'decisions.jsonl', 'chase.jsonl', 'scene/case.json', 'scene/environment.bin'):
                            (game / name).write_bytes(b'fixture')
            with mock.patch.object(r, 'ROOT', p), mock.patch.object(r, 'P', p), mock.patch.object(r, 'OUTPUT', out), \
                 mock.patch.object(r, 'MONITORED', mon), mock.patch.object(r, 'MONITOR_SCRIPT', wrapper):
                with self.assertRaises(FileNotFoundError): r.verify()
                (mon / 'launch.json').write_text(json.dumps({'sourcePins': r.source_pins()}))
                (mon / 'completion.json').write_text(json.dumps({'status': 'passed', 'hashes': r.snapshot()}))
                self.assertEqual(r.verify()['status'], 'passed')
                (tests / 'monitored-visual-v4-smoke.py').write_text('tampered telemetry')
                with self.assertRaisesRegex(ValueError, 'receipt differs'): r.verify()
                (tests / 'monitored-visual-v4-smoke.py').write_text('monitored-visual-v4-smoke.py')
                target = out / 'control-L5/shard-0/data.bin'; target.write_bytes(b'altered')
                with self.assertRaisesRegex(ValueError, 'receipt differs'): r.verify()
                target.write_bytes(b'fixture')
                trace = out / 'control-L5/shard-0/expert-0/decisions.jsonl'; trace.write_bytes(b'altered')
                with self.assertRaisesRegex(ValueError, 'receipt differs'): r.verify()
                trace.write_bytes(b'fixture')
                trace.unlink()
                with self.assertRaises(FileNotFoundError): r.verify()
                trace.write_bytes(b'fixture')
                optional = out / 'control-L5/shard-0/expert-0/native.log'; optional.write_text('timeout')
                with self.assertRaisesRegex(ValueError, 'receipt differs'): r.verify()
                optional.unlink()
                kernel = out / 'control-L5/shard-0/policy/kernels/kernel'; kernel.write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError, 'receipt differs'): r.verify()
                kernel.write_bytes(b'fixture')
                dirty = dict(clean); dirty['timedOut'] = True
                (out / 'treatment-L5/monitor-3/supervisor-result.json').write_text(json.dumps(dirty))
                with self.assertRaisesRegex(ValueError, 'unclean supervisor'): r.verify()

    def test_all_downstream_entrypoints_gate_before_mutation(self):
        for name in ('prepare-heading-overlays.py', 'verify-heading-overlay-pair.py', 'run-heading-training.py'):
            with self.subTest(name=name):
                module = load(name, S / name)
                base = module.rollin.base if hasattr(module, 'rollin') else module.base
                with mock.patch.object(module.sys, 'argv', [name]), \
                     mock.patch.object(base, 'acquire_lock', return_value=nullcontext()), \
                     mock.patch.object(module.collection_receipt, 'verify', side_effect=ValueError('missing monitor')), \
                     mock.patch.object(module.os, 'chdir', create=True):
                    with self.assertRaisesRegex(ValueError, 'missing monitor'): module.main()

    def test_changed_post_training_evidence_blocks_report(self):
        module = load('training', S / 'run-heading-training.py')
        with mock.patch.object(module.collection_receipt, 'verify', side_effect=ValueError('changed collection evidence')), \
             mock.patch.object(module.builder.pair, 'publish_new') as publish:
            with self.assertRaisesRegex(ValueError, 'changed collection evidence'):
                module.publish_training_report({'status': 'training_diagnostic_only'})
            publish.assert_not_called()


if __name__ == '__main__': unittest.main()
