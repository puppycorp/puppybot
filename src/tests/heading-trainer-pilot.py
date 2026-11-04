#!/usr/bin/env python3
"""CPU controls for matched one-epoch trainer pilot comparisons."""
import importlib.util
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
p = ROOT / 'datasets/visual-control/chase-v1/levels/run-heading-trainer-pilot.py'
s = importlib.util.spec_from_file_location('pilot', p); pilot = importlib.util.module_from_spec(s); s.loader.exec_module(pilot)


class PilotTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name); self.parent, self.stock, self.clone = (root / x for x in ('parent','stock','clone'))
        for d in (self.parent, self.stock, self.clone): d.mkdir()
        (self.parent / 'weights.bin').write_bytes(b'weights')
        for d in (self.stock, self.clone):
            (d / 'kernels').mkdir(); (d / 'kernels/a').write_bytes(b'kernel')
            for name in ('initial.bin','first-gradients.bin','first-after.bin','epoch-1.bin','last.bin','weights.bin'):
                (d / name).write_bytes(b'weights')
            for name in ('policy','model.pup','factory.flex'): (d / name).write_bytes(b'file')
            for name in ('first-order.bin','final-order.bin'): (d / name).write_bytes(struct.pack('<34Q', *range(34)))
            (d / 'first-mirror-mask.bin').write_bytes(struct.pack('<Q', 2))
            rows = [{'epoch': n, 'optimizerSteps': 16*n, 'mirroredTrainingSequences': n,
                     'trainingLoss': .5, 'validationLoss': .5, 'selected': False} for n in range(2)]
            (d / 'curves.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))

    def test_same_and_different_weights(self):
        self.assertEqual(pilot.compare_models(self.stock, self.clone, self.parent), [])
        (self.clone / 'first-gradients.bin').write_bytes(b'different')
        self.assertIn('first-gradients.bin', pilot.compare_models(self.stock, self.clone, self.parent))

    def test_identical_invalid_orders_rejected(self):
        for model in (self.stock, self.clone): (model / 'first-order.bin').write_bytes(bytes(34 * 8))
        with self.assertRaises(ValueError): pilot.compare_models(self.stock, self.clone, self.parent)

    def test_extent_parser_rejects_bad_output(self):
        run = mock.Mock(); run.stdout = 'bad data\n'
        with mock.patch.object(pilot.subprocess, 'run', return_value=run):
            with self.assertRaises(ValueError): pilot.extent_numbers(self.stock / 'data.bin')

    def test_comparison_not_published_when_disk_floor_fails(self):
        result = Path(self.tmp.name) / 'result'; result.mkdir()
        with mock.patch.object(pilot, 'RESULT', result), \
             mock.patch.object(pilot.base, 'require_capacity', side_effect=RuntimeError('disk floor')):
            with self.assertRaisesRegex(RuntimeError, 'disk floor'):
                pilot.publish_comparison({'status': 'passed'})
        self.assertFalse((result / 'comparison.json').exists())

    def test_supervisor_status_requires_clean_exact_fields(self):
        result = Path(self.tmp.name) / 'result'; result.mkdir()
        status = {'clientExit': 0, 'signal': None, 'timedOut': False,
                  'remainingWorkersTerminated': False, 'processGroup': 123}
        for arm in ('stock', 'reflink'):
            d = result / f'monitor-{arm}'; d.mkdir()
            (d / 'supervisor-result.json').write_text(json.dumps(status))
        with mock.patch.object(pilot, 'RESULT', result):
            checksums = pilot.supervisor_statuses()
            self.assertEqual(set(checksums), {'stock', 'reflink'})
            for key, value in [('clientExit', True), ('signal', 15), ('timedOut', True),
                               ('remainingWorkersTerminated', True), ('processGroup', 0)]:
                bad = dict(status); bad[key] = value
                (result / 'monitor-stock/supervisor-result.json').write_text(json.dumps(bad))
                with self.subTest(key=key), self.assertRaises(ValueError): pilot.supervisor_statuses()
            bad = dict(status); del bad['signal']
            (result / 'monitor-stock/supervisor-result.json').write_text(json.dumps(bad))
            with self.assertRaises(ValueError): pilot.supervisor_statuses()

    def test_monitored_completion_required_and_bound_to_evidence(self):
        root = Path(self.tmp.name); result = root / 'result'; result.mkdir()
        monitored = root / 'monitor'; monitored.mkdir(); (monitored / 'outer-monitor').mkdir()
        script = root / 'monitor.py'; script.write_text('monitor')
        files = {'comparison': result / 'comparison.json', 'monitorResult': monitored / 'monitor-result.json',
                 'outerSupervisor': monitored / 'outer-monitor/supervisor-result.json',
                 'telemetry': monitored / 'telemetry.jsonl', 'monitorScript': script}
        files['comparison'].write_text('{"status":"passed"}')
        files['monitorResult'].write_text('{"status":"passed"}')
        files['outerSupervisor'].write_text(json.dumps({'clientExit': 0, 'signal': None, 'timedOut': False,
                                                       'remainingWorkersTerminated': False, 'processGroup': 123}))
        files['telemetry'].write_text('{}\n')
        with mock.patch.object(pilot, 'RESULT', result), mock.patch.object(pilot, 'MONITORED', monitored), \
             mock.patch.object(pilot, 'MONITOR_SCRIPT', script):
            with self.assertRaises(FileNotFoundError): pilot.verify_monitored_completion()
            hashes = {key: pilot.base.sha(path) for key, path in files.items()}
            (monitored / 'completion.json').write_text(json.dumps({'status': 'passed', 'hashes': hashes}))
            self.assertEqual(pilot.verify_monitored_completion()['status'], 'passed')
            files['telemetry'].write_text('changed')
            with self.assertRaisesRegex(ValueError, 'receipt differs'): pilot.verify_monitored_completion()


if __name__ == '__main__': unittest.main()
