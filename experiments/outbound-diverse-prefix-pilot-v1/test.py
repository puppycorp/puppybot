#!/usr/bin/env python3
"""CPU tests of the diverse pilot's input boundaries and paired worker."""
import contextlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


plan = load('diverse_plan_test', HERE / 'plan.py')
worker = load('diverse_worker_test', HERE / 'run.py')
monitor = load('diverse_monitor_test', HERE / 'monitor.py')
audit = load('diverse_pilot_prefix_test', HERE / 'audit.py')


class PlanTests(unittest.TestCase):
    def test_real_input_preflight_is_separate_and_pins_runner(self):
        data = plan.preflight(); rows = data['design']['rows']
        self.assertEqual(len(rows), 12)
        self.assertEqual([row['seed'] for row in rows], list(range(6910000, 6910012)))
        self.assertEqual({row['layout'] for row in rows if row['fitting']}, {27, 29, 31})
        self.assertEqual({row['layout'] for row in rows if not row['fitting']}, {33, 35, 37})
        self.assertEqual(sum(row['fitting'] for row in rows), 9)
        self.assertEqual(data['design']['gate']['backForthMetric'], 'pose20-prefix-bounded-final-inclusive-v1')
        self.assertFalse(data['selectionSeparation']['caseHashOverlap'])
        self.assertFalse(data['selectionSeparation']['environmentHashOverlap'])
        for name in ('plan.py', 'run.py', 'audit.py', 'monitor.py'):
            self.assertIn(str(HERE / name), data['sourceFiles'])
        self.assertIn(str(plan.ROOT / 'experiments/final-loop-window-v1/audit.py'), data['sourceFiles'])
        student = plan.command('student', plan.OUTPUT / 'student')
        teacher = plan.command('teacher', plan.OUTPUT / 'teacher')
        student_without_policy = student[:-2]
        student_without_policy[student_without_policy.index('--output') + 1] = str(plan.OUTPUT / 'teacher')
        self.assertEqual(student_without_policy, teacher)
        self.assertEqual(student[-2:], ['--policy', str(plan.prior.MODEL)])
        self.assertEqual(student[student.index('--scene-catalog') + 1], str(plan.CATALOG))

    def test_existing_catalog_is_preserved_before_preflight(self):
        with tempfile.TemporaryDirectory(prefix='diverse-catalog-existing-') as tmp:
            root = Path(tmp); output = root / 'pilot'; output.mkdir()
            marker = output / 'preserve'; marker.write_text('existing')
            with mock.patch.object(plan.prior, 'OUTPUT', output), \
                 mock.patch.object(plan.prior.register.base, 'acquire_lock', return_value=contextlib.nullcontext()), \
                 mock.patch.object(plan.prior, 'preflight') as preflight:
                with self.assertRaises(FileExistsError): plan.prepare_catalog()
                preflight.assert_not_called()
            self.assertEqual(marker.read_text(), 'existing')

    def test_current_selection_overlap_is_rejected(self):
        payload = json.loads(plan.SELECTION.read_text())
        first = payload['design']['tasks'][0]['rows'][0]
        scene = Path(first['scene'])
        row = {'files': {name: plan.prior.register.base.sha(scene / name)
                         for name in ('case.json', 'environment.bin', 'layout.json')}}
        with self.assertRaises(ValueError):
            plan.check_selection_separation([row])

    def test_changed_selection_bytes_change_registered_separation(self):
        data = plan.preflight(); scenes = data['scenes']
        selected = json.loads(plan.SELECTION.read_text())['design']['tasks'][0]['rows'][0]
        changed = Path(selected['scene']) / 'case.json'
        original_sha = plan.prior.register.base.sha
        def modified_sha(path):
            if Path(path) == changed: return 'f' * 64
            return original_sha(path)
        with mock.patch.object(plan.prior.register.base, 'sha', side_effect=modified_sha):
            after = plan.check_selection_separation(scenes)
        self.assertEqual(after['selectionManifestSHA256'], data['selectionSeparation']['selectionManifestSHA256'])
        self.assertNotEqual(after['selectionSceneHashesSHA256'], data['selectionSeparation']['selectionSceneHashesSHA256'])


