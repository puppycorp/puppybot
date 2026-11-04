#!/usr/bin/env python3
"""CPU-only synthetic outcomes and fail-closed wrapper checks."""
import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


audit = load('hybrid_physical_audit_fixture', HERE / 'audit.py')
runner = load('hybrid_physical_runner_fixture', HERE / 'run.py')


def evidence(handoff=True, moving=1):
    result = {'handoff': handoff, 'collectorTerminal': False}
    actor = {'policyActions': 2, 'nonzeroDriveActions': moving}
    manipulation = {'objects': 1, 'traceMeetsManipulationCriteria': False, 'captures': [],
                    'releases': [], 'settledAtEnd': [], 'settledDeliveries': {}}
    def row(ack, tick, owner, valid, detections, command):
        return {'ack': ack, 'step': tick, 'totalSteps': tick, 'owner': owner,
                'imageValid': valid, 'rgbDetections': detections, 'driveCommand': command, 'timeMs': tick * 20,
                'cameraFrame': tick if owner == 0 else -1, 'cameraDriving': owner == 0, 'cameraStill': owner == 0}
    journal = [row(0, 10, 0, True, 0, [0, 0, 90]),
               row(1, 20, 0, True, 0, [12, 12, 90]),
               row(1, 30, 0, True, 1 if handoff else 0, [0, 0, 90])]
    if handoff:
        journal.append(row(3, 32, 1, False, None, [0, 0, 90]))
        journal.extend(row(4, tick, 1, False, None, [0, 0, 90]) for tick in range(52, 333, 20))
    final = 332 if handoff else 30
    journal.append(row(7, final, 2, False, None, [0, 0, 90]))
    for index, item in enumerate(journal): item['sequence'] = index + 1
    return result, actor, manipulation, journal


def delivered():
    result, actor, manipulation, journal = evidence()
    manipulation.update(traceMeetsManipulationCriteria=True,
                        captures=[{'object': 'red-block', 'step': 100}],
                        releases=[{'object': 'red-block', 'step': 200, 'overBox': True}],
                        settledAtEnd=['red-block'], settledDeliveries={'red-block': 300})
    return result, actor, manipulation, journal


