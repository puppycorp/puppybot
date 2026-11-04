#!/usr/bin/env python3
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('turn_rendered_audit', HERE / 'audit.py')
audit = importlib.util.module_from_spec(spec); spec.loader.exec_module(audit)


def fixture(root, duration, candidate):
    run = root / 'run'; run.mkdir()
    fail = duration == 60 or (duration == 10 and not candidate)
    end = 100 if not duration or (duration == 10 and not candidate) or (duration == 60 and not candidate) else (150 if duration == 60 else 138)
    rows = []
    for tick in range(100, end + 1):
        lowered = not fail and tick == end
        samples = 5 + (tick - 100) // 10
        masked = 0 if not duration else 1 + min((tick - 100) // 10, (duration - 1) // 10)
        recovered = duration == 10 and candidate and tick >= 118
        frame = 118 + 10 * ((tick - 118) // 10) if recovered else (tick if lowered else 100)
        reason = ''
        if fail and tick == end:
            reason = ('box observation reacquisition timed out after turn' if candidate else
                      'box observation lost or changed while turning above container')
        rows.append({'totalSteps': tick, 'case': {'phase': 'failed' if reason else 'placing', 'reason': reason,
            'turnProbe': {'duration': duration, 'triggerTick': 100, 'eligible': True, 'preStable': 3,
                          'preFrame': 100, 'masked': masked, 'lowerTick': tick if lowered else -1,
                          'waitTick': 100 if candidate and duration and not lowered else -1, 'turning': not lowered},
            'dockVision': {'valid': not duration or recovered, 'stableObservations': (frame - 118) // 10 + 1 if recovered else (3 if lowered else 0),
                           'frameId': frame, 'samples': samples}},
            'gripper': {'held': True, 'releases': 0}})
    trace = run / 'trace.jsonl'; trace.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    (run / 'result.json').write_text(json.dumps({'collectorTerminal': True, 'stopCommandAcknowledged': True,
                                                'traceSHA256': audit.sha(trace)}))
    (root / 'supervisor-result.json').write_text(json.dumps({'clientExit': 0, 'timedOut': False, 'signal': None, 'processGroup': 123,
                                                             'remainingWorkersTerminated': False}))
    (root / 'manipulation-audit.json').write_text(json.dumps({'status': 'diagnostic_only',
                                                              'traceMeetsManipulationCriteria': False}))
    return rows


class AuditTest(unittest.TestCase):
    def test_each_expected_mechanism(self):
        for candidate in (False, True):
            for duration in (0, 10, 60):
                with self.subTest(candidate=candidate, duration=duration), tempfile.TemporaryDirectory() as temp:
                    root = Path(temp); fixture(root, duration, candidate)
                    self.assertEqual(audit.audit(root, duration, candidate)['status'], 'mechanism_observed')

    def test_missing_trigger_and_unacknowledged_stop_are_censored(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); rows = fixture(root, 0, True)
            rows[0]['case']['turnProbe']['triggerTick'] = -1
            trace = root / 'run/trace.jsonl'; trace.write_text(json.dumps(rows[0]) + '\n')
            result = root / 'run/result.json'; result.write_text(json.dumps({'collectorTerminal': True,
                'stopCommandAcknowledged': True, 'traceSHA256': audit.sha(trace)}))
            self.assertEqual(audit.audit(root, 0, True)['status'], 'censored')
            result.write_text(json.dumps({'collectorTerminal': True, 'stopCommandAcknowledged': False,
                                          'traceSHA256': audit.sha(trace)}))
            self.assertEqual(audit.audit(root, 0, True)['status'], 'censored')

    def test_noneligible_trigger_is_censored(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); rows = fixture(root, 0, True)
            rows[0]['case']['turnProbe']['eligible'] = False
            trace = root / 'run/trace.jsonl'; trace.write_text(json.dumps(rows[0]) + '\n')
            result = root / 'run/result.json'; result.write_text(json.dumps({'collectorTerminal': True,
                'stopCommandAcknowledged': True, 'traceSHA256': audit.sha(trace)}))
            self.assertEqual(audit.audit(root, 0, True)['status'], 'censored')

    def test_early_vision_and_unmasked_sample_rejected(self):
        for fault in ('vision', 'mask'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); rows = fixture(root, 60, True)
                if fault == 'vision': rows[5]['case']['dockVision']['valid'] = True
                else: rows[10]['case']['turnProbe']['masked'] -= 1
                trace = root / 'run/trace.jsonl'; trace.write_text(''.join(json.dumps(row) + '\n' for row in rows))
                result = root / 'run/result.json'; result.write_text(json.dumps({'collectorTerminal': True,
                    'stopCommandAcknowledged': True, 'traceSHA256': audit.sha(trace)}))
                self.assertEqual(audit.audit(root, 60, True)['status'], 'mechanism_mismatch')

    def test_malformed_supervisor_rejected(self):
        for key, value in (('clientExit', False), ('processGroup', True), ('processGroup', 0), ('signal', 9)):
            with self.subTest(key=key, value=value), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); fixture(root, 0, True)
                status = root / 'supervisor-result.json'; obj = json.loads(status.read_text()); obj[key] = value
                status.write_text(json.dumps(obj))
                self.assertEqual(audit.audit(root, 0, True)['status'], 'censored')

    def test_immediate_control_must_fail_on_trigger_tick(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); rows = fixture(root, 60, True)[:6]
            rows[-1]['case']['phase'] = 'failed'
            rows[-1]['case']['reason'] = 'box observation lost or changed while turning above container'
            trace = root / 'run/trace.jsonl'; trace.write_text(''.join(json.dumps(row) + '\n' for row in rows))
            result = root / 'run/result.json'; result.write_text(json.dumps({'collectorTerminal': True,
                'stopCommandAcknowledged': True, 'traceSHA256': audit.sha(trace)}))
            self.assertEqual(audit.audit(root, 60, False)['status'], 'mechanism_mismatch')

    def test_candidate_wait_and_three_recovered_frames_are_required(self):
        for fault in ('wait', 'frames'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); rows = fixture(root, 10, True)
                if fault == 'wait':
                    rows[5]['case']['turnProbe']['waitTick'] = -1
                else:
                    for row in rows:
                        if row['case']['dockVision']['frameId'] == 128:
                            row['case']['dockVision']['frameId'] = 118
                trace = root / 'run/trace.jsonl'; trace.write_text(''.join(json.dumps(row) + '\n' for row in rows))
                result = root / 'run/result.json'; result.write_text(json.dumps({'collectorTerminal': True,
                    'stopCommandAcknowledged': True, 'traceSHA256': audit.sha(trace)}))
                self.assertEqual(audit.audit(root, 10, True)['status'], 'mechanism_mismatch')


if __name__ == '__main__':
    unittest.main()
