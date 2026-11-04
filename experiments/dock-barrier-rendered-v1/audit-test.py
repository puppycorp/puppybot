#!/usr/bin/env python3
"""CPU-only tests for saved worker barrier and validated map evidence."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('barrier_audit', HERE / 'audit.py')
audit = importlib.util.module_from_spec(spec); spec.loader.exec_module(audit)


def state(waits=0, frame=-1, tick=-1, wall=-1, failures=0):
    return {'waits': waits, 'lastFrameId': frame, 'lastWorkerCompleteTick': tick,
            'lastWallMs': wall, 'failures': failures}


def row(tick, barrier=None, frame=0):
    item = {'step': tick, 'totalSteps': tick, 'timeMs': tick * 20}
    if barrier is not None: item['discovery'] = {'workerBarrier': barrier, 'mapFrameId': frame}
    return item


def write_trace(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(record) + '\n' for record in records))


class BarrierAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='barrier-audit-'); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.records = [row(1), row(2, state()), row(3, state(1, 2, 3, 700), 2),
                        row(4, state(1, 2, 3, 700), 2), row(5, state(2, 4, 5, 900), 4)]

    def trace(self, records):
        path = self.root / 'trace.jsonl'; write_trace(path, records); return audit.barrier(path)

    def test_map_application_and_wall_latency_are_distinct(self):
        result = self.trace(self.records)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual([x['mapAppliedTick'] for x in result['waits']], [3, 5])
        self.assertEqual([x['wallMs'] for x in result['waits']], [700, 900])
        self.assertTrue(all(x['mapApplied'] for x in result['waits']))
        records = list(self.records); records[2] = row(3, state(1, 2, 3, 700), 0)
        result = self.trace(records)
        self.assertEqual(result['censorReason'], 'completion_without_observed_map_application')
        self.assertFalse(result['waits'][0]['mapApplied'])
        self.assertIsNone(result['waits'][0]['mapAppliedTick'])

    def test_ambiguous_or_missing_records_are_censored(self):
        examples = [
            ([row(1), row(2, state()), row(4, state(1, 2, 3, 500), 2)], 'missing_or_duplicate_tick'),
            ([row(1), row(2, state(1, 1, 2, 10), 1)], 'unobserved_prior_wait'),
            ([row(1), row(2, state()), row(3, state(2, 2, 3, 10), 2)], 'unobserved_or_decreasing_waits'),
            ([row(1), row(2, state()), row(3, state(1, 2, 2, 10), 2)], 'invalid_or_unobserved_completion'),
            ([row(1), row(2, state()), row(3, state(1, 2, 3, 15000), 2)], 'invalid_or_unobserved_completion'),
            ([row(1), row(2, state()), row(3, state(failures=1))], 'worker_barrier_failure'),
            ([row(1), row(2, state()), row(3, state(), 2)], 'map_changed_without_observed_wait'),
            ([row(1), row(2, state())], 'no_worker_wait_observed'),
            ([row(1), row(2)], 'discovery_not_observed'),
            ([row(1), {'step': 2, 'totalSteps': 2, 'timeMs': 40, 'discovery': {'mapFrameId': 0}}], 'missing_or_invalid_barrier'),
        ]
        for records, reason in examples:
            with self.subTest(reason=reason):
                result = self.trace(records)
                self.assertEqual((result['status'], result['censorReason']), ('censored', reason))

    def test_control_comparison_ignores_wall_variation_only(self):
        for name in audit.base.ARMS:
            records = json.loads(json.dumps(self.records))
            if name == 'candidate-disabled':
                for item in records:
                    barrier = item.get('discovery', {}).get('workerBarrier')
                    if barrier and barrier['waits']: barrier['lastWallMs'] += 1
            write_trace(self.root / name / 'run/trace.jsonl', records)
        result = audit.barrier_comparison(self.root)
        self.assertEqual(result['status'], 'complete'); self.assertTrue(result['matchedControlMapApplications'])
        records = json.loads(json.dumps(self.records))
        records[2] = row(3, state(1, 1, 3, 701), 1); records[3] = row(4, state(1, 1, 3, 701), 1)
        write_trace(self.root / 'candidate-disabled/run/trace.jsonl', records)
        result = audit.barrier_comparison(self.root)
        self.assertEqual(result['censorReason'], 'control_map_application_sequence_mismatch')
        self.assertFalse(result['matchedControlMapApplications'])
        write_trace(self.root / 'candidate-disabled/run/trace.jsonl', self.records)
        write_trace(self.root / 'candidate-search/run/trace.jsonl', [row(1)])
        self.assertEqual(audit.barrier_comparison(self.root, include_candidate=True)['censorReason'], 'candidate_barrier_trace_censored')

    def test_pair_does_not_require_candidate_and_censors_missing_control(self):
        for name in ('baseline', 'candidate-disabled'):
            write_trace(self.root / name / 'run/trace.jsonl', self.records)
        self.assertTrue(audit.barrier_comparison(self.root)['matchedControlMapApplications'])
        (self.root / 'candidate-disabled/run/trace.jsonl').unlink()
        result = audit.barrier_comparison(self.root)
        self.assertEqual(result['censorReason'], 'control_barrier_trace_censored')
        self.assertEqual(result['arms']['candidate-disabled']['censorReason'], 'missing_or_invalid_trace')

    def test_filter_only_instrumentation_and_gate_eligibility(self):
        path = self.root / 'trace.jsonl'; write_trace(path, self.records)
        filtered = audit.rows(path)
        self.assertNotIn('workerBarrier', filtered[2]['discovery'])
        self.assertEqual(filtered[2]['discovery']['mapFrameId'], 2)
        inherited = {'arms': [{'status': 'complete'}] * 3, 'comparisonEligible': True,
                     'mechanismEligible': True, 'censorReason': None, 'scope': 'test'}
        with mock.patch.object(audit.clearance, 'audit', return_value=inherited), \
                mock.patch.object(audit, 'barrier_comparison', return_value={'status': 'censored', 'censorReason': 'test_reason'}):
            result = audit.audit(self.root)
        self.assertFalse(result['comparisonEligible']); self.assertFalse(result['mechanismEligible'])
        self.assertEqual(result['censorReason'], 'test_reason')


if __name__ == '__main__': unittest.main()
