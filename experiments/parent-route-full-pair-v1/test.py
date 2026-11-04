#!/usr/bin/env python3
"""CPU-only fail-closed fixtures for full-pair preparation."""
import importlib.util
import json
import os
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


plan = load('test_full_plan', HERE / 'plan.py')
audit = load('test_full_audit', HERE / 'audit.py')
monitor = load('test_full_monitor', HERE / 'monitor.py')


def put(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + '\n')


class GateTests(unittest.TestCase):
    def test_no_registration_without_completed_smoke(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.object(plan, 'SMOKE_OUTPUT', root / 'missing'), \
                    mock.patch.object(plan, 'PLAN', root / 'plan.json'), mock.patch.object(plan, 'OUTPUT', root / 'out'):
                with self.assertRaisesRegex(ValueError, 'missing or linked'):
                    plan.freeze()
                self.assertFalse((root / 'plan.json').exists())
                self.assertFalse((root / 'out').exists())


class SmokeGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='full-pair-smoke-gate-'); self.root = Path(self.temp.name)
        self.prior_plan = self.root / 'smoke-plan.json'; put(self.prior_plan, {'fixed': True})
        self.env = {'PATH': '/usr/bin:/bin'}; self.report = {'status': 'one_step_diagnostic_only', 'value': 7}
        self.files = {'control/weights.bin': {'sha256': 'a', 'size': 10}}
        final = {'status': 'one_step_diagnostic_only', 'planSHA256': plan.sha(self.prior_plan),
                 'report': self.report, 'inventory': self.files}
        put(self.root / 'final-result.json', final)
        put(self.root / 'launcher.json', {'argv': ['python', '999'], 'environment': self.env,
                                         'planSHA256': plan.sha(self.prior_plan)})
        put(self.root / 'guardian-launch.json', {'parentPID': 999, 'guardianPID': 1234})
        put(self.root / 'guardian-result.json', {'status': 'passed'})
        (self.root / 'guardian-telemetry.jsonl').write_text('{}\n')
        put(self.root / 'baseline-passed.json', {'status': 'passed'})
        for name in ('baseline-control.jsonl', 'baseline-treatment.jsonl', 'reservation-control.json', 'reservation-treatment.json'):
            (self.root / name).write_text('{}\n')
        status = {'clientExit': 0, 'timedOut': False, 'remainingWorkersTerminated': False,
                  'signal': None, 'processGroup': 1}
        for arm in ('control', 'treatment', 'final'):
            d = self.root / f'supervisor-{arm}'; d.mkdir()
            put(d / 'invocation.json', {'argv': ['fake-final'] if arm == 'final' else ['fake-arm'],
                                        'environment': self.env, 'wallSeconds': 2400 if arm == 'final' else 1})
            put(d / 'supervisor-result.json', status); (d / 'client.log').write_text('')
        self.fake_plan = SimpleNamespace(PLAN=self.prior_plan, environment=lambda: self.env,
                                         verify=lambda: {'fixed': True}, paired=SimpleNamespace(os=os))
        def verify_guardian(pid):
            if pid != 1234 or os.getpid() != 999: raise ValueError('wrong guardian')
        def evidence():
            names = ['baseline-control.jsonl', 'baseline-treatment.jsonl', 'reservation-control.json',
                     'reservation-treatment.json', 'final-result.json']
            for arm in ('control', 'treatment'):
                names += [f'supervisor-{arm}/{name}' for name in ('invocation.json', 'supervisor-result.json', 'client.log')]
            return {name: plan.sha(self.root / name) for name in names}
        self.smoke = SimpleNamespace(plan=self.fake_plan, verify_guardian=verify_guardian,
            evidence_hashes=evidence, inventory=lambda: self.files, verify_arms=lambda: self.report,
            command=lambda function: ['fake-final'], clean=lambda value: value == status)
        hashes = evidence()
        for name in ('invocation.json', 'supervisor-result.json', 'client.log'):
            hashes[f'supervisor-final/{name}'] = plan.sha(self.root / 'supervisor-final' / name)
        put(self.root / 'coordinator-result.json', {'status': 'one_step_diagnostic_only',
            'planSHA256': plan.sha(self.prior_plan), 'evidenceSHA256': hashes})
        put(self.root / 'completion.json', {'status': 'one_step_diagnostic_only',
            'planSHA256': plan.sha(self.prior_plan), 'coordinatorSHA256': plan.sha(self.root / 'coordinator-result.json'),
            'guardianResultSHA256': plan.sha(self.root / 'guardian-result.json'),
            'guardianTelemetrySHA256': plan.sha(self.root / 'guardian-telemetry.jsonl')})

    def tearDown(self): self.temp.cleanup()

    def test_valid_completed_smoke_is_bound_and_failed_or_tampered_is_rejected(self):
        with mock.patch.object(plan, 'SMOKE_OUTPUT', self.root), mock.patch.object(plan, 'smoke', self.smoke):
            result = plan.smoke_evidence()
            self.assertEqual(result['completionSHA256'], plan.sha(self.root / 'completion.json'))
            self.assertEqual(result['guardianLaunchSHA256'], plan.sha(self.root / 'guardian-launch.json'))
            (self.root / 'supervisor-control/client.log').write_text('tampered')
            with self.assertRaisesRegex(ValueError, 'evidence or final audit'): plan.smoke_evidence()
            (self.root / 'supervisor-control/client.log').write_text('')
            completion = json.loads((self.root / 'completion.json').read_text()); completion['status'] = 'failed'
            put(self.root / 'completion.json', completion)
            with self.assertRaisesRegex(ValueError, 'incomplete or failed'): plan.smoke_evidence()

    def test_failed_final_supervisor_and_mismatched_historical_parent_are_rejected(self):
        with mock.patch.object(plan, 'SMOKE_OUTPUT', self.root), mock.patch.object(plan, 'smoke', self.smoke):
            status_path = self.root / 'supervisor-final/supervisor-result.json'; saved = status_path.read_bytes()
            status = json.loads(saved); status['clientExit'] = 1; put(status_path, status)
            with self.assertRaisesRegex(ValueError, 'final supervisor'): plan.smoke_evidence()
            status_path.write_bytes(saved)
            launch_path = self.root / 'launcher.json'; value = json.loads(launch_path.read_text()); value['argv'][-1] = '998'; put(launch_path, value)
            with self.assertRaisesRegex(ValueError, 'identity'): plan.smoke_evidence()
    def test_commands_use_fixed_full_epoch_and_original_parent(self):
        left, right = plan.command('control'), plan.command('treatment')
        self.assertEqual(left[left.index('--seed') + 1], '7120000')
        self.assertEqual(left[left.index('--epochs') + 1], '1')
        self.assertEqual(left[left.index('--batch') + 1], '2')
        self.assertEqual(left[left.index('--learning-rate-micros') + 1], '100')
        self.assertNotIn('--max-optimizer-steps', left)
        self.assertIn('--mirror-augment', left); self.assertIn('--carry-cue', left)
        for flag in ('--policy', '--memory-map', '--data', '--output'):
            self.assertEqual(left.index(flag), right.index(flag))
        self.assertEqual(left[left.index('--policy') + 1], right[right.index('--policy') + 1])
        self.assertNotEqual(left[left.index('--data') + 1], right[right.index('--data') + 1])
        with self.assertRaises(ValueError): plan.command('invalid')

    def test_full_disk_reservation_and_guarded_baseline(self):
        needed = 34 * monitor.GIB + 6564583232 + monitor.HEADROOM
        self.assertEqual(monitor.reserve(needed, 6564583232)['requiredBytes'], needed)
        with self.assertRaises(ValueError): monitor.reserve(needed - 1, 6564583232)
        rows = [{'monotonicSeconds': float(i), 'phase': 'baseline', 'busyPercent': 0,
                 'totalBytes': 10 * monitor.GIB, 'usedBytes': monitor.GIB, 'freeBytes': 9 * monitor.GIB}
                for i in range(31)]
        monitor.check_baseline(rows)
        with self.assertRaises(ValueError): monitor.check_baseline(rows[:5] + rows[8:])
        with self.assertRaises(ValueError): monitor.check_baseline([dict(r, busyPercent=80) for r in rows])

    def test_synthetic_registration_requires_stable_completed_smoke(self):
        with tempfile.TemporaryDirectory(prefix='full-pair-plan-') as tmp:
            root = Path(tmp)
            first = {'completionSHA256': 'a', 'planSHA256': 'b', 'launcherSHA256': 'c',
                     'guardianLaunchSHA256': 'd', 'baselineMarkerSHA256': 'e', 'finalResultSHA256': 'f'}
            refs = {str(plan.SMOKE_OUTPUT / name): digest for name, digest in (
                    ('completion.json', 'a'), ('launcher.json', 'c'), ('guardian-launch.json', 'd'),
                    ('baseline-passed.json', 'e'))}
            light = {'lineageReceiptSHA256': refs, 'smokePlanSHA256': 'b',
                     'smokeEvidenceSHA256': {'final-result.json': 'f'}, 'other': 'pinned', 'privateBinaries': {}}
            with mock.patch.object(plan, 'PLAN', root / 'plan.json'), mock.patch.object(plan, 'OUTPUT', root / 'output'), \
                    mock.patch.object(plan, 'smoke_evidence', return_value=first) as deep, \
                    mock.patch.object(plan.builder, 'verify', return_value={'binaries': {}}), \
                    mock.patch.object(plan, 'verify_smoke_data_copies') as copies, \
                    mock.patch.object(plan, 'light_inputs', return_value=light) as shallow:
                value = plan.freeze(); self.assertEqual(value['status'], 'registered_before_training')
                self.assertEqual(deep.call_count, 1)
                copies.assert_called_once_with(value)
                self.assertEqual(plan.verify(), value)
                self.assertEqual(value['training']['optimizerSteps'], 468)
                self.assertEqual(value['thresholds']['pairOverallSeconds'], 7500)
                with self.assertRaises(FileExistsError): plan.freeze()
                shallow.return_value = dict(light, other='changed')
                with self.assertRaisesRegex(ValueError, 'plan or inputs changed'): plan.verify()
                deep.return_value = dict(first, completionSHA256='changed')
                with self.assertRaisesRegex(ValueError, 'deep smoke evidence changed'): plan.deep_check(value)

    def test_changed_smoke_during_registration_never_registers(self):
        with tempfile.TemporaryDirectory(prefix='full-pair-changing-') as tmp:
            root = Path(tmp)
            first = {'completionSHA256': 'a', 'planSHA256': 'b', 'launcherSHA256': 'c',
                     'guardianLaunchSHA256': 'd', 'baselineMarkerSHA256': 'e', 'finalResultSHA256': 'f'}
            refs = {str(plan.SMOKE_OUTPUT / name): digest for name, digest in (
                    ('completion.json', 'a'), ('launcher.json', 'c'), ('guardian-launch.json', 'd'),
                    ('baseline-passed.json', 'e'))}
            light = {'lineageReceiptSHA256': refs, 'smokePlanSHA256': 'b',
                     'smokeEvidenceSHA256': {'final-result.json': 'f'}, 'privateBinaries': {}}
            with mock.patch.object(plan, 'PLAN', root / 'plan.json'), mock.patch.object(plan, 'OUTPUT', root / 'output'), \
                    mock.patch.object(plan, 'smoke_evidence', return_value=first), \
                    mock.patch.object(plan.builder, 'verify', return_value={'binaries': {}}), \
                    mock.patch.object(plan, 'light_inputs', side_effect=[light, dict(light, changed=True)]):
                with self.assertRaisesRegex(ValueError, 'changed during registration'): plan.freeze()
                self.assertFalse((root / 'plan.json').exists())


