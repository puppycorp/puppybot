#!/usr/bin/env python3
"""CPU-only fixtures for monitored full-training completion."""
import importlib.util
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
path = ROOT / 'datasets/visual-control/chase-v1/levels/heading-full-training-receipt.py'
spec = importlib.util.spec_from_file_location('training_receipt_fixture', path)
r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)


class ReceiptTest(unittest.TestCase):
    def test_training_receipt_and_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp); output = p / 'output'; output.mkdir(); models = output / 'models'; models.mkdir()
            parent = p / 'parent'; parent.mkdir(); (parent / 'weights.bin').write_text('fixture')
            small = p / 'small'; small.mkdir(); (small / 'comparison.json').write_text('{}')
            monitor = p / 'monitor'; monitor.mkdir(); (monitor / 'outer-monitor').mkdir()
            wrapper = p / 'wrapper.py'; wrapper.write_text('wrapper')
            clean = {'clientExit': 0, 'signal': None, 'timedOut': False,
                     'remainingWorkersTerminated': False, 'processGroup': 123}
            (monitor / 'outer-monitor/supervisor-result.json').write_text(json.dumps(clean))
            (monitor / 'monitor-result.json').write_text('{"status":"passed"}')
            def gpu(phase, t):
                return {'phase': phase, 'monotonicSeconds': t, 'unixSeconds': t, 'busyPercent': 3,
                        'totalBytes': 16 * r.GIB, 'usedBytes': 8 * r.GIB, 'freeBytes': 8 * r.GIB}
            rows = [gpu('baseline', t) for t in range(100, 131)] + [gpu('training', 131), gpu('after-training', 132)]
            disk = [{'phase': phase, 'monotonicSeconds': t, 'unixSeconds': t, 'freeBytes': 35 * r.GIB}
                    for phase, t in [('pre-baseline', 99), ('post-baseline', 130.5), ('training', 131.5), ('after-training', 132.5)]]
            gpu_path = monitor / 'telemetry.jsonl'; disk_path = monitor / 'disk.jsonl'
            gpu_path.write_text(''.join(json.dumps(x) + '\n' for x in rows))
            disk_path.write_text(''.join(json.dumps(x) + '\n' for x in disk))
            code = ('import importlib.util,sys;'
                    's=importlib.util.spec_from_file_location("monitored",sys.argv[1]);'
                    'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);'
                    'm.monitor_worker(sys.argv[2])')
            env = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'SDL_VIDEODRIVER': 'offscreen',
                   'LD_LIBRARY_PATH': str(r.ROOT / 'build/flex/rocm-runtime')}
            (monitor / 'launch.json').write_text(json.dumps({'sourcePins': {'source.fixture': 'hash'},
                'command': [sys.executable, '-I', '-c', code, str(wrapper), str(monitor)],
                'environment': env, 'wallSeconds': 15000}))
            (monitor / 'worker-invocation.json').write_text(json.dumps({'argv': [sys.executable, '-I', str(r.RUNNER)], 'cwd': str(r.ROOT)}))
            (output / 'pair-ready.json').write_text('{}'); inputs = {}
            for arm in ('control', 'treatment'):
                data = output / f'aggregate-{arm}'; data.mkdir()
                for name, value in (('data.bin', 'fixture'), ('map.bin', 'map')):
                    (data / name).write_text(value); inputs[str(data / name)] = r.digest(data / name)
            (models / 'inputs.json').write_text(json.dumps(inputs))
            with mock.patch.object(r, 'OUTPUT', output), mock.patch.object(r, 'MODELS', models), \
                 mock.patch.object(r, 'MONITORED', monitor), mock.patch.object(r, 'MONITOR_SCRIPT', wrapper), \
                 mock.patch.object(r, 'PARENT', parent), mock.patch.object(r, 'source_pins', return_value={'source.fixture': 'hash'}), \
                 mock.patch.object(r.training, 'sources', return_value=inputs), mock.patch.object(r.training.small, 'RESULT', small):
                for arm in ('control', 'treatment'):
                    job = models / f'monitor-{arm}'; job.mkdir(); model = models / f'{arm}-s0'; model.mkdir()
                    (job / 'supervisor-result.json').write_text(json.dumps(clean))
                    (job / 'command.json').write_text(json.dumps(r.expected_command(arm))); (job / 'client.log').write_text('ready')
                    for name in ('data.bin', 'weights.bin', 'initial.bin', 'first-order.bin', 'final-order.bin',
                                 'first-mirror-mask.bin', 'epoch-8.bin', 'last.bin', 'policy', 'model.pup',
                                 'factory.flex', 'receipt.json', 'curves.jsonl'):
                        (model / name).write_text('fixture')
                    for name in ('first-order.bin', 'final-order.bin'):
                        (model / name).write_bytes(struct.pack('<1024Q', *range(1024)))
                    (model / 'first-mirror-mask.bin').write_bytes(struct.pack('<Q', 0))
                    rows_curve = [{'epoch': i, 'optimizerSteps': 464 * i, 'mirroredTrainingSequences': i} for i in range(9)]
                    (model / 'curves.jsonl').write_text(''.join(json.dumps(x) + '\n' for x in rows_curve))
                    (model / 'kernels').mkdir(); (model / 'kernels/a').write_text('kernel')
                    (model / 'receipt.json').write_text(json.dumps({'dataSHA256': r.digest(model / 'data.bin'),
                        'memoryMapTargetsSHA256': inputs[str(output / f'aggregate-{arm}/map.bin')],
                        'initialWeightsSHA256': r.digest(parent / 'weights.bin'), 'seed': 6900000, 'epochs': 8,
                        'batch': 2, 'checkpointEveryEpochs': 8, 'sequenceMirrorAugmentation': True, 'carryCue': True,
                        'speedTransitionLossWeight': 1, 'actionCodec': 'joint-seven-v1',
                        'weightsSHA256': r.digest(model / 'weights.bin'), 'binarySHA256': r.digest(model / 'policy'),
                        'graphSHA256': r.digest(model / 'model.pup'), 'kernels': {'a': r.digest(model / 'kernels/a')}}))
                arms = {arm: {'weightsSHA256': r.digest(models / f'{arm}-s0/weights.bin'),
                              'receiptSHA256': r.digest(models / f'{arm}-s0/receipt.json')}
                        for arm in ('control', 'treatment')}
                report = {'status': 'training_diagnostic_only', 'arms': arms, 'pairReadySHA256': r.digest(output / 'pair-ready.json'),
                          'smallPilotSHA256': r.digest(small / 'comparison.json'),
                          'matchedArtifacts': r.matched_training.audit(parent, models / 'control-s0', models / 'treatment-s0')}
                (models / 'training-report.json').write_text(json.dumps(report))
                with self.assertRaises(FileNotFoundError): r.verify()
                receipt = {'status': 'passed', 'hashes': r.snapshot(), 'freeBytesBeforeReceipt': 34 * r.GIB}
                (monitor / 'completion.json').write_text(json.dumps(receipt))
                self.assertEqual(r.verify()['status'], 'passed')
                (small / 'comparison.json').write_text('{"changed":true}')
                with self.assertRaisesRegex(ValueError, 'input provenance differs'): r.verify()
                (small / 'comparison.json').write_text('{}')
                data = models / 'control-s0/data.bin'; data.write_text('wrong')
                with self.assertRaisesRegex(ValueError, 'trainer input clone bytes differ'): r.verify()
                data.write_text('fixture')
                receipt_path = models / 'control-s0/receipt.json'; old_receipt = receipt_path.read_text()
                invalid = json.loads(old_receipt); invalid['epochs'] = 1; receipt_path.write_text(json.dumps(invalid))
                with self.assertRaisesRegex(ValueError, 'receipt parameters differ'): r.verify()
                receipt_path.write_text(old_receipt)
                missing = dict(report); del missing['matchedArtifacts']
                (models / 'training-report.json').write_text(json.dumps(missing))
                with self.assertRaisesRegex(ValueError, 'artifact comparison differs'): r.verify()
                (models / 'training-report.json').write_text(json.dumps(report))
                curve = models / 'treatment-s0/curves.jsonl'; old_curve = curve.read_text()
                broken = [json.loads(x) for x in old_curve.splitlines()]; broken[8]['optimizerSteps'] -= 1
                curve.write_text(''.join(json.dumps(x) + '\n' for x in broken))
                with self.assertRaisesRegex(ValueError, 'optimizer counts'): r.verify()
                curve.write_text(old_curve)
                weight = models / 'control-s0/epoch-8.bin'; weight.write_text('changed')
                with self.assertRaisesRegex(ValueError, 'receipt differs'): r.verify()
                weight.write_text('fixture')
                command = models / 'monitor-treatment/command.json'; command.write_text(json.dumps(r.expected_command('control')))
                with self.assertRaisesRegex(ValueError, 'command intent differs'): r.verify()
                command.write_text(json.dumps(r.expected_command('treatment')))
                dirty = dict(clean); dirty['timedOut'] = True
                status = models / 'monitor-control/supervisor-result.json'; status.write_text(json.dumps(dirty))
                with self.assertRaisesRegex(ValueError, 'unclean'): r.verify()
                status.write_text(json.dumps(clean))
                rows[-1]['usedBytes'] = 15 * r.GIB; rows[-1]['freeBytes'] = r.GIB
                gpu_path.write_text(''.join(json.dumps(x) + '\n' for x in rows))
                with self.assertRaisesRegex(ValueError, 'GPU memory guard'): r.verify()
                rows[-1] = gpu('after-training', 132)
                gpu_path.write_text(''.join(json.dumps(x) + '\n' for x in rows))
                disk[-1]['freeBytes'] = 33 * r.GIB
                disk_path.write_text(''.join(json.dumps(x) + '\n' for x in disk))
                with self.assertRaisesRegex(ValueError, 'disk headroom'): r.verify()


if __name__ == '__main__': unittest.main()
