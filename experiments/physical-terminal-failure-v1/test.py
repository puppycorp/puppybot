#!/usr/bin/env python3
"""Native protocol encoding and simulated peer tests for terminal failure."""
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


def function(source, name):
    start = source.index('fn ' + name + '(')
    return source[start:source.index('\nfn ', start + 1)]


transform = load('terminal_failure_transform', HERE / 'transform.py')
prior = load('terminal_failure_socket_tests', ROOT / 'experiments/physical-search-fallback-v1/test_search_client.py')


class TerminalFailureTests(prior.SearchClientTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        control = cls.shadow / 'control/test-candidate.flex'
        staged = cls.shadow / 'control/test-terminal-failure.flex'
        staged.write_text(transform.client(control.read_text()))
        subprocess.run([str(prior.prepare.COMPILER), str(staged), '-o', str(cls.root / 'client-terminal')],
                       cwd=ROOT, capture_output=True, text=True, timeout=120, check=True)
        current = (ROOT / 'flex/control/physical-client.flex').read_text()
        if function(current, 'pc_remember_terminal_failure') != function(staged.read_text(), 'pc_remember_terminal_failure'):
            raise ValueError('worktree client differs from tested terminal reporter')
        asset = 'vc_file_sha("build/flex/sim/puppybot.bin")'
        if current.count(asset) != 2:
            raise ValueError('unexpected current client asset check')
        current_path = cls.shadow / 'control/test-current-terminal.flex'
        current_path.write_text(current.replace(asset, 'vc_file_sha(case_path)'))
        subprocess.run([str(prior.prepare.COMPILER), str(current_path), '-o', str(cls.root / 'client-current')],
                       cwd=ROOT, capture_output=True, text=True, timeout=120, check=True)
        agent = cls.build / 'source/sim/agent.flex'
        agent.write_text(transform.simulator(agent.read_text()))
        current_agent = (ROOT / 'flex/sim/agent.flex').read_text()
        if function(current_agent, 'ps_physical_terminal_failure') != function(agent.read_text(), 'ps_physical_terminal_failure'):
            raise ValueError('worktree simulator differs from tested terminal reporter')
        main = cls.build / 'source/sim/main.flex'; source = main.read_text()
        if source.count('fn main(argc, argv) {') != 1:
            raise ValueError('unexpected simulator main')
        subprocess.run([str(prior.prepare.COMPILER), str(main), '-o', str(cls.root / 'simulator-terminal')],
                       cwd=ROOT, capture_output=True, text=True, timeout=120, check=True)
        main.write_text(source.replace('fn main(argc, argv) {', 'fn terminal_original_main(argc, argv) {', 1) + '''
fn main(argc, argv) {
    if !pl_init() { return 1; }
    let text = alloc(4096); let b = alloc(32); pl_builder(b, text, 4096);
    ps_physical_ack = 5; ps_case_stage = 13; ps_case_reason = "box not reacquired";
    pl_text(b, "{\\\"v\\\":1"); ps_physical_terminal_failure(b); pl_text(b, "}\\n");
    ps_case_stage = 12; pl_text(b, "{\\\"v\\\":1"); ps_physical_terminal_failure(b); pl_text(b, "}\\n");
    ps_case_stage = 13; ps_physical_ack = 4; pl_text(b, "{\\\"v\\\":1"); ps_physical_terminal_failure(b); pl_text(b, "}\\n");
    ps_physical_ack = 5; ps_case_reason = 0; pl_text(b, "{\\\"v\\\":1"); ps_physical_terminal_failure(b); pl_text(b, "}\\n");
    pl_print(1, text); return 0;
}
''')
        subprocess.run([str(prior.prepare.COMPILER), str(main), '-o', str(cls.root / 'terminal-server-probe')],
                       cwd=ROOT, capture_output=True, text=True, timeout=120, check=True)
        peer = prior.SIMULATOR.replace(
            '  if cmd==8 and mode=="missing-frame":del x["cameraFrame"]',
            '''  if cmd==7 and mode=="terminal-fail":x["collectorFailure"]='box not reacquired'
  if cmd==7 and mode=="terminal-stop-eof":x["collectorFailure"]='box not reacquired'
  if cmd==7 and mode=="terminal-bad-type":x["collectorFailure"]=False
  if cmd==7 and mode=="terminal-empty":x["collectorFailure"]=''
  if cmd==7 and mode=="terminal-oversize":x["collectorFailure"]='a'*129
  if cmd==7 and mode=="terminal-nul":x["collectorFailure"]='bad\\x00tail'
  if cmd==7 and mode=="terminal-escapes":x["collectorFailure"]='\\n'*128
  if cmd==8 and mode=="missing-frame":del x["cameraFrame"]''')
        peer = peer.replace('  elif cmd==3:owner=2;valid=False;ack=7',
                            '  elif cmd==3:\n   if mode=="terminal-stop-eof":break\n   owner=2;valid=False;ack=7')
        cls.simulator.write_text(peer)
        cls.simulator.chmod(0o755)

    def test_real_simulator_helper_emits_failure_only_for_failed_terminal(self):
        result = subprocess.run([str(self.root / 'terminal-server-probe')], cwd=ROOT,
                                capture_output=True, text=True, timeout=10, check=True)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(rows, [{'v': 1, 'collectorFailure': 'box not reacquired'}, {'v': 1}, {'v': 1},
                                {'v': 1, 'collectorFailure': 'collector failed'}])

    def test_client_stops_then_reports_collector_failure(self):
        output, done, commands, _ = self.run_case('terminal-fail', enabled=True, mode='terminal-fail', binary='terminal')
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(commands.read_text().split(), ['1', '2', '8', '7', '3'])
        report = json.loads((output / 'result.json').read_text())
        self.assertEqual(report['collectorFailure'], 'box not reacquired')
        self.assertTrue(report['stopCommandAcknowledged'])
        self.assertEqual(report['outcome'], 'unverified')
        self.assertNotIn('collectorFailureReportInvalid', report)

    def test_worktree_client_stops_then_reports_failure(self):
        output, done, commands, _ = self.run_case('worktree-terminal-fail', mode='terminal-fail',
                                                 visible=True, binary='current')
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(commands.read_text().split(), ['1', '6', '7', '3'])
        report = json.loads((output / 'result.json').read_text())
        self.assertEqual(report['collectorFailure'], 'box not reacquired')
        self.assertTrue(report['stopCommandAcknowledged'])
        self.assertEqual(report['outcome'], 'unverified')

    def test_invalid_detail_still_stops_and_is_not_reported_as_success(self):
        for mode in ('terminal-bad-type', 'terminal-empty', 'terminal-oversize', 'terminal-nul'):
            with self.subTest(mode=mode):
                output, done, commands, _ = self.run_case(mode, enabled=True, mode=mode, binary='terminal')
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual(commands.read_text().split(), ['1', '2', '8', '7', '3'])
                report = json.loads((output / 'result.json').read_text())
                self.assertTrue(report['collectorFailureReportInvalid'])
                self.assertTrue(report['stopCommandAcknowledged'])
                self.assertNotIn('collectorFailure', report)
                self.assertEqual(report['outcome'], 'unverified')

    def test_maximum_escaped_reason_fits_result(self):
        output, done, commands, _ = self.run_case('terminal-escapes', enabled=True, mode='terminal-escapes', binary='terminal')
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(commands.read_text().split(), ['1', '2', '8', '7', '3'])
        self.assertEqual(json.loads((output / 'result.json').read_text())['collectorFailure'], '\n' * 128)

    def test_missing_stop_ack_never_produces_a_result(self):
        output, done, commands, _ = self.run_case('terminal-stop-eof', enabled=True, mode='terminal-stop-eof', binary='terminal')
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(commands.read_text().split(), ['1', '2', '8', '7', '3'])
        self.assertFalse((output / 'result.json').exists())

    def test_legacy_peer_remains_unverified_and_result_compatible(self):
        normal, done, _, _ = self.run_case('terminal-legacy', enabled=True, binary='terminal')
        baseline, old, _, _ = self.run_case('terminal-legacy-baseline', enabled=True, binary='candidate')
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(old.returncode, 0, old.stderr)
        self.assertEqual((normal / 'result.json').read_bytes(), (baseline / 'result.json').read_bytes())


if __name__ == '__main__':
    unittest.main()