class BoundaryTests(unittest.TestCase):
    def test_smoke_small_inventory_hashes_small_files_and_defers_data(self):
        with tempfile.TemporaryDirectory(prefix='full-pair-boundary-') as tmp:
            root = Path(tmp); inventory = {}
            for arm in ('control', 'treatment'):
                (root / arm).mkdir()
                for name, content in (('data.bin', b'data'), ('weights.bin', b'weights')):
                    path = root / arm / name; path.write_bytes(content)
                    inventory[f'{arm}/{name}'] = {'size': len(content), 'sha256': plan.sha(path)}
            with mock.patch.object(plan, 'SMOKE_OUTPUT', root), mock.patch.object(plan, 'stable_sha', wraps=plan.stable_sha) as stable:
                result = plan.smoke_small_inventory(inventory)
                self.assertEqual(result['files'], 4)
                self.assertEqual(len(stable.call_args_list), 2)
                self.assertTrue(all(call.args[0].name == 'weights.bin' for call in stable.call_args_list))
                (root / 'control/weights.bin').write_bytes(b'weightx')
                with self.assertRaisesRegex(ValueError, 'non-data output changed'): plan.smoke_small_inventory(inventory)

    def test_sealed_smoke_copies_reject_same_size_post_deep_mutation(self):
        with tempfile.TemporaryDirectory(prefix='full-pair-smoke-copy-') as tmp:
            root = Path(tmp); inventory = {}
            for arm in ('control', 'treatment'):
                (root / arm).mkdir(); path = root / arm / 'data.bin'; path.write_bytes(b'data')
                inventory[f'{arm}/data.bin'] = {'size': 4, 'sha256': plan.sha(path)}
            final = root / 'final-result.json'; put(final, {'inventory': inventory})
            frozen = {'smoke': {'finalResultSHA256': plan.sha(final)}}
            with mock.patch.object(plan, 'SMOKE_OUTPUT', root):
                plan.verify_smoke_data_copies(frozen)
                (root / 'treatment/data.bin').write_bytes(b'evil')
                with self.assertRaisesRegex(ValueError, 'data copy changed'): plan.verify_smoke_data_copies(frozen)
                (root / 'treatment/data.bin').write_bytes(b'data')
                put(final, {'inventory': inventory, 'changed': True})
                with self.assertRaisesRegex(ValueError, 'final result changed'): plan.verify_smoke_data_copies(frozen)

    def test_final_check_rejects_clone_mutated_after_deep_check(self):
        with tempfile.TemporaryDirectory(prefix='full-pair-final-race-') as tmp:
            root = Path(tmp); smoke_root = root / 'smoke'; smoke_root.mkdir(); inventory = {}
            for arm in ('control', 'treatment'):
                (smoke_root / arm).mkdir(); path = smoke_root / arm / 'data.bin'; path.write_bytes(b'data')
                inventory[f'{arm}/data.bin'] = {'size': 4, 'sha256': plan.sha(path)}
            final = smoke_root / 'final-result.json'; put(final, {'inventory': inventory})
            frozen = {'smoke': {'finalResultSHA256': plan.sha(final)}}
            registered = root / 'plan.json'; put(registered, frozen)
            output = root / 'output'; output.mkdir()
            def mutate_after_deep():
                (smoke_root / 'control/data.bin').write_bytes(b'evil')
                return {}
            with mock.patch.object(monitor.plan, 'SMOKE_OUTPUT', smoke_root), \
                    mock.patch.object(monitor.plan, 'PLAN', registered), mock.patch.object(monitor.plan, 'OUTPUT', output), \
                    mock.patch.object(monitor.plan, 'verify', return_value=frozen), \
                    mock.patch.object(monitor.plan, 'deep_check'), mock.patch.object(monitor, 'verify_arms', return_value={}), \
                    mock.patch.object(monitor, 'inventory', side_effect=mutate_after_deep):
                with self.assertRaisesRegex(ValueError, 'data copy changed'): monitor.final_check()
                self.assertFalse((output / 'final-result.json').exists())

    def test_runtime_chain_rejects_changed_links(self):
        with tempfile.TemporaryDirectory(prefix='full-pair-runtime-') as tmp:
            root = Path(tmp); (root / 'runtime-a').write_bytes(b'a'); (root / 'runtime-b').write_bytes(b'b')
            (root / 'runtime').symlink_to('runtime-a')
            first = plan.runtime_chain(root / 'runtime')
            (root / 'runtime').unlink(); (root / 'runtime').symlink_to('runtime-b')
            self.assertNotEqual(first, plan.runtime_chain(root / 'runtime'))
            (root / 'runtime').unlink(); (root / 'runtime').symlink_to('runtime')
            with self.assertRaisesRegex(ValueError, 'cycle'): plan.runtime_chain(root / 'runtime')


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='full-pair-package-')
        self.root = Path(self.temp.name)
        self.plan = SimpleNamespace(OUTPUT=self.root, sha=plan.sha)
        source = self.root / 'control'; source.mkdir(); (source / 'kernels').mkdir()
        for name in ('epoch-1.bin', 'weights.bin', 'policy', 'model.pup', 'factory.flex'):
            (source / name).write_bytes(('source-' + name).encode())
        (source / 'kernels/one.hip').write_bytes(b'kernel')
        self.receipt = {'weightsSHA256': plan.sha(source / 'weights.bin'),
                        'kernels': {'one.hip': plan.sha(source / 'kernels/one.hip')}}
        put(source / 'receipt.json', self.receipt)

    def tearDown(self):
        root = self.root / 'fixed-control'
        if root.exists():
            root.chmod(0o755); (root / 'kernels').chmod(0o755)
        self.temp.cleanup()

    def test_fixed_epoch_package_uses_epoch_not_selected_weights(self):
        report = audit.create_package(self.plan, 'control')
        self.assertEqual(report['weightsSHA256'], plan.sha(self.root / 'control/epoch-1.bin'))
        self.assertNotEqual(report['weightsSHA256'], self.receipt['weightsSHA256'])
        self.assertEqual(audit.verify_package(self.plan, 'control'), report)
        with self.assertRaises(FileExistsError): audit.create_package(self.plan, 'control')

    def test_tampered_package_and_writable_package_are_rejected(self):
        audit.create_package(self.plan, 'control')
        root = self.root / 'fixed-control'; weights = root / 'weights.bin'
        weights.chmod(0o644); weights.write_bytes(b'wrong'); weights.chmod(0o444)
        with self.assertRaises(ValueError): audit.verify_package(self.plan, 'control')
        weights.chmod(0o644); weights.write_bytes((self.root / 'control/epoch-1.bin').read_bytes()); weights.chmod(0o444)
        root.chmod(0o755)
        with self.assertRaisesRegex(ValueError, 'read-only'): audit.verify_package(self.plan, 'control')


