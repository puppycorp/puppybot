#!/usr/bin/env python3
"""CPU-only freeze, censoring, invocation and receipt controls."""
import contextlib
import io
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
S = ROOT / 'datasets/visual-control/chase-v1/levels'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


f = load('teacher_frozen_fixture', S / 'heading-teacher-frozen-v1.py')
r = load('teacher_runner_fixture', S / 'run-heading-teacher-v1.py')
receipt = load('teacher_receipt_fixture', S / 'heading-teacher-receipt-v1.py')
monitor = load('teacher_monitor_fixture', ROOT / 'flex/tests/monitored-heading-teacher-v1.py')
worker = load('teacher_worker_fixture', S / 'heading-teacher-worker-v1.py')


class TeacherScaffoldTests(unittest.TestCase):
    def test_worker_uses_task_and_exact_saved_pool_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); reports = {}
            for level in ('L1', 'L2', 'L3', 'L4', 'L5'):
                path = root / f'evidence-{level}/audit'; path.mkdir(parents=True)
                reports[level] = {'status': 'complete_diagnostic', 'task': level}
                (path / 'client.log').write_text(json.dumps(reports[level]))
            with mock.patch.object(worker.draft, 'TEACHER_ROOT', root), \
                 mock.patch.object(worker.sys, 'argv', ['worker', 'L4']), \
                 mock.patch.object(worker.audit, 'audit_task', return_value={'status': 'complete_diagnostic'}) as task, \
                 contextlib.redirect_stdout(io.StringIO()):
                worker.main()
            self.assertEqual(task.call_args.args[0], 'L4')
            self.assertEqual(task.call_args.args[1], root / 'L4')
            with mock.patch.object(worker.draft, 'TEACHER_ROOT', root), \
                 mock.patch.object(worker.sys, 'argv', ['worker', 'pool']), \
                 mock.patch.object(worker.audit, 'audit_pool', return_value={'status': 'complete_diagnostic'}) as pool, \
                 contextlib.redirect_stdout(io.StringIO()):
                worker.main()
            pool.assert_called_once_with(reports)

    def test_censored_audit_cannot_pass_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            for index, report in enumerate(({'status': 'censored'},
                                            {'status': 'complete_diagnostic', 'task': 'L2'},
                                            {'status': 'complete_diagnostic', 'levels': ['L1']},
                                            {'status': 'complete_diagnostic', 'task': 'L3', 'level': True})):
                folder = Path(tmp) / str(index); folder.mkdir()
                def supervised(argv, directory, env, limit):
                    directory.mkdir(); (directory / 'client.log').write_text(json.dumps(report))
                with mock.patch.object(r, 'supervised', side_effect=supervised):
                    with self.assertRaisesRegex(ValueError, 'censored'): r.audit('pool' if index == 2 else 'L3', folder, {})

    def test_freeze_exclusive_and_detects_changing_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); plan = root / 'plan.json'
            with mock.patch.object(f, 'PLAN', plan), mock.patch.object(f, 'OUTPUT', root / 'out'), \
                 mock.patch.object(f, 'MONITORED', root / 'monitor'), \
                 mock.patch.object(f.base, 'acquire_lock', return_value=contextlib.nullcontext()), \
                 mock.patch.object(f.base, 'require_capacity'), mock.patch.object(f, 'current_plan', side_effect=[{'x': 1}, {'x': 2}]):
                with self.assertRaisesRegex(ValueError, 'changed'): f.freeze()
                self.assertFalse(plan.exists())
            with mock.patch.object(f, 'PLAN', plan), mock.patch.object(f, 'OUTPUT', root / 'out'), \
                 mock.patch.object(f, 'MONITORED', root / 'monitor'), \
                 mock.patch.object(f.base, 'acquire_lock', return_value=contextlib.nullcontext()), \
                 mock.patch.object(f.base, 'require_capacity'), mock.patch.object(f, 'current_plan', return_value={'x': 1}):
                self.assertEqual(f.freeze(), {'x': 1}); self.assertEqual(f.verify(), {'x': 1})
                with self.assertRaises(ValueError): f.freeze()
                self.assertEqual(json.loads(plan.read_text()), {'x': 1})

    def test_runner_censors_partial_and_never_runs_later_tasks(self):
        tasks = f.draft.draft()['tasks']; plan = {'draft': {'tasks': tasks}, 'sourcePins': {'fixture': 'hash'}}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); output = root / 'out'; calls = []
            def supervised(argv, directory, env, limit): calls.append(argv); directory.mkdir()
            def audit(name, evidence, env):
                if name == 'L2': raise ValueError('synthetic incomplete teacher')
                return {'status': 'complete_diagnostic', 'task': name}
            with mock.patch.object(r.frozen, 'OUTPUT', output), mock.patch.object(r.frozen, 'P', root), \
                 mock.patch.object(r.base, 'acquire_lock', return_value=contextlib.nullcontext()), \
                 mock.patch.object(r.base, 'require_capacity'), mock.patch.object(r.base, 'sha', return_value='hash'), \
                 mock.patch.object(r.frozen, 'verify', return_value=plan), mock.patch.object(r.frozen, 'pins', return_value=plan['sourcePins']), \
                 mock.patch.object(r, 'supervised', side_effect=supervised), mock.patch.object(r, 'audit', side_effect=audit):
                with self.assertRaisesRegex(ValueError, 'incomplete teacher'): r.run()
            partial = json.loads((output / 'teacher.partial.json').read_text())
            self.assertEqual(partial['tasks']['L2']['status'], 'censored')
            self.assertEqual(partial['tasks']['L3']['status'], 'not_started')
            self.assertEqual(len(calls), 3)
            self.assertFalse((output / 'teacher-summary.json').exists())

    def test_monitor_disk_threshold_and_disabled_entrypoints(self):
        from types import SimpleNamespace
        with mock.patch.object(monitor.shutil, 'disk_usage', return_value=SimpleNamespace(free=34 * f.GIB - 1)):
            import io
            with self.assertRaisesRegex(RuntimeError, '34 GiB'): monitor.disk_sample(io.StringIO(), 'selection')
        import subprocess
        for path in (S / 'heading-teacher-frozen-v1.py', S / 'run-heading-teacher-v1.py',
                     ROOT / 'flex/tests/monitored-heading-teacher-v1.py'):
            result = subprocess.run([sys.executable, '-I', str(path)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0); self.assertIn('Disabled pending', result.stderr)

    def test_receipt_binds_all_task_intents_and_audits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); out = root / 'out'; out.mkdir(); mon = root / 'monitor'; mon.mkdir()
            (mon / 'outer-monitor').mkdir(); planfile = root / 'plan.json'; planfile.write_text('{}')
            tasks = f.draft.draft()['tasks']; plan = {'draft': {'tasks': tasks}, 'sourcePins': {'fixture': 'hash'}}
            clean = {'clientExit': 0, 'signal': None, 'timedOut': False,
                     'remainingWorkersTerminated': False, 'processGroup': 123}
            (mon / 'outer-monitor/supervisor-result.json').write_text(json.dumps(clean))
            (mon / 'monitor-result.json').write_text('{"status":"passed"}')
            (mon / 'telemetry.jsonl').write_text('fixture'); (mon / 'disk.jsonl').write_text('fixture')
            code = ('import importlib.util,sys;s=importlib.util.spec_from_file_location("teacher_monitor",sys.argv[1]);'
                    'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.monitor_worker(sys.argv[2])')
            env = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'SDL_VIDEODRIVER': 'offscreen',
                   'LD_LIBRARY_PATH': str(ROOT / 'build/flex/rocm-runtime')}
            (mon / 'launch.json').write_text(json.dumps({'command': [sys.executable, '-I', '-c', code, str(f.MONITOR), str(mon)],
                'environment': env, 'wallSeconds': 32600, 'sourcePins': plan['sourcePins']}))
            worker = ('import importlib.util,sys;s=importlib.util.spec_from_file_location("teacher_runner",sys.argv[1]);'
                      'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.run()')
            (mon / 'worker-invocation.json').write_text(json.dumps({'argv': [sys.executable, '-I', '-c', worker, str(f.RUNNER)], 'cwd': str(ROOT)}))
            (out / 'launch.json').write_text(json.dumps({'planSHA256': f.base.sha(planfile), 'tasks': tasks}))
            items = {}
            def evidence(name, argv, task_env, limit, result=None):
                directory = out / name; directory.mkdir(parents=True)
                (directory / 'supervisor-result.json').write_text(json.dumps(clean))
                (directory / 'invocation.json').write_text(json.dumps({'argv': argv, 'cwd': str(ROOT), 'environment': task_env, 'wallSeconds': limit}))
                if result is not None: (directory / 'client.log').write_text(json.dumps(result))
            for task in tasks:
                name = task['name']; report = {'status': 'complete_diagnostic', 'task': name, 'level': task['level'],
                    'results': {arm: {'games': 32, 'simulatedMinutes': 32, 'deliveries': 0, 'gamesWithDelivery': 0}
                                for arm in ('control', 'treatment', 'teacher')}}
                items[name] = {'status': 'complete_diagnostic', 'audit': report}
                evidence(f'evidence-{name}/run', task['argv'], task['environment'], 3600)
                evidence(f'evidence-{name}/audit', [sys.executable, '-I', str(f.WORKER), name], task['environment'], 600, report)
            pool = receipt.teacher_audit.audit_pool({name: items[name]['audit'] for name in ('L1', 'L2', 'L3', 'L4', 'L5')})
            evidence('evidence-pool/audit', [sys.executable, '-I', str(f.WORKER), 'pool'], tasks[0]['environment'], 600, pool)
            with mock.patch.object(receipt.frozen, 'OUTPUT', out), mock.patch.object(receipt.frozen, 'MONITORED', mon), \
                 mock.patch.object(receipt.frozen, 'PLAN', planfile), mock.patch.object(receipt.frozen, 'verify', return_value=plan), \
                 mock.patch.object(receipt.selection_receipt, 'validate_telemetry'), \
                 mock.patch.object(receipt.selection_receipt, 'read_samples', return_value=[{'freeBytes': x * f.GIB} for x in (39, 39, 35, 35)]):
                summary = {'status': 'teacher_comparison_diagnostic_only', 'tasks': items, 'pool': pool, 'inventory': receipt.inventory()}
                (out / 'teacher-summary.json').write_text(json.dumps(summary))
                self.assertIn('summary', receipt.snapshot())
                bad = out / 'evidence-L4/audit/invocation.json'; original = bad.read_text(); value = json.loads(original); value['argv'][-1] = 'L3'; bad.write_text(json.dumps(value))
                with self.assertRaisesRegex(ValueError, 'invocation differs'): receipt.snapshot()
                bad.write_text(original)
                audit_log = out / 'evidence-L2/audit/client.log'; original = audit_log.read_text()
                audit_log.write_text(json.dumps({'status': 'complete_diagnostic', 'task': 'L3'}))
                with self.assertRaisesRegex(ValueError, 'audit differs'): receipt.snapshot()
                audit_log.write_text(original)
                status = out / 'evidence-L5/run/supervisor-result.json'; original = status.read_text()
                status.write_text(json.dumps(dict(clean, timedOut=True)))
                with self.assertRaisesRegex(ValueError, 'unclean'): receipt.snapshot()
                status.write_text(original)
                (out / 'teacher.partial.json').write_text('{}')
                with self.assertRaisesRegex(ValueError, 'completed teacher'): receipt.snapshot()
                (out / 'teacher.partial.json').unlink()
                with mock.patch.object(receipt.selection_receipt, 'read_samples', return_value=[{'freeBytes': x * f.GIB} for x in (39, 39, 33, 35)]):
                    with self.assertRaisesRegex(ValueError, 'disk headroom'): receipt.snapshot()
                with mock.patch.object(receipt.selection_receipt, 'read_samples', return_value=[{'freeBytes': x * f.GIB} for x in (37, 39, 35, 35)]):
                    with self.assertRaisesRegex(ValueError, 'disk headroom'): receipt.snapshot()
                pool_path = out / 'evidence-pool/audit/client.log'; original = pool_path.read_text()
                bad_pool = dict(pool); bad_pool['results'] = dict(pool['results']); bad_pool['results']['teacher'] = dict(pool['results']['teacher'], deliveries=99)
                summary['pool'] = bad_pool; pool_path.write_text(json.dumps(bad_pool))
                (out / 'teacher-summary.json').write_text(json.dumps(summary))
                with self.assertRaisesRegex(ValueError, 'disagrees with task'): receipt.snapshot()
                pool_path.write_text(original)
                with self.assertRaises(FileNotFoundError): receipt.verify()


if __name__ == '__main__': unittest.main()
