#!/usr/bin/env python3
"""Exercise the visual-stall saved-game audit without launching a simulator."""
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location('visual_trial_audit', HERE / 'audit.py')
audit = importlib.util.module_from_spec(spec); spec.loader.exec_module(audit)
PRIOR = ROOT / 'build/flex/sim/levels-v2/pitch82/l5-steering-hysteresis-debug-v1/games'


def write_json(path, value):
    path.write_text(json.dumps(value) + '\n')


def update_result(root, **changes):
    path = root / 'result.json'; result = json.loads(path.read_text()); result.update(changes); write_json(path, result)


def fixture(root, index, seed, trigger=None):
    prior = PRIOR / str(index) / 'kick-hysteresis' / str(seed)
    disabled = root / 'disabled'; enabled = root / 'enabled'
    shutil.copytree(prior, disabled); shutil.copytree(prior, enabled)
    update_result(disabled, visualContactAblated=False)
    if trigger is None:
        update_result(enabled, visualContactAblated=False, visualStopReason=None,
                      countAsFailedGame=False, fullHorizonCompleted=True)
        return disabled, enabled, prior
    control_probe = audit.rows(prior / 'steer-probe.jsonl')
    for name in ('steer-probe.jsonl', 'hysteresis.jsonl'):
        path = enabled / name; path.write_text(''.join(path.read_text().splitlines(keepends=True)[:trigger]))
    path = enabled / 'decisions.jsonl'; decisions = audit.rows(path)[:trigger]
    zero = json.loads(json.dumps(decisions[-1])); zero['sequence'] += 1; zero['step'] += 10; zero['action'] = [0.0, 0.0]
    zero['state']['controller']['drive']['leftSpeed'] = 0; zero['state']['controller']['drive']['rightSpeed'] = 0
    path.write_text(''.join(json.dumps(row) + '\n' for row in decisions + [zero]))
    state = decisions[-1]['state']; drive = state['controller']['drive']
    update_result(enabled, steps=trigger + 1, visualContactAblated=False,
                  visualStopReason='repeated_actor_image', countAsFailedGame=True, fullHorizonCompleted=False)
    write_json(enabled / 'visual-stall-stop.json', {'schema': 'puppybot.sim-visual-stall.v1',
        'reason': 'repeated_actor_image', 'triggerAfterActions': trigger, 'observedActions': trigger + 1,
        'zeroStopActions': 1, 'identicalFrames': 5, 'zeroCommandEchoObserved': True,
        'stopCommandAcknowledged': False, 'goalGameCompleted': False,
        'triggerImageSHA256': control_probe[trigger]['imageSHA256'], 'triggerTick': state['totalSteps'],
        'triggerFrameId': state['case']['perception']['frameId'],
        'triggerLeftSpeed': drive['leftSpeed'], 'triggerRightSpeed': drive['rightSpeed']})
    return disabled, enabled, prior