class JournalTests(unittest.TestCase):
    def test_pair_order_and_all_masks_checked(self):
        with tempfile.TemporaryDirectory(prefix='full-pair-journal-') as tmp:
            root = Path(tmp); fixture = SimpleNamespace(OUTPUT=root, journal=plan.journal, smoke=plan.smoke)
            order = plan.smoke.audit.order_for_seed(7120000); order_data = struct.pack('<1031Q', *order)
            def make_journal(order):
                rng = (7120000 ^ 0x5a5a5a5a) & 2147483647
                result = bytearray(struct.pack('<8s4q', b'PBMIRR01', 1, 7120000, 935, 2))
                for index in range(468):
                    start = index * 2; count = min(2, 935 - start); mask = 0
                    for bit in range(count):
                        rng = (rng * 1103515245 + 12345) & 2147483647; mask |= ((rng >> 15) & 1) << bit
                    result.extend(struct.pack('<6q', index, start, count, mask, order[start],
                                              order[start + 1] if count == 2 else -1))
                result.extend(struct.pack('<8sQ', b'PBDONE01', 468)); return result
            journal = make_journal(order)
            for arm in ('control', 'treatment'):
                d = root / arm; d.mkdir(); (d / 'batch-schedule.bin').write_bytes(journal)
                (d / 'first-order.bin').write_bytes(order_data); (d / 'final-order.bin').write_bytes(order_data)
            self.assertEqual(audit.schedules(fixture)['batches'], 468)
            broken = root / 'treatment/batch-schedule.bin'; data = bytearray(broken.read_bytes()); data[64] ^= 1; broken.write_bytes(data)
            with self.assertRaises(ValueError): audit.schedules(fixture)
            wrong = list(order); wrong[0], wrong[1] = wrong[1], wrong[0]
            for arm in ('control', 'treatment'):
                d = root / arm; (d / 'batch-schedule.bin').write_bytes(make_journal(wrong))
                (d / 'first-order.bin').write_bytes(struct.pack('<1031Q', *wrong))
                (d / 'final-order.bin').write_bytes(struct.pack('<1031Q', *wrong))
            with self.assertRaisesRegex(ValueError, 'shuffle seed'): audit.schedules(fixture)