class WorkerTests(unittest.TestCase):
    def exercise(self, fail_arm=None):
        with tempfile.TemporaryDirectory(prefix='diverse-pilot-test-') as temp:
            root = Path(temp); output = root / 'run'; inputs = {'input': 'hash'}; calls = []
            env = {'PATH': '/usr/bin:/bin'}
            def cmd(arm, target): return ['simulator', arm, str(target)]
            def prepare():
                output.mkdir(); return {'inputs': inputs}
            def freeze():
                return {'inputs': inputs, 'commands': {a: cmd(a, output / a) for a in ('student', 'teacher')},
                        'environment': env}
            def supervise(argv, directory, environment, seconds):
                calls.append((argv, environment, seconds))
                status = {'clientExit': 1 if argv[1] == fail_arm else 0, 'signal': None,
                          'timedOut': False, 'remainingWorkersTerminated': False, 'processGroup': 1}
                (directory / 'supervisor-result.json').write_text(json.dumps(status))
                return status
            result = {'status': 'screen_failed', 'trainingAuthorized': False}
            with contextlib.ExitStack() as stack:
                stack.enter_context(mock.patch.object(worker, 'P', root))
                stack.enter_context(mock.patch.object(worker, 'OUTPUT', output))
                stack.enter_context(mock.patch.object(worker, 'command', side_effect=cmd))
                stack.enter_context(mock.patch.object(worker, 'pin_inputs', return_value=inputs))
                stack.enter_context(mock.patch.object(worker.standalone, 'require_dedicated_process'))
                stack.enter_context(mock.patch.object(worker.plan, 'prepare_catalog', side_effect=prepare))
                stack.enter_context(mock.patch.object(worker.plan, 'freeze', side_effect=freeze))
                stack.enter_context(mock.patch.object(worker.plan, 'environment', return_value=env))
                stack.enter_context(mock.patch.object(worker.plan, 'verify_catalog'))
                stack.enter_context(mock.patch.object(worker.base, 'acquire_lock', return_value=contextlib.nullcontext()))
                stack.enter_context(mock.patch.object(worker.base, 'require_capacity'))
                stack.enter_context(mock.patch.object(worker.base.hidden, 'supervise', side_effect=supervise))
                stack.enter_context(mock.patch.object(worker.auditor, 'audit', return_value=result))
                if fail_arm:
                    with self.assertRaises(RuntimeError): worker.run()
                    self.assertEqual(json.loads((output / 'partial.json').read_text())['status'], 'censored')
                    self.assertFalse((output / 'report.json').exists())
                else:
                    self.assertEqual(worker.run(), result)
                    self.assertEqual(json.loads((output / 'report.json').read_text()), result)
                    self.assertEqual([entry[0][1] for entry in calls], ['student', 'teacher'])
                    self.assertTrue(all(entry[2] == 3600 for entry in calls))
                    self.assertFalse((output / 'partial.json').exists())

    def test_paired_worker_records_failed_screen_as_completed_diagnostic(self):
        self.exercise()

    def test_failed_first_arm_censors_without_starting_second(self):
        self.exercise('student')

    def test_failed_second_arm_censors_without_report(self):
        self.exercise('teacher')

    def test_supervisor_requires_clean_exit_and_cleanup(self):
        status = {'clientExit': 0, 'signal': None, 'timedOut': False,
                  'remainingWorkersTerminated': False, 'processGroup': 9}
        self.assertTrue(worker.clean(status))
        for key, value in (('clientExit', 1), ('signal', 9), ('timedOut', True),
                           ('remainingWorkersTerminated', True), ('processGroup', 0)):
            changed = status | {key: value}
            self.assertFalse(worker.clean(changed), key)


