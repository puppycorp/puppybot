#!/usr/bin/env python3
"""CPU-only checks for the pre-game GPU-baseline retry adapter."""
import importlib.util
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('fresh_retry_test', HERE / 'retry.py')
retry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retry)


class RetryTests(unittest.TestCase):
    def fixture(self, directory):
        root = Path(directory); plan = root / 'plan.json'; monitored = root / 'monitor'
        (monitored / 'outer-monitor').mkdir(parents=True)
        links = {}
        for task in retry.base.design()['tasks']:
            for row in task['rows']:
                links.update(retry.base.scene_links(row))
        frozen = {'status': 'frozen_before_play', 'design': retry.base.design(), 'files': {},
                  'runtime': retry.base.old.runtime_chain(), 'sceneLinks': links}
        plan.write_text(json.dumps(frozen))
        (monitored / 'frozen-manifest.json').write_text(json.dumps(frozen))
        (monitored / 'monitor-result.json').write_text(json.dumps({
            'status': 'failed', 'reason': 'GPU busy above 10% for five consecutive samples'}))
        (monitored / 'outer-monitor/supervisor-result.json').write_text(json.dumps({
            'clientExit': 1, 'signal': None, 'timedOut': False, 'remainingWorkersTerminated': False}))
        (monitored / 'telemetry.jsonl').write_text(''.join(json.dumps({
            'phase': 'baseline', 'busyPercent': 42}) + '\n' for _ in range(5)))
        (monitored / 'launch.json').write_text('{}')
        (monitored / 'disk.jsonl').write_text('{}\n')
        (monitored / 'outer-monitor/client.log').write_text('baseline failed\n')
        return plan, root / 'prior-output', monitored

    def test_real_prior_is_terminal_before_games(self):
        self.assertEqual(retry.check_prior()['status'], 'frozen_before_play')
        self.assertFalse(retry.PRIOR_OUTPUT.exists())

    def test_rejects_started_or_incomplete_prior(self):
        for kind in ('game-output', 'worker', 'wrong-reason', 'busy-under-limit', 'timed-out'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(prefix='fresh-retry-test-') as tmp:
                plan, output, monitored = self.fixture(tmp)
                if kind == 'game-output': output.mkdir()
                elif kind == 'worker': (monitored / 'worker.log').touch()
                elif kind == 'wrong-reason': (monitored / 'monitor-result.json').write_text('{}')
                elif kind == 'busy-under-limit':
                    (monitored / 'telemetry.jsonl').write_text((json.dumps({'phase': 'baseline', 'busyPercent': 10}) + '\n') * 5)
                else:
                    status = json.loads((monitored / 'outer-monitor/supervisor-result.json').read_text())
                    status['timedOut'] = True
                    (monitored / 'outer-monitor/supervisor-result.json').write_text(json.dumps(status))
                with mock.patch.object(retry, 'PRIOR_PLAN', plan), mock.patch.object(retry, 'PRIOR_OUTPUT', output), \
                        mock.patch.object(retry, 'PRIOR_MONITOR', monitored):
                    with self.assertRaises(ValueError): retry.check_prior()

    def test_prior_receipts_are_pinned(self):
        with tempfile.TemporaryDirectory(prefix='fresh-retry-test-') as tmp:
            plan, output, monitored = self.fixture(tmp)
            with mock.patch.object(retry, 'PRIOR_PLAN', plan), mock.patch.object(retry, 'PRIOR_OUTPUT', output), \
                    mock.patch.object(retry, 'PRIOR_MONITOR', monitored), \
                    mock.patch.object(retry, 'prior_source_paths', return_value=[]):
                paths = retry.source_paths()
                self.assertEqual(set(paths), set(retry.prior_files() + [HERE / 'retry.py']))

    def test_changed_prior_input_rejected(self):
        with tempfile.TemporaryDirectory(prefix='fresh-retry-test-') as tmp:
            plan, output, monitored = self.fixture(tmp)
            source = Path(tmp) / 'source'; source.write_text('changed')
            frozen = json.loads(plan.read_text())
            frozen['files'] = {str(source): hashlib.sha256(b'original').hexdigest()}
            plan.write_text(json.dumps(frozen))
            (monitored / 'frozen-manifest.json').write_text(json.dumps(frozen))
            with mock.patch.object(retry, 'PRIOR_PLAN', plan), mock.patch.object(retry, 'PRIOR_OUTPUT', output), \
                    mock.patch.object(retry, 'PRIOR_MONITOR', monitored):
                with self.assertRaisesRegex(ValueError, 'input changed'): retry.check_prior()

    def test_changed_runtime_chain_or_scene_link_rejected(self):
        for kind in ('runtime', 'scene'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(prefix='fresh-retry-test-') as tmp:
                plan, output, monitored = self.fixture(tmp)
                with mock.patch.object(retry, 'PRIOR_PLAN', plan), mock.patch.object(retry, 'PRIOR_OUTPUT', output), \
                        mock.patch.object(retry, 'PRIOR_MONITOR', monitored):
                    if kind == 'runtime':
                        with mock.patch.object(retry.base.old, 'runtime_chain', return_value={'/retargeted': 'link'}):
                            with self.assertRaisesRegex(ValueError, 'runtime symlink chain changed'): retry.check_prior()
                    else:
                        with mock.patch.object(retry.base, 'scene_links', return_value={'/training-link': '../other'}):
                            with self.assertRaisesRegex(ValueError, 'scene links changed'): retry.check_prior()

    def test_each_subprocess_reloads_v2_bindings(self):
        value = json.loads(subprocess.check_output(retry.python_call('describe_configuration'), text=True))
        self.assertEqual(value['registration'], str(HERE / 'retry.py'))
        self.assertEqual(value['output'], str(retry.OUTPUT))
        self.assertEqual(value['worker'], retry.python_call('run'))
        self.assertIn('fresh-policy-selection-v2', retry.base.command(retry.base.design()['tasks'][0], 'control')[2])
        self.assertEqual(retry.base.SEED, 7820000)

    def test_old_files_and_resource_gates_are_unchanged(self):
        self.assertNotEqual(retry.MANIFEST, retry.PRIOR_PLAN)
        self.assertNotEqual(retry.MONITOR, retry.PRIOR_MONITOR)
        self.assertNotEqual(retry.OUTPUT, retry.PRIOR_OUTPUT)
        retry.configure_monitor()
        self.assertEqual(retry.base.monitor.OUTPUT, retry.OUTPUT)
        # The retry only rebinds monitor paths; the original monitor module is
        # reused, including its 30-second baseline and 34/32 GiB thresholds.
        self.assertEqual(retry.base.monitor.baseline.__module__, retry.base.monitor.__name__)

    def test_launch_reaches_supervisor_without_touching_prior(self):
        with tempfile.TemporaryDirectory(prefix='fresh-retry-launch-') as tmp:
            root = Path(tmp); monitored = root / 'v2-monitor'; output = root / 'v2-output'
            with mock.patch.object(retry, 'MONITOR', monitored), mock.patch.object(retry, 'OUTPUT', output), \
                    mock.patch.object(retry.base, 'MONITOR', monitored), mock.patch.object(retry.base, 'OUTPUT', output), \
                    mock.patch.object(retry.base, 'verify', return_value={'files': {}}), \
                    mock.patch.object(retry.base.guard, 'require_dedicated_process'), \
                    mock.patch.object(retry.base.monitor, 'require_disk'), \
                    mock.patch.object(retry.base.base.hidden, 'supervise', return_value={'clientExit': 1}) as supervise:
                with self.assertRaisesRegex(RuntimeError, 'resource monitor failed'): retry.launch()
                argv = supervise.call_args.args[0]
                self.assertIn(str(HERE / 'retry.py'), argv)
                self.assertIn('monitor_worker', argv)
                self.assertFalse(output.exists())
                self.assertTrue((monitored / 'launch.json').is_file())


if __name__ == '__main__':
    unittest.main()