class CoordinatorTests(unittest.TestCase):
    def test_second_arm_failure_preserves_first_and_skips_packages(self):
        with tempfile.TemporaryDirectory(prefix='full-pair-coordinator-') as tmp:
            root = Path(tmp); output = root / 'out'; output.mkdir(); data = root / 'data'
            for arm in ('control', 'treatment'):
                (data / arm).mkdir(parents=True); (data / arm / 'data.bin').write_bytes(b'data')
            planfile = root / 'plan.json'; planfile.write_text('{}')
            success = {'clientExit': 0, 'signal': None, 'timedOut': False,
                       'remainingWorkersTerminated': False, 'processGroup': 7}
            failure = dict(success, clientExit=1)
            calls = []
            def supervise(argv, directory, env, seconds):
                calls.append(argv); status = success if len(calls) == 1 else failure
                put(directory / 'supervisor-result.json', status)
                if len(calls) == 1:
                    (output / 'control').mkdir(); (output / 'control/evidence').write_text('retained')
                return status
            with mock.patch.object(monitor.plan, 'OUTPUT', output), mock.patch.object(monitor.plan, 'PLAN', planfile), \
                    mock.patch.object(monitor.plan, 'ROOT', root), mock.patch.object(monitor.plan, 'verify', return_value={'fixed': True}), \
                    mock.patch.object(monitor.plan, 'command', side_effect=lambda arm: [arm]), \
                    mock.patch.object(monitor.plan.smoke.plan, 'DATA', data), mock.patch.object(monitor, 'baseline'), \
                    mock.patch.object(monitor.audit, 'model', return_value={'consistent': True}), \
                    mock.patch.object(monitor.audit, 'schedules') as schedules, \
                    mock.patch.object(monitor.audit, 'create_package') as package, \
                    mock.patch.object(monitor.hidden, 'supervise', side_effect=supervise), \
                    mock.patch.object(monitor.shutil, 'disk_usage', return_value=SimpleNamespace(free=42 * monitor.GIB)):
                with self.assertRaisesRegex(RuntimeError, 'training arm failed'): monitor.coordinator()
                self.assertEqual(calls, [['control'], ['treatment']])
                self.assertEqual((output / 'control/evidence').read_text(), 'retained')
                schedules.assert_not_called(); package.assert_not_called()
                self.assertFalse((output / 'coordinator-result.json').exists())

    def test_inventory_rejects_linked_roots_and_hardlinks(self):
        with tempfile.TemporaryDirectory(prefix='full-pair-inventory-') as tmp:
            root = Path(tmp)
            for name in ('control', 'treatment', 'fixed-control', 'fixed-treatment'):
                (root / name).mkdir(); (root / name / 'item').write_bytes(name.encode())
            with mock.patch.object(monitor.plan, 'OUTPUT', root):
                self.assertEqual(len(monitor.inventory()), 4)
                source = root / 'control/item'; alias = root / 'control/alias'; os.link(source, alias)
                with self.assertRaisesRegex(ValueError, 'unsafe model file'): monitor.inventory()
                alias.unlink()
                (root / 'fixed-treatment/item').unlink(); (root / 'fixed-treatment').rmdir()
                (root / 'fixed-treatment').symlink_to(root / 'control', target_is_directory=True)
                with self.assertRaisesRegex(ValueError, 'missing or linked'): monitor.inventory()


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='full-pair-model-'); self.root = Path(self.temp.name)
        self.model = self.root / 'control'; self.model.mkdir(); (self.model / 'kernels').mkdir()
        values = {'data.bin': b'data', 'seed.bin': b'parent', 'initial.bin': b'parent',
                  'weights.bin': b'weights', 'policy': b'policy', 'model.pup': b'graph', 'backend.txt': b'hip'}
        for name, value in values.items(): (self.model / name).write_bytes(value)
        (self.model / 'kernels/one.hip').write_bytes(b'kernel')
        self.parent_sha = plan.sha(self.model / 'seed.bin'); data_sha = plan.sha(self.model / 'data.bin')
        kernel = {'one.hip': plan.sha(self.model / 'kernels/one.hip')}
        self.parent = {'binarySHA256': plan.sha(self.model / 'policy'), 'graphSHA256': plan.sha(self.model / 'model.pup'), 'kernels': kernel}
        smoke_audit = SimpleNamespace(DATA={'control': data_sha}, MAP='map-sha', PARENT=self.parent_sha,
                                      checkpoint=self.fake_checkpoint)
        self.plan = SimpleNamespace(OUTPUT=self.root, sha=plan.sha,
                                    smoke=SimpleNamespace(audit=smoke_audit,
                                        plan=SimpleNamespace(design=SimpleNamespace(parent_receipt=lambda: self.parent))))
        self.receipt = {'dataSHA256': data_sha, 'memoryMapTargetsSHA256': 'map-sha',
                        'initialWeightsSHA256': self.parent_sha, 'seed': 7120000, 'epochs': 1, 'batch': 2,
                        'learningRateMicros': 100, 'checkpointEveryEpochs': 1, 'sequenceMirrorAugmentation': True,
                        'carryCue': True, 'speedTransitionLossWeight': 1, 'stopLossWeight': 5,
                        'actionCodec': 'joint-seven-v1', 'memoryWidth': 128, 'phaseSupervisionFromValidFrames': False,
                        'taskFeedback': False, 'trainingRuntime': 'Flexscript/Pup HIP (RDNA)',
                        'fromScratch': False, 'imageSide': 84, 'focusCopiesPerEpoch': 0, 'focusHistory': None,
                        'phaseGatedNavigation': False, 'cameraEventAuxiliary': False, 'memoryPoseAuxiliary': False,
                        'targetHeatmapAuxiliary': False, 'targetPositionAuxiliary': False,
                        'heatmapAbsenceSupervision': False, 'heatmapActorFeatures': False,
                        'heatmapActorGradientDetached': False, 'controlLoss': 'weighted joint action cross entropy',
                        'weightsSHA256': plan.sha(self.model / 'weights.bin'), **self.parent}
        put(self.model / 'receipt.json', self.receipt)
        self.curves = [{'epoch': 0, 'optimizerSteps': 0, 'trainingLoss': 1.0, 'validationLoss': 1.0,
                        'mapValidationLoss': 1.0, 'gradientNorm': 0.0},
                       {'epoch': 1, 'optimizerSteps': 468, 'trainingLoss': 0.9, 'validationLoss': 0.9,
                        'mapValidationLoss': 0.9, 'mapTrainingLoss': 0.9, 'gradientNorm': 1.0}]
        self.write_curves()

    def tearDown(self): self.temp.cleanup()

    def write_curves(self):
        (self.model / 'curves.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in self.curves))

    @staticmethod
    def fake_checkpoint(path):
        name = Path(path).name; digest = {'initial.bin': 'initial', 'first-gradients.bin': 'gradient',
                                          'first-after.bin': 'first', 'last.bin': 'last', 'epoch-1.bin': 'last'}[name]
        return {'tableSHA256': 'same', 'sha256': digest, 'nonzero': 1, 'actorBias': [1] * 7}

    def test_exact_optimizer_steps_and_finite_losses(self):
        with mock.patch.object(audit, 'clone_evidence', return_value={'consistent': True}):
            self.assertEqual(audit.model(self.plan, 'control')['epoch1SHA256'], 'last')
            self.curves[1]['optimizerSteps'] = 467; self.write_curves()
            with self.assertRaisesRegex(ValueError, '468'): audit.model(self.plan, 'control')
            self.curves[1]['optimizerSteps'] = 468; self.curves[1]['trainingLoss'] = float('nan'); self.write_curves()
            with self.assertRaisesRegex(ValueError, 'nonfinite'): audit.model(self.plan, 'control')

    def test_optimizer_cap_and_wrong_parent_rejected(self):
        with mock.patch.object(audit, 'clone_evidence', return_value={'consistent': True}):
            self.receipt['maxOptimizerSteps'] = 1; put(self.model / 'receipt.json', self.receipt)
            with self.assertRaisesRegex(ValueError, 'cap'): audit.model(self.plan, 'control')
            self.receipt.pop('maxOptimizerSteps'); self.receipt['initialWeightsSHA256'] = 'wrong'; put(self.model / 'receipt.json', self.receipt)
            with self.assertRaisesRegex(ValueError, 'initialWeights'): audit.model(self.plan, 'control')


if __name__ == '__main__':
    unittest.main()