class PrefixReversalTests(unittest.TestCase):
    def rows(self, speeds, first=None):
        return [{'action': [0., speed], 'state': {'pose': [0., 0., 0.],
                'findReturn': {'consumedIndex': 0 if first is not None and i + 1 >= first else -1}}}
                for i, speed in enumerate(speeds)]

    def test_post_pickup_reversals_do_not_mark_prior_actions(self):
        rows = self.rows([1.] * 20 + [1., -1.] * 10, first=21)
        start = [0., 0., 0.]
        prior_marks = audit.prior.outbound.reversal_marks(rows, start)
        self.assertEqual(sum(i < 20 for i in prior_marks), 15)
        self.assertEqual(audit.prefix_reversal_steps(rows, start, 21), 0)

    def test_exactly_one_complete_prefix_window_is_counted(self):
        rows = self.rows([1., -1.] * 10 + [1.] * 20, first=21)
        self.assertEqual(audit.prefix_reversal_steps(rows, [0., 0., 0.], 21), 20)
        self.assertEqual(audit.prefix_reversal_steps(rows, [0., 0., 0.], 20), 0)

    def test_no_pickup_uses_all_actions_including_terminal_window(self):
        rows = self.rows([1., -1.] * 10)
        self.assertEqual(audit.prefix_reversal_steps(rows, [0., 0., 0.], None), 20)
        self.assertEqual(audit.prior.outbound.reversal_marks(rows, [0., 0., 0.]), set())

    def test_rejects_invalid_pickup_boundary(self):
        rows = self.rows([1.] * 20)
        for value in (0, 21, True, 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                audit.prefix_reversal_steps(rows, [0., 0., 0.], value)

    def test_audited_arm_uses_prefix_bounded_score(self):
        rows = self.rows([1.] * 20 + [1., -1.] * 10, first=21)
        game = {'rows': rows, 'first': 21, 'before': 15}; labels = {'checkedRows': 40}
        with tempfile.TemporaryDirectory(prefix='diverse-prefix-score-') as tmp:
            root = Path(tmp); folder = root / 'expert-0'; folder.mkdir()
            (folder / 'chase.jsonl').write_text(json.dumps({'event': 'start', 'robot': [0., 0., 0.]}) + '\n')
            with mock.patch.object(audit, 'original_audit_arm', return_value=([game], labels)):
                games, actual_labels = audit.audit_arm(root, 'teacher', {})
            self.assertEqual(games[0]['before'], 0)
            self.assertEqual(actual_labels, labels)

    def test_report_names_metric_and_cannot_authorize_training(self):
        with mock.patch.object(audit.prior, 'audit', return_value={'status': 'screen_failed', 'trainingAuthorized': False}):
            result = audit.audit()
        self.assertEqual(result['outboundBackForthMetric'], 'pose20-prefix-bounded-final-inclusive-v1')
        self.assertFalse(result['trainingAuthorized'])
        with mock.patch.object(audit.prior, 'audit', return_value={'status': 'screen_passed', 'trainingAuthorized': True}):
            with self.assertRaises(ValueError): audit.audit()

    def test_real_screen_uses_prefix_score_after_prior_arm_audits(self):
        teacher_rows = self.rows([1.] * 20 + [1., -1.] * 40, first=21)
        student_rows = self.rows([1.] * 100, first=60)
        with tempfile.TemporaryDirectory(prefix='diverse-prefix-screen-') as tmp:
            root = Path(tmp)
            for arm in ('student', 'teacher'):
                for index in range(12):
                    folder = root / arm / f'expert-{index}'; folder.mkdir(parents=True)
                    (folder / 'chase.jsonl').write_text(json.dumps({'event': 'start', 'robot': [0., 0., 0.]}) + '\n')
            def saved_arm(path, arm, inputs):
                rows, first = (student_rows, 60) if arm == 'student' else (teacher_rows, 21)
                return ([{'rows': rows, 'first': first, 'before': 15, 'initial': 'same', 'start': 'same'}
                         for _ in range(12)], {'checkedRows': 1200})
            with mock.patch.object(audit.plan, 'OUTPUT', root), mock.patch.object(audit.plan.prior, 'OUTPUT', root), \
                 mock.patch.object(audit.prior, 'verify_collection_evidence', return_value={}), \
                 mock.patch.object(audit, 'original_audit_arm', side_effect=saved_arm):
                result = audit.audit()
            self.assertEqual(result['status'], 'screen_passed')
            self.assertEqual(result['fittingHelpful'], 9)
            self.assertEqual(result['validationHelpful'], 3)
            self.assertFalse(result['trainingAuthorized'])


class MonitorTests(unittest.TestCase):
    def test_monitor_import_is_repeatable_in_a_fresh_process(self):
        code = ('import importlib.util,json,sys;'
                's=importlib.util.spec_from_file_location("m",sys.argv[1]);'
                'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);'
                'print(json.dumps({"worker":m.old.worker_command()[-1],"monitor":str(m.MONITOR),'
                '"pilot":str(m.pilot.OUTPUT)}))')
        done = subprocess.run([sys.executable, '-I', '-c', code, str(HERE / 'monitor.py')],
                              check=True, capture_output=True, text=True, timeout=20)
        result = json.loads(done.stdout)
        self.assertEqual(result['worker'], str(HERE / 'run.py'))
        self.assertEqual(result['monitor'], str(monitor.MONITOR))
        self.assertEqual(result['pilot'], str(monitor.pilot.OUTPUT))

    def test_preflight_pins_every_eager_local_monitor_import(self):
        code = '''import importlib.util,json,pathlib,sys
root=pathlib.Path(sys.argv[1]); seen=set(); original=importlib.util.module_from_spec
def tracked(spec):
 m=original(spec)
 if spec.origin and spec.origin.startswith(str(root)+"/") and spec.origin.endswith(".py"): seen.add(spec.origin)
 return m
importlib.util.module_from_spec=tracked
s=importlib.util.spec_from_file_location("m",root/"experiments/outbound-diverse-prefix-pilot-v1/monitor.py")
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
files=m.pilot.pin_inputs()["sourceFiles"]
print(json.dumps({"seen":len(seen),"missing":sorted(seen-set(files))}))
'''
        done = subprocess.run([sys.executable, '-I', '-c', code, str(plan.ROOT)],
                              check=True, capture_output=True, text=True, timeout=30)
        result = json.loads(done.stdout)
        self.assertGreater(result['seen'], 20)
        self.assertEqual(result['missing'], [])

    def test_spawned_worker_imports_the_diverse_entrypoint(self):
        self.assertEqual(monitor.old.worker_command()[-1], str(HERE / 'run.py'))
        self.assertIn('m.run()', monitor.old.worker_command()[-2])
        self.assertGreaterEqual(monitor.old.WORKER_SECONDS, 2 * 3600)
        self.assertGreater(monitor.old.OUTER_SECONDS, monitor.old.WORKER_SECONDS)

    def test_worker_rechecks_inputs_before_and_after_saved_audit(self):
        process = type('Process', (), {'pid': 123, 'returncode': 0, 'poll': lambda self: 0})()
        for changed in (False, True):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory(prefix='diverse-monitor-test-') as tmp:
                values = [{'input': 'original'}, {'input': 'changed' if changed else 'original'}, {'input': 'original'}]
                old = monitor.old
                with mock.patch.object(monitor.pilot, 'pin_inputs', side_effect=values), mock.patch.object(old, 'baseline'), \
                     mock.patch.object(old, 'sample_disk'), mock.patch.object(old, 'verify_logs'), mock.patch.object(old, 'require_disk'), \
                     mock.patch.object(old, 'verify_pilot', return_value={'status': 'screen_failed', 'trainingAuthorized': False}), \
                     mock.patch.object(old, 'inventory', return_value={}), \
                     mock.patch.object(old.telemetry, 'sample', return_value={'freeBytes': 8 * old.telemetry.GIB}), \
                     mock.patch.object(old.subprocess, 'Popen', return_value=process), \
                     mock.patch.object(old.os, 'pidfd_open', return_value=456), mock.patch.object(old.os, 'close'):
                    if changed:
                        with self.assertRaisesRegex(ValueError, 'inputs changed'): monitor.monitor_worker(tmp)
                        self.assertEqual(json.loads((Path(tmp) / 'monitor-result.json').read_text())['status'], 'failed')
                    else:
                        monitor.monitor_worker(tmp)
                        self.assertEqual(json.loads((Path(tmp) / 'monitor-result.json').read_text())['status'], 'passed')

    def test_outer_completion_requires_same_frozen_inputs_and_final_inventory(self):
        for mode in ('ok', 'changed-worker-inputs', 'bad-monitor', 'bad-final', 'training-authorized'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(prefix='diverse-outer-test-') as tmp:
                root = Path(tmp); target = root / 'monitor'; trial = root / 'trial'
                frozen = {'source': 'hash'}; report = {'status': 'screen_failed', 'trainingAuthorized': mode == 'training-authorized'}
                clean = {'clientExit': 0, 'signal': None, 'timedOut': False,
                         'remainingWorkersTerminated': False, 'processGroup': 123}
                def supervise(argv, directory, env, timeout):
                    if directory.name == 'final-inventory-monitor':
                        self.assertEqual(timeout, 300)
                        result = monitor.final_check(str(target), monitor.pilot.sha(target / 'evidence.json'))
                        (directory / 'client.log').write_text(json.dumps(result))
                        status = clean | {'timedOut': mode == 'bad-final'}
                        (directory / 'supervisor-result.json').write_text(json.dumps(status))
                        return status
                    self.assertEqual(timeout, 7900)
                    trial.mkdir(); (trial / 'report.json').write_text(json.dumps(report))
                    (target / 'monitor-result.json').write_text(json.dumps({'status': 'failed' if mode == 'bad-monitor' else 'passed'}))
                    (target / 'frozen-inputs.json').write_text(json.dumps({'source': 'changed'} if mode == 'changed-worker-inputs' else frozen))
                    (target / 'evidence.json').write_text(json.dumps({'status': 'diagnostic_only', 'report': report,
                                                                     'files': monitor.old.inventory(trial)}))
                    (target / 'telemetry.jsonl').write_text('fixture\n')
                    (target / 'disk.jsonl').write_text('fixture\n')
                    (directory / 'supervisor-result.json').write_text(json.dumps(clean))
                    return clean
                with mock.patch.object(monitor, 'MONITOR', target), mock.patch.object(monitor.pilot, 'OUTPUT', trial), \
                     mock.patch.object(monitor.pilot, 'pin_inputs', return_value=frozen), \
                     mock.patch.object(monitor.pilot.standalone, 'require_dedicated_process'), \
                     mock.patch.object(monitor.old, 'require_disk'), mock.patch.object(monitor.old, 'verify_logs'), \
                     mock.patch.object(monitor.pilot.base.hidden, 'supervise', side_effect=supervise):
                    if mode == 'ok':
                        self.assertEqual(monitor.launch(), report)
                        self.assertFalse(json.loads((target / 'completion.json').read_text())['trainingAuthorized'])
                    else:
                        with self.assertRaises((ValueError, RuntimeError)): monitor.launch()
                        self.assertFalse((target / 'completion.json').exists())


if __name__ == '__main__':
    unittest.main()
