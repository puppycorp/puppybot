#!/usr/bin/env python3
"""CPU checks for the fresh training-family comparison design."""
import importlib.util
import json
import subprocess
import tempfile
import unittest
from contextlib import ExitStack, nullcontext
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('fresh_selection_test', HERE / 'selection.py')
selection = importlib.util.module_from_spec(spec); spec.loader.exec_module(selection)


class SelectionTests(unittest.TestCase):
    def test_design(self):
        design = selection.design()
        self.assertEqual([x['level'] for x in design['tasks']], [1, 2, 3, 4, 5])
        self.assertEqual(design['arms'], ['control', 'treatment', 'teacher'])
        for task in design['tasks']:
            self.assertEqual(len(task['rows']), 32)
            self.assertEqual([x['seed'] for x in task['rows']], list(range(7820000, 7820032)))
            self.assertTrue(all(x['layout'] in ({13, 15, 17} if task['level'] >= 4 else set(range(12, 18))) for x in task['rows']))

    def test_commands_and_auditor_seed(self):
        for task in selection.design()['tasks']:
            env = selection.environment(task['level'])
            self.assertEqual(env['PUPPYBOT_EVAL_SELECTION_SEED'], '7820000')
            self.assertEqual(env['PUPPYBOT_EVAL_TWO_ROOM'], '1' if task['level'] >= 4 else '0')
            for arm in selection.design()['arms']:
                cmd = selection.command(task, arm)
                self.assertEqual(cmd.count('--explore-teacher'), int(arm == 'teacher'))
                self.assertEqual(cmd[cmd.index('--level') + 1], str(task['level']))
        self.assertEqual(selection.auditor.BASE, selection.SEED)
        self.assertEqual(selection.auditor.selection.BASE, selection.SEED)

    def test_live_inputs_and_named_history(self):
        plan = selection.current()
        self.assertEqual(plan['status'], 'frozen_before_play')
        self.assertGreaterEqual(plan['history']['records'], 60)
        self.assertEqual(plan['design'], selection.design())

    def test_reject_unknown_command(self):
        with self.assertRaises(ValueError): selection.command(selection.design()['tasks'][0], 'other')

    def test_fresh_subprocess_configuration(self):
        value = json.loads(subprocess.check_output(selection.python_call('describe_configuration'), text=True))
        self.assertEqual(value['registration'], str(HERE / 'selection.py'))
        self.assertEqual(value['output'], str(selection.OUTPUT))
        self.assertEqual(value['worker'], selection.python_call('run'))

    def test_retargeted_scene_link_rejected_before_scene_content_read(self):
        with tempfile.TemporaryDirectory(prefix='selection-scene-test-') as temp:
            scenes = Path(temp) / 'scenes'; layout = scenes / '13'; variant = layout / '0'
            variant.mkdir(parents=True)
            (variant / 'case.json').write_text('{}')
            for name in ('environment.bin', 'layout.json'):
                (layout / name).write_text('training')
                (variant / name).symlink_to(layout / name)
            row = {'layout': 13, 'variant': 0, 'scene': str(variant)}
            self.assertEqual(len(selection.scene_links(row, scenes)), 3)
            reserved = scenes / '226'; reserved.mkdir()
            (reserved / 'environment.bin').write_text('reserved')
            (variant / 'environment.bin').unlink()
            (variant / 'environment.bin').symlink_to(reserved / 'environment.bin')
            with mock.patch.object(Path, 'read_text', side_effect=AssertionError('content read')):
                with self.assertRaisesRegex(ValueError, 'escaped'): selection.scene_links(row, scenes)

    def test_arm_failure_is_censored_and_preserved(self):
        with tempfile.TemporaryDirectory(prefix='selection-failure-test-') as temp:
            output = Path(temp) / 'output'
            with mock.patch.object(selection, 'OUTPUT', output), \
                    mock.patch.object(selection.guard, 'require_dedicated_process'), \
                    mock.patch.object(selection.base, 'acquire_lock', return_value=nullcontext()), \
                    mock.patch.object(selection.base, 'require_capacity'), \
                    mock.patch.object(selection, 'verify', return_value={'test': 'frozen'}), \
                    mock.patch.object(selection.base.hidden, 'supervise', return_value={'clientExit': 1}):
                with self.assertRaisesRegex(ValueError, 'supervisor failed'): selection.run()
            partial = json.loads((output / 'partial.json').read_text())
            self.assertEqual(partial['status'], 'censored')
            self.assertEqual(partial['completed'], [])
            self.assertFalse((output / 'report.json').exists())

    def test_launch_retains_receipt_and_rejects_telemetry_changes(self):
        status = {'clientExit': 0, 'signal': None, 'timedOut': False,
                  'remainingWorkersTerminated': False, 'processGroup': 42}
        frozen = {'files': {'fixed': 'hash'}}; report = {'status': 'diagnostic_only'}
        for changed in (False, True):
            with self.subTest(telemetry_changed=changed), tempfile.TemporaryDirectory(prefix='selection-launch-test-') as temp:
                root = Path(temp); output = root / 'output'; monitored = root / 'monitor'
                def supervise(argv, directory, env, limit):
                    directory = Path(directory)
                    (directory / 'supervisor-result.json').write_text(json.dumps(status))
                    if directory.name == 'outer-monitor':
                        (monitored / 'frozen-manifest.json').write_text(json.dumps(frozen))
                        (monitored / 'monitor-result.json').write_text(json.dumps({'status': 'passed'}))
                        (monitored / 'evidence.json').write_text(json.dumps({'status': 'diagnostic_only', 'report': report}))
                        (monitored / 'telemetry.jsonl').write_text('telemetry\n')
                        (monitored / 'disk.jsonl').write_text('disk\n')
                    else:
                        (directory / 'client.log').write_text(json.dumps({'status': 'final_inventory_verified'}))
                        if changed: (monitored / 'telemetry.jsonl').write_text('changed\n')
                    return status
                with ExitStack() as patches:
                    patches.enter_context(mock.patch.object(selection, 'OUTPUT', output))
                    patches.enter_context(mock.patch.object(selection, 'MONITOR', monitored))
                    patches.enter_context(mock.patch.object(selection, 'MANIFEST', root / 'manifest'))
                    patches.enter_context(mock.patch.object(selection, 'verify', return_value=frozen))
                    patches.enter_context(mock.patch.object(selection, 'verify_saved', return_value=report))
                    patches.enter_context(mock.patch.object(selection.guard, 'require_dedicated_process'))
                    patches.enter_context(mock.patch.object(selection.monitor, 'require_disk'))
                    patches.enter_context(mock.patch.object(selection.monitor, 'verify_logs'))
                    for name in ('OUTPUT', 'MONITOR', 'MANIFEST', 'REGISTER', 'verify_saved', 'worker_command'):
                        patches.enter_context(mock.patch.object(selection.monitor, name, getattr(selection.monitor, name)))
                    patches.enter_context(mock.patch.object(selection.base.hidden, 'supervise', side_effect=supervise))
                    if changed:
                        with self.assertRaisesRegex(ValueError, 'changed during final audit'): selection.launch()
                        self.assertFalse((monitored / 'completion.json').exists())
                    else:
                        self.assertEqual(selection.launch(), report)
                        completion = json.loads((monitored / 'completion.json').read_text())
                        for key in ('telemetrySHA256', 'diskSHA256', 'monitorResultSHA256',
                                    'outerSupervisorStatusSHA256', 'frozenManifestSHA256',
                                    'finalInventoryInvocationSHA256', 'finalInventoryStatusSHA256',
                                    'finalInventoryResultSHA256'):
                            self.assertEqual(len(completion[key]), 64)

    def test_existing_teacher_auditor_on_saved_three_arm_l5(self):
        old = selection.P / 'search-dagger-l35-4workers/selection-L5'
        heading = selection.P / 'search-dagger-heading/selection-epoch8/L5'
        teacher = selection.P / 'search-dagger-heading/teacher-selection-v1/L5'
        with tempfile.TemporaryDirectory(prefix='selection-auditor-test-') as temp:
            root = Path(temp)
            for name, source in (('control', old / 'student-s1'), ('treatment', heading / 'treatment'),
                                 ('teacher', teacher / 'teacher')):
                (root / name).symlink_to(source)
            for name, source in (('control', old / 'score-student-s1.json'), ('treatment', heading / 'score-treatment.json'),
                                 ('teacher', teacher / 'score-teacher.json')):
                value = json.loads(source.read_text()); value['player'] = name
                (root / ('score-' + name + '.json')).write_text(json.dumps(value))
            with mock.patch.object(selection.auditor, 'BASE', 7800000), \
                    mock.patch.object(selection.auditor.selection, 'BASE', 7800000):
                report = selection.auditor.audit_task('L5', root, root, selection.MODELS)
            self.assertEqual(report['status'], 'complete_diagnostic')
            self.assertEqual({k: v['deliveries'] for k, v in report['results'].items()},
                             {'teacher': 24, 'control': 29, 'treatment': 14})

    def test_full_saved_l5_reaudit_and_loop_metrics(self):
        old = selection.P / 'search-dagger-l35-4workers/selection-L5'
        heading = selection.P / 'search-dagger-heading/selection-epoch8/L5'
        teacher = selection.P / 'search-dagger-heading/teacher-selection-v1/L5'
        status = {'clientExit': 0, 'signal': None, 'timedOut': False,
                  'remainingWorkersTerminated': False, 'processGroup': 42}
        with tempfile.TemporaryDirectory(prefix='selection-full-audit-test-') as temp:
            output = Path(temp); root = output / 'L5'; root.mkdir()
            frozen = {'scope': 'CPU fixture'}; (output / 'inputs.json').write_text(json.dumps(frozen))
            for name, source in (('control', old / 'student-s1'), ('treatment', heading / 'treatment'),
                                 ('teacher', teacher / 'teacher')):
                (root / name).symlink_to(source)
            for name, source in (('control', old / 'score-student-s1.json'), ('treatment', heading / 'score-treatment.json'),
                                 ('teacher', teacher / 'score-teacher.json')):
                value = json.loads(source.read_text()); value['player'] = name
                (root / ('score-' + name + '.json')).write_text(json.dumps(value))
            with mock.patch.object(selection, 'OUTPUT', output), mock.patch.object(selection, 'SEED', 7800000), \
                    mock.patch.object(selection.auditor, 'BASE', 7800000), \
                    mock.patch.object(selection.auditor.selection, 'BASE', 7800000):
                original_design = selection.design(); task = original_design['tasks'][-1]
                fixture_design = dict(original_design, tasks=[task])
                with mock.patch.object(selection, 'design', return_value=fixture_design):
                    for arm in fixture_design['arms']:
                        receipt = output / 'supervisors/L5' / arm; receipt.mkdir(parents=True)
                        invocation = {'argv': selection.command(task, arm), 'environment': selection.environment(5),
                                      'wallSeconds': 3600}
                        (receipt / 'invocation.json').write_text(json.dumps(invocation))
                        (receipt / 'supervisor-result.json').write_text(json.dumps(status))
                    result = selection.reaudit(frozen)
            self.assertEqual(result['status'], 'diagnostic_only')
            metrics = result['tasks']['L5']['results']
            self.assertEqual({k: v['deliveries'] for k, v in metrics.items()},
                             {'teacher': 24, 'control': 29, 'treatment': 14})
            self.assertEqual(len(metrics['control']['longerSearchLoops']['games']), 32)
            self.assertEqual(len(metrics['treatment']['longerSearchLoops']['games']), 32)
            self.assertEqual(result['pool']['status'], 'censored')


if __name__ == '__main__': unittest.main()
