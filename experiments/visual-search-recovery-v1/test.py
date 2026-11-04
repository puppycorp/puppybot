#!/usr/bin/env python3
"""CPU-only copied hybrid client and synthetic physical-agent peer tests."""
import importlib.util
import json
import os
import shutil
import subprocess
import unittest
from unittest import mock
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


transform = load('visual_search_transform', HERE / 'transform.py')
audit = load('visual_search_audit', HERE / 'audit.py')
prior = load('visual_search_peer_fixtures', ROOT / 'experiments/physical-search-fallback-v1/test_search_client.py')


class VisualSearchTest(prior.SearchClientTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        source = cls.shadow / 'control/test-candidate.flex'
        output = cls.shadow / 'control/test-visual-search.flex'
        output.write_text(transform.transform(source.read_text()))
        shutil.copyfile(ROOT / 'experiments/visual-exact-stall-v1/visual-stall.flex',
                        cls.shadow / 'control/visual-stall.flex')
        built = subprocess.run([str(prior.prepare.COMPILER), str(output), '-o', str(cls.root / 'client-visual')],
                               cwd=ROOT, capture_output=True, text=True, timeout=120)
        if built.returncode:
            raise RuntimeError(built.stdout + '\n' + built.stderr)

    def visual_case(self, name, enabled, mode='normal', search=True, binary='visual', simulator=None):
        output = self.root / name
        commands = self.root / (name + '.commands')
        actor = self.root / (name + '.actor')
        env = dict(os.environ, PUPPYBOT_PHYSICAL_NAV_LIMIT='10', PUPPYBOT_PHYSICAL_POLL_LIMIT='1',
                   PUPPYBOT_PHYSICAL_SEARCH_FALLBACK='1' if search else '0',
                   PUPPYBOT_VISUAL_SEARCH_RECOVERY='1' if enabled else '0',
                   SEARCH_TEST_VISIBLE='0', SEARCH_TEST_MODE=mode,
                   SEARCH_TEST_COMMANDS=str(commands), PUPPY_TEST_ACTOR=str(actor))
        env.pop('PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS', None)
        command = [str(self.root / ('client-' + binary)), str(simulator or self.simulator), str(self.model),
                   str(self.case), str(self.environment), str(output), '--allow-zero-contact']
        done = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=20)
        return output, done, commands

    def test_repeated_images_trigger_stopped_search_before_budget(self):
        output, done, commands = self.visual_case('early-search', True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(commands.read_text().split(), ['1', '2', '2', '2', '2', '8', '7', '3'])
        result = json.loads((output / 'result.json').read_text())
        self.assertEqual(result['policyActions'], 4)
        self.assertEqual(result['visualRecoveryReason'], 1)
        self.assertEqual(result['visualRecoveryTriggerAction'], 4)
        self.assertEqual(result['visualRecoveryOutcome'], 'search_started_unverified')
        trigger = (output / 'visual-trigger.rgb').read_bytes()
        self.assertEqual(len(trigger), 21168)
        self.assertEqual(trigger, (output / 'actors/actor-4.rgb').read_bytes())
        self.assertTrue(result['searchFallbackStarted'])
        self.assertFalse(result['handoff'])
        self.assertTrue(result['collectorTerminal'])
        self.assertEqual(result['outcome'], 'unverified')

    def test_new_target_at_transfer_uses_ordinary_handoff(self):
        output, done, commands = self.visual_case('visual-new-target', True, mode='new-target')
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(commands.read_text().split(), ['1', '2', '2', '2', '2', '8', '6', '7', '3'])
        result = json.loads((output / 'result.json').read_text())
        self.assertTrue(result['handoff'])
        self.assertFalse(result['searchFallbackStarted'])
        self.assertEqual(result['visualRecoveryOutcome'], 'target_handoff_unverified')
        self.assertEqual(result['outcome'], 'unverified')

    def test_target_disappearing_reports_transfer_failure(self):
        output, done, commands = self.visual_case('visual-target-vanishes', True, mode='target-vanishes')
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(commands.read_text().split(), ['1', '2', '2', '2', '2', '8', '6', '3'])
        result = json.loads((output / 'result.json').read_text())
        self.assertEqual(result['visualRecoveryOutcome'], 'transfer_did_not_start')
        self.assertFalse(result['handoff'])
        self.assertFalse(result['searchFallbackStarted'])
        self.assertFalse(result['collectorTerminal'])
        self.assertEqual(result['outcome'], 'unverified')

    def test_disabled_retains_navigation_budget_and_no_recovery_fields(self):
        output, done, commands = self.visual_case('disabled-visual', False)
        reference, prior_done, prior_commands = self.visual_case('disabled-reference', False, binary='candidate')
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(prior_done.returncode, 0, prior_done.stderr)
        self.assertEqual(commands.read_text().split(), ['1'] + ['2'] * 10 + ['8', '7', '3'])
        self.assertEqual(commands.read_text(), prior_commands.read_text())
        result = json.loads((output / 'result.json').read_text())
        self.assertEqual(result['policyActions'], 10)
        self.assertNotIn('visualRecoveryReason', result)
        self.assertNotIn('visualRecoveryOutcome', result)
        self.assertFalse((output / 'visual-trigger.rgb').exists())
        for name in ('result.json', 'physical-agent.jsonl', 'search-requests.jsonl'):
            self.assertEqual((output / name).read_bytes(), (reference / name).read_bytes(), name)
        for file in (reference / 'actors').iterdir():
            self.assertEqual(file.read_bytes(), (output / 'actors' / file.name).read_bytes(), file.name)

    def test_changing_images_do_not_trigger_the_guard(self):
        simulator = self.root / 'changing-simulator'
        needle = 'pixels=bytes([128,64,255])*(640*480) if valid else bytes(640*480*3)'
        self.assertEqual(prior.SIMULATOR.count(needle), 1)
        simulator.write_text(prior.SIMULATOR.replace(needle,
            'pixels=bytes([(step//10)%256,64,255])*(640*480) if valid else bytes(640*480*3)'))
        simulator.chmod(0o755)
        output, done, commands = self.visual_case('changing-images', True, simulator=simulator)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(commands.read_text().split(), ['1'] + ['2'] * 10 + ['8', '7', '3'])
        result = json.loads((output / 'result.json').read_text())
        self.assertEqual((result['visualRecoveryReason'], result['visualRecoveryTriggerAction']), (0, -1))
        self.assertEqual(result['visualRecoveryOutcome'], 'not_triggered')

    def test_bad_search_reply_does_not_report_success(self):
        output, done, commands = self.visual_case('stale-transfer', True, mode='stale')
        self.assertNotEqual(done.returncode, 0)
        self.assertFalse((output / 'result.json').exists())
        self.assertEqual(commands.read_text().split(), ['1', '2', '2', '2', '2', '8'])

    def test_visual_recovery_requires_search_opt_in(self):
        output, done, commands = self.visual_case('missing-search', True, search=False)
        self.assertNotEqual(done.returncode, 0)
        self.assertFalse(output.exists())
        self.assertFalse(commands.exists())

    def test_saved_protocol_audits_each_early_transfer_outcome(self):
        for mode, expected in (('normal', 'search_started_unverified'),
                               ('new-target', 'target_handoff_unverified'),
                               ('target-vanishes', 'transfer_did_not_start')):
            with self.subTest(mode=mode):
                output, done, _ = self.visual_case('audit-' + mode, True, mode=mode)
                self.assertEqual(done.returncode, 0, done.stderr)
                saved = audit.audit_run(output, visual_enabled=True, nav_limit=10, poll_limit=1)
                self.assertEqual(saved['visualTriggerAction'], 4)
                self.assertEqual(saved['triggerTick'], 140)
                self.assertEqual(saved['visualRecoveryOutcome'], expected)

    def test_saved_audit_rejects_missing_tampered_or_unjustified_trigger(self):
        output, done, _ = self.visual_case('audit-tampered', True)
        self.assertEqual(done.returncode, 0, done.stderr)
        trigger = output / 'visual-trigger.rgb'; image = trigger.read_bytes()
        trigger.unlink()
        with self.assertRaises(ValueError): audit.audit_run(output, visual_enabled=True, nav_limit=10, poll_limit=1)
        trigger.write_bytes(bytes([image[0] ^ 1]) + image[1:])
        with self.assertRaises(ValueError): audit.audit_run(output, visual_enabled=True, nav_limit=10, poll_limit=1)
        trigger.write_bytes(image)
        result_path = output / 'result.json'; result = json.loads(result_path.read_text())
        result['visualRecoveryTriggerAction'] = 3; result_path.write_text(json.dumps(result))
        with self.assertRaises(ValueError): audit.audit_run(output, visual_enabled=True, nav_limit=10, poll_limit=1)

    def test_saved_audit_disabled_mode_and_forged_outcome(self):
        output, done, _ = self.visual_case('audit-disabled', False)
        self.assertEqual(done.returncode, 0, done.stderr)
        saved = audit.audit_run(output, visual_enabled=False, nav_limit=10, poll_limit=1)
        self.assertIsNone(saved['visualTriggerAction'])
        result_path = output / 'result.json'; result = json.loads(result_path.read_text())
        result['visualRecoveryOutcome'] = 'search_started_unverified'; result_path.write_text(json.dumps(result))
        with self.assertRaises(ValueError): audit.audit_run(output, visual_enabled=False, nav_limit=10, poll_limit=1)

    def test_saved_audit_rejects_changed_echo_and_missing_request(self):
        output, done, _ = self.visual_case('audit-protocol-tampered', True)
        self.assertEqual(done.returncode, 0, done.stderr)
        journal = output / 'physical-agent.jsonl'; original = journal.read_text()
        rows = [json.loads(line) for line in original.splitlines()]
        rows[1]['driveCommand'] = [0, 0, 90]
        journal.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        with self.assertRaises(ValueError): audit.audit_run(output, visual_enabled=True, nav_limit=10, poll_limit=1)
        journal.write_text(original)
        requests = output / 'search-requests.jsonl'
        requests.write_text(''.join(requests.read_text().splitlines(keepends=True)[:-1]))
        with self.assertRaises(ValueError): audit.audit_run(output, visual_enabled=True, nav_limit=10, poll_limit=1)

    def test_prior_audit_identity_and_run_bounds_are_enforced(self):
        original = audit.inspect.getsource(audit.base.protocol)
        with mock.patch.object(audit.inspect, 'getsource', return_value=original + '\n# changed\n'):
            with self.assertRaises(ValueError): audit.adapted_protocol()
        for nav, polls in ((0, 1), (301, 1), (1, 0), (1, 1501)):
            with self.subTest(nav=nav, polls=polls), self.assertRaises(ValueError):
                audit.audit_run(self.root / 'absent', visual_enabled=True, nav_limit=nav, poll_limit=polls)

    def test_existing_trigger_image_is_not_overwritten_or_transferred(self):
        simulator = self.root / 'existing-trigger-simulator'
        marker = 's=socket.socket(fileno=3);step=100;visible=int(os.environ["SEARCH_TEST_VISIBLE"]);mode=os.environ["SEARCH_TEST_MODE"]'
        self.assertEqual(prior.SIMULATOR.count(marker), 1)
        inject = '\nPath(sys.argv[sys.argv.index("--record")+1]).parent.joinpath("visual-trigger.rgb").write_bytes(b"preserve")'
        simulator.write_text(prior.SIMULATOR.replace(marker, marker + inject))
        simulator.chmod(0o755)
        output, done, commands = self.visual_case('existing-trigger', True, simulator=simulator)
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual((output / 'visual-trigger.rgb').read_bytes(), b'preserve')
        self.assertEqual(commands.read_text().split(), ['1', '2', '2', '2', '2'])
        self.assertFalse((output / 'result.json').exists())


if __name__ == '__main__':
    unittest.main()