class VisualAuditTests(unittest.TestCase):
    def test_known_stall_and_tampered_trigger_digest(self):
        with tempfile.TemporaryDirectory(prefix='visual-audit-') as temp:
            disabled, enabled, prior = fixture(Path(temp), 1, 6800107, 147)
            result = audit.audit_pair(disabled, enabled, prior)
            self.assertEqual(result['triggerAfterActions'], 147)
            self.assertTrue(result['countAsFailedGame'])
            path = enabled / 'visual-stall-stop.json'; report = json.loads(path.read_text())
            report['triggerImageSHA256'] = '0' * 64; write_json(path, report)
            with self.assertRaisesRegex(ValueError, 'trigger'):
                audit.audit_pair(disabled, enabled, prior)

    def test_noop_and_bad_prefix_are_censored(self):
        with tempfile.TemporaryDirectory(prefix='visual-audit-') as temp:
            disabled, enabled, prior = fixture(Path(temp), 0, 6800102)
            self.assertFalse(audit.audit_pair(disabled, enabled, prior)['stopped'])
            path = enabled / 'steer-probe.jsonl'; lines = path.read_text().splitlines(); row = json.loads(lines[1]); row['imageSHA256'] = '0' * 64
            lines[1] = json.dumps(row); path.write_text('\n'.join(lines) + '\n')
            with self.assertRaisesRegex(ValueError, 'history'):
                audit.audit_pair(disabled, enabled, prior)

    def test_zero_contact_mode_checks_actor_and_decision_feedback(self):
        with tempfile.TemporaryDirectory(prefix='visual-audit-') as temp:
            disabled, enabled, _ = fixture(Path(temp), 0, 6800102)
            for root in (disabled, enabled): update_result(root, visualContactAblated=True)
            self.assertTrue(audit.audit_pair(disabled, enabled, require_zero_contact=True)['contactAblation'])
            path = disabled / 'steer-probe.jsonl'; lines = path.read_text().splitlines(); row = json.loads(lines[0]); row['feedback'][5] = 1065353216
            lines[0] = json.dumps(row); path.write_text('\n'.join(lines) + '\n')
            with self.assertRaisesRegex(ValueError, 'history|contact ablation'):
                audit.audit_pair(disabled, enabled, require_zero_contact=True)

    def test_zero_contact_pair_cannot_hide_shared_actor_or_hysteresis_tampering(self):
        changes = (
            ('steer-probe.jsonl', 'applied', [0, 0]),
            ('steer-probe.jsonl', 'command1000', [0, 0]),
            ('steer-probe.jsonl', 'feedback', [0, 0, 0, 0, 0, 0, 0]),
            ('steer-probe.jsonl', 'hiddenBeforeSHA256', '0' * 64),
            ('hysteresis.jsonl', 'remainingAfter', 99),
        )
        for name, field, replacement in changes:
            with self.subTest(name=name, field=field), tempfile.TemporaryDirectory(prefix='visual-audit-') as temp:
                disabled, enabled, _ = fixture(Path(temp), 0, 6800102)
                for root in (disabled, enabled):
                    update_result(root, visualContactAblated=True)
                    path = root / name; lines = path.read_text().splitlines()
                    row = json.loads(lines[1]); row[field] = replacement; lines[1] = json.dumps(row)
                    path.write_text('\n'.join(lines) + '\n')
                with self.assertRaises(ValueError):
                    audit.audit_pair(disabled, enabled, require_zero_contact=True)

    def test_horizon_trigger_without_independent_image_digest_is_censored(self):
        with tempfile.TemporaryDirectory(prefix='visual-audit-') as temp:
            disabled, enabled, prior = fixture(Path(temp), 0, 6800102)
            update_result(enabled, steps=301, visualStopReason='repeated_actor_image',
                          countAsFailedGame=True, fullHorizonCompleted=False)
            write_json(enabled / 'visual-stall-stop.json', {'schema': 'puppybot.sim-visual-stall.v1',
                'reason': 'repeated_actor_image', 'triggerAfterActions': 300, 'observedActions': 301,
                'zeroStopActions': 1, 'identicalFrames': 5, 'zeroCommandEchoObserved': True,
                'stopCommandAcknowledged': False, 'goalGameCompleted': False})
            with self.assertRaisesRegex(ValueError, 'post-horizon trigger image'):
                audit.audit_pair(disabled, enabled, prior)

    def test_moving_truth_does_not_authorize_claim_of_stationary(self):
        def state(tick, x):
            return {'totalSteps': tick, 'camera': {'pose': 'driving', 'armSettled': True},
                    'case': {'perception': {'frameId': tick}}, 'pose': [x, 0.0, 0.0],
                    'controller': {'drive': {'leftSpeed': 60, 'rightSpeed': 60}}}
        initial = state(100, 0.0)
        decisions = [{'step': 110 + i * 10, 'state': state(110 + i * 10, (i + 1) * 0.1)} for i in range(4)]
        self.assertEqual(audit.first_stall(initial, decisions, ['a' * 64] * 5), (4, 140, 5))


if __name__ == '__main__':
    unittest.main()