class OutcomeTests(unittest.TestCase):
    def test_success_requires_learned_drive_and_independent_settled_chain(self):
        result, actor, manipulation, journal = delivered()
        report = audit.classify(result, actor, manipulation, journal, {'pathM': 1.0})
        self.assertEqual(report['outcome'], 'hybrid_simulated_delivery')
        self.assertEqual(report['status'], 'diagnostic_only')
        self.assertIn('heuristic collector', report['scope'])
        actor['nonzeroDriveActions'] = 0
        journal[1]['driveCommand'] = [0, 0, 90]
        self.assertEqual(audit.classify(result, actor, manipulation, journal, {'pathM': 0})['outcome'], 'no_nonzero_policy_drive')
        actor['nonzeroDriveActions'] = 1; journal[1]['driveCommand'] = [12, 12, 90]
        self.assertEqual(audit.classify(result, actor, manipulation, journal, {'pathM': 0})['outcome'],
                         'simulated_delivery_without_observed_navigation_motion')

    def test_no_handoff_and_partial_collector_are_distinct(self):
        result, actor, manipulation, journal = evidence(False)
        actor['policyActions'] = 90
        journal[-1:-1] = [dict(journal[2], step=40 + i * 10, totalSteps=40 + i * 10) for i in range(88)]
        journal[-1].update(step=910, totalSteps=910)
        for index, item in enumerate(journal): item['sequence'] = index + 1; item['timeMs'] = item['totalSteps'] * 20; item['cameraFrame'] = item['totalSteps'] if item['owner'] == 0 else -1
        self.assertEqual(audit.classify(result, actor, manipulation, journal, {'pathM': 1.0})['outcome'], 'no_handoff_within_navigation_limit')
        result, actor, manipulation, journal = evidence()
        self.assertEqual(audit.classify(result, actor, manipulation, journal, {'pathM': 1.0})['outcome'], 'collector_incomplete_without_capture')
        manipulation['captures'] = [{'object': 'red-block', 'step': 100}]
        self.assertEqual(audit.classify(result, actor, manipulation, journal, {'pathM': 1.0})['outcome'], 'collector_incomplete_after_capture')
        result['collectorTerminal'] = True
        journal[-2].update(ack=5, owner=2)
        self.assertEqual(audit.classify(result, actor, manipulation, journal, {'pathM': 1.0})['outcome'], 'collector_terminal_without_settled_delivery')

    def test_forged_or_inconsistent_chains_do_not_pass(self):
        for mutation in ('no_handoff', 'wrong_object', 'release_not_over_box', 'release_before_capture',
                         'capture_before_handoff', 'missing_settling', 'ambiguous_tick', 'missing_motion',
                         'drive_after_handoff', 'mismatched_drive_count', 'capture_after_trace',
                         'false_terminal', 'bad_collector_tick', 'zero_policy_actions', 'wrong_drive_owner',
                         'wrong_handoff_owner', 'wrong_handoff_echo', 'unknown_ack', 'wrong_clock', 'wrong_stop_steering',
                         'boolean_owner', 'boolean_step', 'negative_time', 'boolean_detection', 'bad_camera'):
            result, actor, manipulation, journal = delivered()
            if mutation == 'no_handoff': result['handoff'] = False; journal = journal[:3] + [{'ack': 7, 'step': 20, 'totalSteps': 20, 'owner': 2}]
            elif mutation == 'wrong_object': manipulation['releases'][0]['object'] = 'other'
            elif mutation == 'release_not_over_box': manipulation['releases'][0]['overBox'] = False
            elif mutation == 'release_before_capture': manipulation['releases'][0]['step'] = 50
            elif mutation == 'capture_before_handoff': manipulation['captures'][0]['step'] = 20
            elif mutation == 'missing_settling': manipulation['settledDeliveries'] = {}
            elif mutation == 'ambiguous_tick': journal[3]['step'] = 21
            elif mutation == 'drive_after_handoff': journal[2], journal[3] = journal[3], journal[2]
            elif mutation == 'mismatched_drive_count': actor['nonzeroDriveActions'] = 0
            elif mutation == 'capture_after_trace': manipulation['captures'][0]['step'] = 400
            elif mutation == 'false_terminal': result['collectorTerminal'] = True
            elif mutation == 'bad_collector_tick': journal[4]['totalSteps'] += 1
            elif mutation == 'zero_policy_actions': actor['policyActions'] = 0
            elif mutation == 'wrong_drive_owner': journal[1]['owner'] = 1
            elif mutation == 'wrong_handoff_owner': journal[3]['owner'] = 0
            elif mutation == 'wrong_handoff_echo': journal[3]['driveCommand'] = [1, 0, 90]
            elif mutation == 'unknown_ack': journal[1]['ack'] = 9
            elif mutation == 'wrong_clock': journal[1]['timeMs'] -= 1
            elif mutation == 'boolean_owner': journal[1]['owner'] = False
            elif mutation == 'boolean_step': journal[1]['step'] = True
            elif mutation == 'negative_time': journal[0]['timeMs'] = -1
            elif mutation == 'boolean_detection': journal[0]['rgbDetections'] = False
            elif mutation == 'bad_camera': journal[3]['cameraStill'] = True
            elif mutation == 'wrong_stop_steering': journal[3]['driveCommand'][2] = 999
            else: actor.pop('nonzeroDriveActions')
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                audit.classify(result, actor, manipulation, journal, {'pathM': 1.0})

    def test_denied_handoff_requires_exact_stopped_echo(self):
        result, actor, manipulation, journal = evidence()
        journal[1]['rgbDetections'] = 1
        denied = dict(journal[1], ack=2, totalSteps=22, step=22, timeMs=440,
                      driveCommand=[0, 0, 90], cameraFrame=22)
        journal.insert(2, denied)
        for row in journal[3:]:
            row['step'] += 2; row['totalSteps'] += 2; row['timeMs'] += 40
            if row['owner'] == 0: row['cameraFrame'] += 2
        for index, row in enumerate(journal): row['sequence'] = index + 1
        audit.classify(result, actor, manipulation, journal, {'pathM': 1.0})
        denied['driveCommand'] = [0, 0, 999]
        with self.assertRaises(ValueError):
            audit.classify(result, actor, manipulation, journal, {'pathM': 1.0})

    def test_trace_end_must_match_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'trace.jsonl'
            path.write_text(json.dumps({'step': 1, 'totalSteps': 1}) + '\n' + json.dumps({'step': 2, 'totalSteps': 2}) + '\n')
            self.assertEqual(audit.trace_last_tick(path), 2)
            path.write_text(json.dumps({'step': 3, 'totalSteps': 2}) + '\n')
            with self.assertRaises(ValueError): audit.trace_last_tick(path)
            path.write_text(json.dumps({'step': True, 'totalSteps': 1}) + '\n')
            with self.assertRaises(ValueError): audit.trace_last_tick(path)

    def test_missing_trial_evidence_is_censored(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = audit.audit(Path(tmp))
        self.assertEqual(result['status'], 'censored')
        self.assertNotIn('outcome', result)


class WrapperTests(unittest.TestCase):
    def test_worker_uses_only_the_requested_fixed_arm(self):
        with mock.patch.object(runner.hidden, 'run_trial') as trial:
            original = runner.hidden.MODEL
            try:
                runner.worker('/tmp/synthetic-only', 'control')
                self.assertEqual(runner.hidden.MODEL, runner.PACKAGE / 'control')
                trial.assert_called_once_with(Path('/tmp/synthetic-only'))
                with self.assertRaises(ValueError): runner.worker('/tmp/synthetic-only', 'unknown')
            finally: runner.hidden.MODEL = original

    def test_timeout_is_censored_and_does_not_run_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); manifest = {'arms': {'control': {'weightsSHA256': 'hash'}}}
            status = {'clientExit': -15, 'signal': None, 'timedOut': True, 'remainingWorkersTerminated': False}
            with mock.patch.object(runner, 'P', root), mock.patch.object(runner.guard, 'require_dedicated_process'), \
                 mock.patch.object(runner.base, 'acquire_lock', return_value=nullcontext()), \
                 mock.patch.object(runner.base, 'require_capacity'), mock.patch.object(runner.plan.package, 'verify', return_value=manifest), \
                 mock.patch.object(runner, 'pins', return_value={'source': 'hash'}), \
                 mock.patch.object(runner.hidden, 'sha', return_value='hash'), \
                 mock.patch.object(runner.hidden, 'supervise', return_value=status) as supervised:
                with self.assertRaisesRegex(RuntimeError, 'timed out'): runner.run('control')
            output = root / 'hybrid-physical-eval-v1-control'
            self.assertEqual(json.loads((output / 'outcome.json').read_text())['status'], 'censored')
            self.assertFalse((output / 'audit-monitor').exists())
            self.assertEqual(supervised.call_count, 1)

    def test_cli_disabled(self):
        completed = subprocess.run([sys.executable, '-I', str(HERE / 'run.py')], capture_output=True, text=True)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn('Disabled pending', completed.stderr)


if __name__ == '__main__': unittest.main()
