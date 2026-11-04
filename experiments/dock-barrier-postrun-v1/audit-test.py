#!/usr/bin/env python3
"""CPU-only checks for offset-aware postrun trace analysis."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('postrun_audit', HERE / 'audit.py')
audit = importlib.util.module_from_spec(spec); spec.loader.exec_module(audit)


def state(waits=0, frame=-1, tick=-1, wall=-1):
    return {'waits': waits, 'lastFrameId': frame, 'lastWorkerCompleteTick': tick,
            'lastWallMs': wall, 'failures': 0}


def row(step, barrier, frame=0, offset=1280):
    return {'step': step, 'totalSteps': step, 'timeMs': step * 20 + offset,
            'discovery': {'workerBarrier': barrier, 'mapFrameId': frame}}


class PostrunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='barrier-postrun-test-'); self.addCleanup(self.temp.cleanup)
        self.trace = Path(self.temp.name) / 'trace.jsonl'
        self.records = [row(1, state()), row(2, state()), row(3, state(1, 2, 3, 800), 2)]

    def inspect(self, records):
        self.trace.write_text(''.join(json.dumps(item) + '\n' for item in records))
        return audit.barrier(self.trace)

    def test_constant_nonzero_offset_and_validated_map(self):
        report = self.inspect(self.records)
        self.assertEqual(report['status'], 'complete'); self.assertEqual(report['clockOffsetMs'], 1280)
        self.assertEqual(report['waits'][0]['mapAppliedTick'], 3)
        self.assertEqual(report['waits'][0]['wallMs'], 800)

    def test_changing_offset(self):
        records = list(self.records); records[2] = row(3, state(1, 2, 3, 800), 2, 1281)
        self.assertEqual(self.inspect(records)['censorReason'], 'invalid_clock_offset_or_reversal')

    def test_time_reversal(self):
        records = list(self.records); records[2] = dict(records[2], timeMs=records[1]['timeMs'] - 1)
        self.assertEqual(self.inspect(records)['censorReason'], 'invalid_clock_offset_or_reversal')

    def test_missing_frame(self):
        self.assertEqual(self.inspect([self.records[0], self.records[2]])['censorReason'], 'missing_or_duplicate_tick')

    def test_first_row_error_is_not_misreported_as_empty(self):
        records = list(self.records); records[0] = dict(records[0], timeMs='bad')
        self.assertEqual(self.inspect(records)['censorReason'], 'invalid_tick_identity')


if __name__ == '__main__': unittest.main()
