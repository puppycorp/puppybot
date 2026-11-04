#!/usr/bin/env python3
"""CPU-only monitored selection receipt and standalone audit gates."""
import importlib.util
import json
import sys
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
S = ROOT / 'datasets/visual-control/chase-v1/levels'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


r = load('selection_receipt_test', S / 'heading-selection-receipt.py')


class ReceiptTest(unittest.TestCase):
    def test_telemetry_and_disk_guard_rejection(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(r, 'MONITORED', Path(tmp)):
            root = Path(tmp)
            def gpu(phase, t):
                return {'phase': phase, 'monotonicSeconds': t, 'unixSeconds': t, 'busyPercent': 3,
                        'totalBytes': 16 * r.GIB, 'usedBytes': 8 * r.GIB, 'freeBytes': 8 * r.GIB}
            original_gpu = [gpu('baseline', t) for t in range(100, 131)] + [gpu('selection', 131), gpu('after-selection', 132)]
            original_disk = [{'phase': phase, 'monotonicSeconds': t, 'unixSeconds': t, 'freeBytes': 34 * r.GIB}
                             for phase, t in [('pre-baseline', 99), ('post-baseline', 130.5),
                                              ('selection', 131.5), ('after-selection', 132.5)]]
            def write(gpu_rows, disk_rows):
                (root / 'telemetry.jsonl').write_text(''.join(json.dumps(x) + '\n' for x in gpu_rows))
                (root / 'disk.jsonl').write_text(''.join(json.dumps(x) + '\n' for x in disk_rows))
            write(original_gpu, original_disk); r.validate_telemetry()
            busy = [dict(x) for x in original_gpu]
            for row in busy[:5]: row['busyPercent'] = 11
            write(busy, original_disk)
            with self.assertRaisesRegex(ValueError, 'busy guard'): r.validate_telemetry()
            low = [dict(x) for x in original_gpu]; low[-1]['usedBytes'] = 15 * r.GIB; low[-1]['freeBytes'] = r.GIB
            write(low, original_disk)
            with self.assertRaisesRegex(ValueError, 'free memory'): r.validate_telemetry()
            write(original_gpu[:-1], original_disk)
            with self.assertRaisesRegex(ValueError, 'final sample'): r.validate_telemetry()
            low_disk = [dict(x) for x in original_disk]; low_disk[-1]['freeBytes'] = 32 * r.GIB
            write(original_gpu, low_disk)
            with self.assertRaisesRegex(ValueError, 'disk headroom'): r.validate_telemetry()
            missing_disk = [dict(x) for x in original_disk[:-1]]
            write(original_gpu, missing_disk)
            with self.assertRaisesRegex(ValueError, 'disk samples incomplete'): r.validate_telemetry()

    def test_complete_receipt_and_negative_evidence_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); selection = root / 'selection'; selection.mkdir()
            monitored = root / 'monitor'; monitored.mkdir(); (monitored / 'outer-monitor').mkdir()
            wrapper = root / 'wrapper.py'; wrapper.write_text('wrapper')
            plan = root / 'plan.json'
            design = [{'name': name, 'level': index, 'levelArgs': [] if index == 0 else ['--level', str(index)],
                       'twoRoom': index >= 4} for index, name in enumerate(r.TASKS)]
            plan.write_text(json.dumps({'tasks': design}))
            clean = {'clientExit': 0, 'signal': None, 'timedOut': False,
                     'remainingWorkersTerminated': False, 'processGroup': 123}
            (monitored / 'outer-monitor/supervisor-result.json').write_text(json.dumps(clean))
            (monitored / 'monitor-result.json').write_text('{"status":"passed"}')
            def gpu(phase, t):
                return {'phase': phase, 'monotonicSeconds': t, 'unixSeconds': t, 'busyPercent': 3,
                        'totalBytes': 16 * r.GIB, 'usedBytes': 8 * r.GIB, 'freeBytes': 8 * r.GIB}
            gpu_rows = [gpu('baseline', t) for t in range(100, 131)] + [gpu('selection', 131), gpu('after-selection', 132)]
            disk_rows = [{'phase': phase, 'monotonicSeconds': t, 'unixSeconds': t, 'freeBytes': 34 * r.GIB}
                         for phase, t in [('pre-baseline', 99), ('post-baseline', 130.5), ('selection', 131.5), ('after-selection', 132.5)]]
            (monitored / 'telemetry.jsonl').write_text(''.join(json.dumps(x) + '\n' for x in gpu_rows))
            (monitored / 'disk.jsonl').write_text(''.join(json.dumps(x) + '\n' for x in disk_rows))
            code = ('import importlib.util,sys;'
                    's=importlib.util.spec_from_file_location("monitored",sys.argv[1]);'
                    'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);'
                    'm.monitor_worker(sys.argv[2])')
            env = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'SDL_VIDEODRIVER': 'offscreen',
                   'LD_LIBRARY_PATH': str(r.ROOT / 'build/flex/rocm-runtime')}
            (monitored / 'launch.json').write_text(json.dumps({'sourcePins': {'source.fixture': 'hash'},
                'command': [sys.executable, '-I', '-c', code, str(wrapper), str(monitored)],
                'environment': env, 'wallSeconds': 65400}))
            tasks = {}
            with mock.patch.object(r, 'SELECTION', selection):
                runner_tasks = [{'task': task['name'], 'arms': [{'argv': r.arm_command(task, arm), 'environment': r.environment(task)}
                                for arm in ('control', 'treatment')]} for task in design]
                (selection / 'launch.json').write_text(json.dumps({'planSHA256': r.digest(plan),
                    'files': r.expected_runner_pins(sys.executable), 'tasks': runner_tasks}))
            for task in design:
                name = task['name']
                statuses = {}
                for arm in ('control', 'treatment'):
                    statuses[arm] = {'status': 'saved_arm_audit_only', 'task': name, 'arm': arm}
                pair = {'status': 'paired_selection_audit_only', 'task': name}
                tasks[name] = {'status': 'paired_saved_audit', 'arms': statuses, 'pair': pair}
                for mode in ('run-control', 'run-treatment', 'audit-control', 'audit-treatment', 'audit-pair'):
                    folder = selection / f'evidence-{name}' / mode; folder.mkdir(parents=True)
                    (folder / 'supervisor-result.json').write_text(json.dumps(clean))
                    kind, which = mode.split('-', 1)
                    with mock.patch.object(r, 'SELECTION', selection):
                        argv = r.arm_command(task, which) if kind == 'run' else [sys.executable, '-I', str(r.WORKER), which, name]
                    (folder / 'invocation.json').write_text(json.dumps({'argv': argv, 'environment': r.environment(task),
                                                                        'wallSeconds': 3600 if kind == 'run' else 600}))
                    value = 'fixture' if kind == 'run' else json.dumps(pair if which == 'pair' else statuses[which])
                    (folder / 'client.log').write_text(value)
            with mock.patch.object(r, 'SELECTION', selection), mock.patch.object(r, 'MONITORED', monitored), \
                 mock.patch.object(r, 'MONITOR_SCRIPT', wrapper), mock.patch.object(r, 'PLAN', plan), \
                 mock.patch.object(r, 'source_pins', return_value={'source.fixture': 'hash'}):
                with self.assertRaises(FileNotFoundError): r.verify()
                summary = {'status': 'selection_comparison_only', 'tasks': tasks, 'inventory': r.inventory()}
                (selection / 'selection-summary.json').write_text(json.dumps(summary))
                (monitored / 'completion.json').write_text(json.dumps({'status': 'passed', 'hashes': r.snapshot(),
                                                                      'freeBytesBeforeReceipt': 33 * r.GIB}))
                self.assertEqual(r.verify()['status'], 'passed')
                trace = selection / 'evidence-L3/run-control/client.log'; trace.write_text('changed')
                with self.assertRaisesRegex(ValueError, 'inventory changed'): r.verify()
                trace.write_text('fixture')
                invocation = selection / 'evidence-L3/run-control/invocation.json'
                original = invocation.read_text(); changed = json.loads(original)
                changed['argv'] = r.arm_command(design[2], 'control'); invocation.write_text(json.dumps(changed))
                summary['inventory'] = r.inventory(); (selection / 'selection-summary.json').write_text(json.dumps(summary))
                with self.assertRaisesRegex(ValueError, 'invocation intent differs'): r.snapshot()
                invocation.write_text(original)
                audit_log = selection / 'evidence-L3/audit-control/client.log'; original_log = audit_log.read_text()
                audit_log.write_text(json.dumps(tasks['L2']['arms']['control']))
                summary['inventory'] = r.inventory(); (selection / 'selection-summary.json').write_text(json.dumps(summary))
                with self.assertRaisesRegex(ValueError, 'saved audit output differs'): r.snapshot()
                audit_log.write_text(original_log)
                summary['inventory'] = r.inventory(); (selection / 'selection-summary.json').write_text(json.dumps(summary))
                bad = dict(clean); bad['timedOut'] = True
                status = selection / 'evidence-L4/audit-pair/supervisor-result.json'; status.write_text(json.dumps(bad))
                with self.assertRaisesRegex(ValueError, 'unclean'): r.verify()
                status.write_text(json.dumps(clean))
                (selection / 'selection.partial.json').write_text('{}')
                with self.assertRaisesRegex(ValueError, 'partial evidence'): r.verify()
                (selection / 'selection.partial.json').unlink()
                with mock.patch.object(r, 'source_pins', return_value={'source.fixture': 'tampered'}):
                    with self.assertRaisesRegex(ValueError, 'receipt differs'): r.verify()

    def test_standalone_audit_rejects_missing_completion_before_output(self):
        audit = load('selection_audit_gate', S / 'heading-selection-audit.py')
        with mock.patch.object(audit.sys, 'argv', ['audit', '/plan', 'L5']), \
             mock.patch.object(audit.plan_tool.base, 'acquire_lock', return_value=nullcontext()), \
             mock.patch.object(audit.monitored_receipt, 'verify', side_effect=ValueError('no completion')), \
             mock.patch.object(audit, 'audit_pair') as pair:
            with self.assertRaisesRegex(ValueError, 'no completion'): audit.main()
            pair.assert_not_called()


if __name__ == '__main__': unittest.main()
