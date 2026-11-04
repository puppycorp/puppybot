#!/usr/bin/env python3
"""CPU-only verification of the fixed schedule, monitor wiring and packaging."""
import importlib.util
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec); spec.loader.exec_module(obj)
    return obj


train = load('outbound_five_train_test', HERE / 'train.py')
monitor = load('outbound_five_monitor_test', HERE / 'monitor.py')


class DesignTest(unittest.TestCase):
    def test_real_fixed_design_and_selection(self):
        fixed = train.design.design()
        self.assertEqual(fixed['training']['epochs'], 1)
        self.assertEqual(fixed['training']['seed'], 7120000)
        self.assertEqual(fixed['training']['learningRateMicros'], 100)
        self.assertEqual(fixed['maskedEpisodeRange'], [928, 933])
        self.assertEqual(len(fixed['evaluation']['selectionRows']), 160)
        self.assertEqual(fixed['evaluation']['loopMetric'],
                         'pose20-final-inclusive-v2 reconstructed independently for every complete game')
        self.assertEqual(fixed['checkpointRule'], 'fixed epoch-1; never validation-selected weights')
        self.assertEqual(fixed['evaluation']['controls'], ['student-s1', 'fixed epoch-1 candidate', 'exploring teacher'])
        self.assertEqual(fixed['evaluation']['goalThresholds']['completedGameMinimumPerLevel'], 29)
        self.assertEqual(fixed['evaluation']['goalThresholds']['firstPickupL3Minimum'], 29)
        self.assertEqual(fixed['evaluation']['goalThresholds']['doorwayDeliveryMinimumShare'], .8)
        self.assertEqual(fixed['evaluation']['goalThresholds']['backForthActionShareStrictlyLessThan'], .02)

    def test_worker_reimport_and_pinned_module_graph(self):
        self.assertEqual(monitor.old.worker_command(), monitor.worker_command())
        self.assertIs(monitor.old.inventory, monitor.inventory)
        self.assertIs(monitor.old.verify_pilot, monitor.verify_training)
        self.assertEqual(monitor.old.pilot.OUTPUT, train.MODEL)
        files = train.loaded_sources((monitor, train.aggregate, train.prior, train.builder, train.design))
        for path in (HERE / 'monitor.py', HERE / 'train.py', HERE / 'build.py',
                     ROOT / 'experiments/l5-teacher-rollin-pilot-v1/monitor.py',
                     ROOT / 'experiments/outbound-five-aggregate-v1/build.py'):
            self.assertIn(path, files)

    def test_fresh_monitor_import_graph_is_pinned(self):
        code = '''import importlib.machinery,importlib.util
from pathlib import Path
root=Path.cwd();seen=set();original=importlib.machinery.SourceFileLoader.exec_module
def record(self,module):
 p=Path(self.path).resolve()
 if p.is_relative_to(root) and p.suffix==".py":seen.add(p)
 return original(self,module)
importlib.machinery.SourceFileLoader.exec_module=record
p=root/"experiments/outbound-five-trainer-v1/monitor.py"
s=importlib.util.spec_from_file_location("fresh_monitor",p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
found=set(m.train.loaded_sources((m,m.train,m.train.aggregate,m.train.prior,m.train.builder,m.train.design)))
assert seen and not seen-found, sorted(map(str,seen-found))
'''
        subprocess.run([sys.executable, '-I', '-c', code], cwd=ROOT, capture_output=True,
                       text=True, timeout=20, check=True)

    def test_inventory_rejects_links_and_tracks_all_three_roots(self):
        with tempfile.TemporaryDirectory(prefix='outbound-inventory-') as name:
            root = Path(name); model = root / 'model'; package = root / 'package'; worker = root / 'worker'
            for path in (model, package, worker):
                path.mkdir(); (path / 'marker').write_text(path.name)
            with mock.patch.object(monitor.train, 'MODEL', model), mock.patch.object(monitor.train, 'PACKAGE', package), \
                    mock.patch.object(monitor, 'WORKER', worker):
                result = monitor.inventory(model)
                self.assertEqual(set(result), {'model/marker', 'package/marker', 'supervisor/marker'})
                (worker / 'link').symlink_to(worker / 'marker')
                with self.assertRaises(ValueError): monitor.inventory(model)

    def test_dataset_supervisor_receipt_and_hash_are_required(self):
        report = json.loads((train.design.AGGREGATE / 'report.json').read_text())
        original = train.aggregate_supervisor.MONITOR
        with tempfile.TemporaryDirectory(prefix='outbound-aggregate-receipt-') as name:
            copy = Path(name) / 'monitor'; shutil.copytree(original, copy)
            with mock.patch.object(train.aggregate_supervisor, 'MONITOR', copy):
                self.assertEqual(len(train.dataset_supervision(report)), 7)
                path = copy / 'result.json'; result = json.loads(path.read_text())
                result['finalResultSHA256'] = '0' * 64; path.write_text(json.dumps(result))
                with self.assertRaises(ValueError): train.dataset_supervision(report)

    def test_private_build_supervisor_hash_and_clean_exit_required(self):
        with tempfile.TemporaryDirectory(prefix='outbound-build-receipt-') as name:
            root = Path(name); directory = root / 'monitor'; directory.mkdir(); built_dir = root / 'build'; built_dir.mkdir()
            (built_dir / 'build.json').write_text('{}')
            pins = {'example': 'digest'}; binaries = {'control': 'a', 'trainer': 'b', 'reflink-probe': 'c'}
            command = ['supervised', 'build']; status = {'clientExit': 0, 'signal': None, 'timedOut': False,
                        'remainingWorkersTerminated': False, 'processGroup': 5}
            launch = {'command': command, 'environment': {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home())},
                      'wallSeconds': 900, 'sourcePins': pins}
            worker = {'status': 'isolated_build_only', 'sourcePins': pins,
                      'buildSHA256': train.sha(built_dir / 'build.json'), 'binaries': binaries,
                      'cpuNice': 19, 'ioClass': 'idle'}
            for filename, value in (('launch.json', launch), ('worker-result.json', worker), ('supervisor-result.json', status)):
                (directory / filename).write_text(json.dumps(value))
            result = {'status': 'isolated_build_only', 'reason': None, 'supervisorStatus': status,
                      'launchSHA256': train.sha(directory / 'launch.json'),
                      'workerSHA256': train.sha(directory / 'worker-result.json'),
                      'buildSHA256': train.sha(built_dir / 'build.json')}
            path = directory / 'result.json'; path.write_text(json.dumps(result))
            with mock.patch.object(train.build_supervisor, 'MONITOR', directory), \
                    mock.patch.object(train.build_supervisor, 'command', return_value=command), \
                    mock.patch.object(train.build_supervisor, 'source_pins', return_value=pins), \
                    mock.patch.object(train.design, 'TRAINER', built_dir):
                self.assertEqual(len(train.build_supervision({'binaries': binaries})), 4)
                result['workerSHA256'] = '0' * 64; path.write_text(json.dumps(result))
                with self.assertRaises(ValueError): train.build_supervision({'binaries': binaries})

    def test_fixed_command_and_failure_status(self):
        cmd = train.command()
        for name, value in (('--epochs', '1'), ('--batch', '2'), ('--seed', '7120000'),
                            ('--learning-rate-micros', '100'), ('--checkpoint-every', '1')):
            self.assertEqual(cmd[cmd.index(name) + 1], value)
        self.assertEqual(cmd[cmd.index('--policy') + 1], str(train.design.PARENT))
        self.assertIn('--memory-map', cmd); self.assertIn('--carry-cue', cmd)
        okay = {'clientExit': 0, 'signal': None, 'timedOut': False, 'remainingWorkersTerminated': False, 'processGroup': 4}
        self.assertTrue(monitor.clean(okay))
        for key, value in (('clientExit', 1), ('signal', 9), ('timedOut', True),
                           ('remainingWorkersTerminated', True), ('processGroup', 0)):
            changed = dict(okay); changed[key] = value
            self.assertFalse(monitor.clean(changed))

    def test_freeze_requires_fresh_paths_and_exact_manifest(self):
        with tempfile.TemporaryDirectory(prefix='outbound-plan-') as name:
            root = Path(name); manifest = root / 'plan.json'; model = root / 'model'; package = root / 'package'
            with mock.patch.object(train, 'P', root), mock.patch.object(train, 'MANIFEST', manifest), \
                    mock.patch.object(train, 'MODEL', model), mock.patch.object(train, 'PACKAGE', package), \
                    mock.patch.object(train, 'capacity'), mock.patch.object(train, 'inputs', return_value={'frozen': True}):
                worker = root / 'outbound-five-train-worker-v1'; worker.mkdir()
                with self.assertRaises(FileExistsError): train.freeze()
                self.assertFalse(manifest.exists()); worker.rmdir()
                frozen = train.freeze(); self.assertEqual(train.verify_manifest(), frozen)
                frozen['optimizer'] = 'incorrect'; manifest.write_text(json.dumps(frozen))
                with self.assertRaises(ValueError): train.verify_manifest()


class PackageTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='outbound-package-')
        root = Path(self.temp.name); self.model = root / 'model'; self.model.mkdir()
        self.package = root / 'package'; self.data = root / 'dataset'; self.data.mkdir()
        (self.data / 'data.bin').write_bytes(b'dataset'); (self.data / 'map.bin').write_bytes(b'map')
        (self.model / 'data.bin').write_bytes(b'dataset')
        initial = b'PUPV0001' + (1).to_bytes(8, 'little') + bytes(272) + b'old!'
        final = initial[:-4] + b'new!'
        for name, blob in (('seed.bin', initial), ('initial.bin', initial), ('weights.bin', initial),
                           ('epoch-1.bin', final), ('last.bin', final), ('policy', b'policy'),
                           ('model.pup', b'graph'), ('factory.flex', b'factory'), ('backend.txt', b'hip')):
            (self.model / name).write_bytes(blob)
        (self.model / 'kernels').mkdir()
        for i in range(5): (self.model / 'kernels' / str(i)).write_text(str(i))
        kernels = {str(i): train.sha(self.model / 'kernels' / str(i)) for i in range(5)}
        self.parent = {'weightsSHA256': train.sha(self.model / 'initial.bin'),
                       'binarySHA256': train.sha(self.model / 'policy'),
                       'graphSHA256': train.sha(self.model / 'model.pup'), 'kernels': kernels}
        receipt = {'initialWeightsSHA256': self.parent['weightsSHA256'], 'dataSHA256': train.sha(self.data / 'data.bin'),
                   'memoryMapTargetsSHA256': train.sha(self.data / 'map.bin'), 'epochs': 1, 'batch': 2,
                   'learningRateMicros': 100, 'seed': 7120000, 'checkpointEveryEpochs': 1,
                   'sequenceMirrorAugmentation': True, 'carryCue': True, 'speedTransitionLossWeight': 1,
                   'stopLossWeight': 5, 'actionCodec': 'joint-seven-v1', 'memoryWidth': 128,
                   'phaseSupervisionFromValidFrames': False, 'taskFeedback': False,
                   'trainingRuntime': 'Flexscript/Pup HIP (RDNA)',
                   'weightsSHA256': train.sha(self.model / 'weights.bin'), 'binarySHA256': self.parent['binarySHA256'],
                   'graphSHA256': self.parent['graphSHA256'], 'kernels': kernels}
        (self.model / 'receipt.json').write_text(json.dumps(receipt))
        (self.model / 'curves.jsonl').write_text('\n'.join(json.dumps(row) for row in [
            {'epoch': 0, 'optimizerSteps': 0, 'trainingLoss': 1.0, 'validationLoss': 1.0},
            {'epoch': 1, 'optimizerSteps': 467, 'trainingLoss': .9, 'validationLoss': 1.1}]) + '\n')
        order = struct.pack('<1029Q', *range(1029))
        (self.model / 'first-order.bin').write_bytes(order); (self.model / 'final-order.bin').write_bytes(order)
        (self.model / 'first-mirror-mask.bin').write_bytes(struct.pack('<Q', 3))
        self.stack = [mock.patch.object(train, 'MODEL', self.model), mock.patch.object(train, 'PACKAGE', self.package),
                      mock.patch.object(train.design, 'AGGREGATE', self.data),
                      mock.patch.object(train.design, 'parent_receipt', return_value=self.parent)]
        for patch in self.stack: patch.start()

    def tearDown(self):
        for patch in reversed(self.stack): patch.stop()
        self.temp.cleanup()

    def test_fixed_checkpoint_is_used_even_when_validation_selected_initial(self):
        result = train.package_fixed_epoch()
        self.assertEqual(result['weightsSHA256'], train.sha(self.model / 'epoch-1.bin'))
        self.assertNotEqual(result['weightsSHA256'], train.sha(self.model / 'weights.bin'))
        self.assertEqual(train.verify_package(), result)
        derived = json.loads((self.package / 'receipt.json').read_text())
        self.assertEqual(derived['checkpointEpoch'], 1)
        self.assertEqual(derived['checkpointSourceWeightsSHA256'], train.sha(self.model / 'weights.bin'))

    def test_rejects_incomplete_training_or_altered_package(self):
        curves = self.model / 'curves.jsonl'; original = curves.read_text()
        curves.write_text(original.replace('467', '466'))
        with self.assertRaises(ValueError): train.verify_model()
        curves.write_text(original)
        train.package_fixed_epoch()
        path = self.package / 'weights.bin'; path.chmod(0o644); path.write_bytes(b'tampered')
        with self.assertRaises(ValueError): train.verify_package()

    def test_non_hip_backend_or_receipt_is_rejected(self):
        marker = self.model / 'backend.txt'; marker.write_text('cuda')
        with self.assertRaisesRegex(ValueError, 'backend'): train.verify_model()
        marker.write_text('hip')
        path = self.model / 'receipt.json'; receipt = json.loads(path.read_text())
        receipt['trainingRuntime'] = 'Flexscript/Pup CUDA'; path.write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError, 'trainingRuntime'): train.verify_model()

    def test_changed_fit_split_order_and_mirror_are_rejected(self):
        first = self.model / 'first-order.bin'; final = self.model / 'final-order.bin'
        original = first.read_bytes(); order = list(struct.unpack('<1029Q', original))
        order[0] = order[1]; duplicate = struct.pack('<1029Q', *order)
        first.write_bytes(duplicate); final.write_bytes(duplicate)
        with self.assertRaisesRegex(ValueError, 'fit/validation'): train.verify_model()
        first.write_bytes(original); final.write_bytes(original[:-8])
        with self.assertRaisesRegex(ValueError, 'orders'): train.verify_model()
        final.write_bytes(original); (self.model / 'first-mirror-mask.bin').write_bytes(struct.pack('<Q', 4))
        with self.assertRaisesRegex(ValueError, 'mirror'): train.verify_model()


if __name__ == '__main__':
    unittest.main()
