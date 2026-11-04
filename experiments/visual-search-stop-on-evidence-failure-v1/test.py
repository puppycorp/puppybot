#!/usr/bin/env python3
"""Check that trigger-image failure requests a simulated stop before reporting."""
import importlib.util
import json
import subprocess
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


transform = load('trigger_failure_transform', HERE / 'transform.py')
prior = load('trigger_failure_previous_test', ROOT / 'experiments/visual-search-recovery-v1/test.py')


class TriggerEvidenceFailureTest(prior.VisualSearchTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        source = cls.shadow / 'control/test-candidate.flex'
        output = cls.shadow / 'control/test-visual-search-stop-on-evidence-failure.flex'
        output.write_text(transform.transform(source.read_text()))
        built = subprocess.run([str(prior.prior.prepare.COMPILER), str(output), '-o', str(cls.root / 'client-visual')],
                               cwd=ROOT, capture_output=True, text=True, timeout=120)
        if built.returncode:
            raise RuntimeError(built.stdout + '\n' + built.stderr)
        staged = output.read_text()
        needle = 'let error = pl_write(fd, ve_image, ve_image_bytes);'
        if staged.count(needle) != 1:
            raise RuntimeError('unexpected trigger evidence write')
        output.write_text(staged.replace(needle,
            'pl_write(fd, ve_image, 8); let error = 1;'))
        built = subprocess.run([str(prior.prior.prepare.COMPILER), str(output), '-o', str(cls.root / 'client-partial')],
                               cwd=ROOT, capture_output=True, text=True, timeout=120)
        if built.returncode:
            raise RuntimeError(built.stdout + '\n' + built.stderr)
        needle = 'if fd < 0 { return 3; }'
        if staged.count(needle) != 1:
            raise RuntimeError('unexpected trigger evidence open check')
        output.write_text(staged.replace(needle,
            'if fd < 0 { syscall(3, pc_search_requests, 0, 0, 0, 0, 0); return 3; }'))
        built = subprocess.run([str(prior.prior.prepare.COMPILER), str(output), '-o', str(cls.root / 'client-bad-journal')],
                               cwd=ROOT, capture_output=True, text=True, timeout=120)
        if built.returncode:
            raise RuntimeError(built.stdout + '\n' + built.stderr)

    def test_existing_trigger_image_is_not_overwritten_or_transferred(self):
        simulator = self.root / 'existing-trigger-simulator'
        marker = 's=socket.socket(fileno=3);step=100;visible=int(os.environ["SEARCH_TEST_VISIBLE"]);mode=os.environ["SEARCH_TEST_MODE"]'
        self.assertEqual(prior.prior.SIMULATOR.count(marker), 1)
        inject = '\nPath(sys.argv[sys.argv.index("--record")+1]).parent.joinpath("visual-trigger.rgb").write_bytes(b"preserve")'
        simulator.write_text(prior.prior.SIMULATOR.replace(marker, marker + inject))
        simulator.chmod(0o755)
        output, done, commands = self.visual_case('existing-trigger', True, simulator=simulator)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual((output / 'visual-trigger.rgb').read_bytes(), b'preserve')
        self.assertEqual(commands.read_text().split(), ['1', '2', '2', '2', '2', '3'])
        result = json.loads((output / 'result.json').read_text())
        self.assertEqual(result['visualRecoveryReason'], 1)
        self.assertEqual(result['visualRecoveryTriggerAction'], 4)
        self.assertEqual(result['visualRecoveryOutcome'], 'trigger_evidence_unavailable')
        self.assertTrue(result['stopCommandAcknowledged'])
        self.assertFalse(result['searchFallbackStarted'])
        self.assertEqual(result['outcome'], 'unverified')
        with self.assertRaises(ValueError):
            prior.audit.audit_run(output, visual_enabled=True, nav_limit=10, poll_limit=1)

    def test_partial_trigger_write_stops_and_leaves_evidence_censored(self):
        output, done, commands = self.visual_case('partial-trigger', True, binary='partial')
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(commands.read_text().split(), ['1', '2', '2', '2', '2', '3'])
        self.assertEqual(len((output / 'visual-trigger.rgb').read_bytes()), 8)
        result = json.loads((output / 'result.json').read_text())
        self.assertEqual(result['visualRecoveryOutcome'], 'trigger_evidence_unavailable')
        self.assertTrue(result['stopCommandAcknowledged'])
        self.assertFalse(result['searchFallbackStarted'])
        with self.assertRaises(ValueError):
            prior.audit.audit_run(output, visual_enabled=True, nav_limit=10, poll_limit=1)

    def test_unavailable_request_journal_does_not_prevent_stop(self):
        simulator = self.root / 'existing-trigger-closed-journal-simulator'
        marker = 's=socket.socket(fileno=3);step=100;visible=int(os.environ["SEARCH_TEST_VISIBLE"]);mode=os.environ["SEARCH_TEST_MODE"]'
        inject = '\nPath(sys.argv[sys.argv.index("--record")+1]).parent.joinpath("visual-trigger.rgb").write_bytes(b"preserve")'
        self.assertEqual(prior.prior.SIMULATOR.count(marker), 1)
        simulator.write_text(prior.prior.SIMULATOR.replace(marker, marker + inject))
        simulator.chmod(0o755)
        output, done, commands = self.visual_case('closed-journal', True, binary='bad-journal', simulator=simulator)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(commands.read_text().split(), ['1', '2', '2', '2', '2', '3'])
        self.assertEqual(json.loads((output / 'result.json').read_text())['visualRecoveryOutcome'],
                         'trigger_evidence_unavailable')
        journal = [json.loads(line)['command'] for line in (output / 'search-requests.jsonl').read_text().splitlines()]
        self.assertEqual(journal, [1, 2, 2, 2, 2])

    def test_missing_stop_ack_does_not_report_acknowledged(self):
        simulator = self.root / 'existing-trigger-bad-stop-simulator'
        marker = 's=socket.socket(fileno=3);step=100;visible=int(os.environ["SEARCH_TEST_VISIBLE"]);mode=os.environ["SEARCH_TEST_MODE"]'
        inject = '\nPath(sys.argv[sys.argv.index("--record")+1]).parent.joinpath("visual-trigger.rgb").write_bytes(b"preserve")'
        source = prior.prior.SIMULATOR.replace(marker, marker + inject)
        # Close the simulated peer as soon as it receives the stop command.
        needle = 'elif cmd==3:owner=2;valid=False;ack=7'
        self.assertEqual(source.count(needle), 1)
        source = source.replace(needle, 'elif cmd==3:s.close();sys.exit(1)')
        simulator.write_text(source)
        simulator.chmod(0o755)
        output, done, commands = self.visual_case('bad-stop-ack', True, simulator=simulator)
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(commands.read_text().split(), ['1', '2', '2', '2', '2', '3'])
        self.assertFalse((output / 'result.json').exists())
        self.assertEqual((output / 'visual-trigger.rgb').read_bytes(), b'preserve')


if __name__ == '__main__':
    unittest.main()
