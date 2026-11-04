#!/usr/bin/env python3
"""Synthetic saved-protocol evidence and mutation tests; no simulator runs."""
import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('terminal_real_audit', HERE / 'audit.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def row(sequence, step, owner, ack):
    return {'schema': 'puppybot.physical-agent.v1', 'sequence': sequence, 'step': step,
            'totalSteps': step, 'timeMs': 1280 + 20 * step, 'owner': owner, 'ack': ack,
            'imageValid': False, 'rgbDetections': None, 'cameraFrame': -1,
            'cameraDriving': False, 'cameraStill': False, 'driveCommand': [0, 0, 90]}


def intent(sequence, command, hold):
    return {'sequence': sequence, 'command': command, 'steering': 0, 'speed': 0, 'hold': hold}


def fixture():
    previous = row(1, 90, 1, 4)
    terminal = row(2, 99, 2, 5); terminal['collectorFailure'] = 'box not reacquired'
    stop = row(3, 99, 2, 7)
    trace = [{'schema': 'puppybot.sim.v1', 'step': 90, 'totalSteps': 90, 'timeMs': 3080},
             {'schema': 'puppybot.sim.v1', 'step': 99, 'totalSteps': 99, 'timeMs': 3260,
              'case': {'phase': 'failed', 'passed': False, 'reason': 'box not reacquired'}}]
    result = {'collectorTerminal': True, 'stopCommandAcknowledged': True, 'outcome': 'unverified',
              'collectorFailure': 'box not reacquired'}
    return {'journal': [previous, terminal, stop], 'intents': [intent(1, 7, 20), intent(2, 7, 20), intent(3, 3, 0)],
            'trace': trace, 'result': result}


def write_fixture(path, f):
    for filename, key in (('physical-agent.jsonl', 'journal'), ('search-requests.jsonl', 'intents'), ('trace.jsonl', 'trace')):
        (path / filename).write_text(''.join(json.dumps(v) + '\n' for v in f[key]))
    result = dict(f['result'])
    result.setdefault('traceSHA256', hashlib.sha256((path / 'trace.jsonl').read_bytes()).hexdigest())
    (path / 'result.json').write_text(json.dumps(result) + '\n')


class TerminalAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='terminal-audit-fixture-')
        self.root = Path(self.temp.name)
        self.data = fixture()
        write_fixture(self.root, self.data)

    def tearDown(self):
        self.temp.cleanup()

    def reject(self, mutate):
        data = copy.deepcopy(self.data)
        mutate(data)
        write_fixture(self.root, data)
        with self.assertRaises((ValueError, OSError)):
            audit.audit(self.root)

    def test_valid_failure_and_checked_stop(self):
        report = audit.audit(self.root)
        self.assertEqual(report['status'], 'consistent_simulator_failure_report')
        self.assertEqual((report['terminalSequence'], report['stopSequence'], report['terminalStep']), (2, 3, 99))
        self.assertEqual(report['failure'], 'box not reacquired')
        self.assertEqual(len(report['evidenceSHA256']), 4)

    def test_terminal_reason_missing_invalid_and_mismatched(self):
        for edit in (
            lambda d: d['journal'][-2].pop('collectorFailure'),
            lambda d: d['journal'][-2].update(collectorFailure=''),
            lambda d: d['journal'][-2].update(collectorFailure='bad\0tail'),
            lambda d: d['journal'][-2].update(collectorFailure='a' * 129),
            lambda d: d['journal'][-2].update(collectorFailure='wrong reason'),
            lambda d: d['journal'][-1].update(collectorFailure='box not reacquired'),
        ):
            with self.subTest(edit=edit): self.reject(edit)

    def test_terminal_requires_owner_zero_drive_and_camera_fields(self):
        for edit in (
            lambda d: d['journal'][-2].update(ack=4),
            lambda d: d['journal'][-2].update(owner=1),
            lambda d: d['journal'][-2].update(driveCommand=[1, 1, 90]),
            lambda d: d['journal'][-2].pop('rgbDetections'),
            lambda d: d['journal'][-2].update(imageValid=True),
            lambda d: d['journal'][-2].update(timeMs=3261),
        ):
            with self.subTest(edit=edit): self.reject(edit)

    def test_stop_and_request_must_be_present_and_match(self):
        for edit in (
            lambda d: d['journal'].pop(),
            lambda d: d['journal'][-1].update(ack=6),
            lambda d: d['journal'][-1].update(sequence=4),
            lambda d: d['journal'][-1].update(driveCommand=[1, 0, 90]),
            lambda d: d['journal'][-1].update(step=100, totalSteps=100),
            lambda d: d['journal'][-1].update(timeMs=3280),
            lambda d: d['intents'][-1].update(command=2),
            lambda d: d['intents'][-1].update(hold=1),
            lambda d: d['intents'].pop(),
            lambda d: d['intents'][-2].update(command=3),
            lambda d: d['intents'][-2].update(hold=8),
        ):
            with self.subTest(edit=edit): self.reject(edit)

    def test_result_must_retain_reason_and_ack_without_success_claim(self):
        for edit in (
            lambda d: d['result'].pop('collectorFailure'),
            lambda d: d['result'].update(collectorFailure='different'),
            lambda d: d['result'].update(collectorTerminal=False),
            lambda d: d['result'].update(stopCommandAcknowledged=False),
            lambda d: d['result'].update(outcome='success'),
            lambda d: d['result'].update(collectorFailureReportInvalid=True),
            lambda d: d['result'].update(traceSHA256='0' * 64),
        ):
            with self.subTest(edit=edit): self.reject(edit)

    def test_same_step_trace_must_be_failed_with_same_reason(self):
        for edit in (
            lambda d: d['trace'][-1]['case'].update(reason='other'),
            lambda d: d['trace'][-1]['case'].update(phase='passed'),
            lambda d: d['trace'][-1]['case'].update(passed=True),
            lambda d: d['trace'][-1].update(timeMs=3261),
            lambda d: d['trace'][-1].update(totalSteps=98),
            lambda d: d['trace'].pop(),
            lambda d: d['trace'].append(copy.deepcopy(d['trace'][-1])),
            lambda d: d['trace'].append({'schema': 'puppybot.sim.v1', 'step': 100}),
        ):
            with self.subTest(edit=edit): self.reject(edit)

    def test_missing_file_duplicate_json_and_evidence_change_rejected(self):
        (self.root / 'search-requests.jsonl').unlink()
        with self.assertRaises(OSError): audit.audit(self.root)
        write_fixture(self.root, self.data)
        (self.root / 'result.json').write_text('{"collectorFailure":"a","collectorFailure":"b"}')
        with self.assertRaises(ValueError): audit.audit(self.root)
        write_fixture(self.root, self.data)
        original = audit.digest; count = 0
        def changed(path):
            nonlocal count
            count += 1
            value = original(path)
            return '0' * 64 if count > 4 and path.name == 'result.json' else value
        with mock.patch.object(audit, 'digest', side_effect=changed):
            with self.assertRaises(ValueError): audit.audit(self.root)


if __name__ == '__main__':
    unittest.main()
