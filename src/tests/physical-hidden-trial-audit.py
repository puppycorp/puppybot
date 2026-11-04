#!/usr/bin/env python3
# CPU-only tests for the out-of-view physical-simulation selection audit.
import importlib.util
import hashlib
import json
import os
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

path = Path(__file__).with_name('run-physical-hidden-trial.py')
spec = importlib.util.spec_from_file_location('hidden_trial', path)
trial = importlib.util.module_from_spec(spec); spec.loader.exec_module(trial)


def row(seq, tick, owner, ack, valid, detected, drive):
    return {'schema': 'puppybot.physical-agent.v1', 'sequence': seq, 'step': tick, 'timeMs': tick * 20,
            'owner': owner, 'ack': ack, 'imageValid': valid, 'rgbDetections': detected,
            'driveCommand': drive, 'jointTicks': [1, 2, 3, 4], 'totalSteps': tick,
            'cameraFrame': tick if valid else -1, 'cameraDriving': valid, 'cameraStill': valid}


def fixture(root):
    actors = root / 'actors'; actors.mkdir()
    for ext, data in (('.rgb', bytes(21168)), ('.feedback', bytes(28)),
                      ('.hidden', bytes(512)), ('.action', struct.pack('<2f', 0.0, 0.2))):
        (actors / ('actor-1' + ext)).write_bytes(data)
    result = {'policyActions': 1, 'handoff': True, 'stopCommandAcknowledged': True, 'outcome': 'unverified'}
    journal = [row(1, 100, 0, 0, True, 0, [0, 0, 90]), row(2, 110, 0, 1, True, 1, [12, 12, 90]),
               row(3, 112, 1, 3, False, None, [0, 0, 90]), row(4, 112, 2, 7, False, None, [0, 0, 90])]
    return result, journal


class HiddenAuditTest(unittest.TestCase):
    def test_accepts_learned_action_then_detected_handoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, journal = fixture(Path(tmp))
            audit = trial.check_actor_inputs(Path(tmp), result, journal)
            self.assertEqual(audit['policyActions'], 1)
            self.assertEqual(audit['nonzeroDriveActions'], 1)
            self.assertTrue(audit['handoffAfterPolicy'])

    def test_rejects_false_attribution(self):
        mutations = [
            lambda r, j: j[0].update(rgbDetections=1),
            lambda r, j: r.update(policyActions=0),
            lambda r, j: j[1].update(driveCommand=[0, 0, 90]),
            lambda r, j: j[1].update(cameraFrame=109),
            lambda r, j: j[2].update(totalSteps=110),
            lambda r, j: j[1].update(rgbDetections=0),
            lambda r, j: j[-1].update(driveCommand=[1, 1, 90]),
            lambda r, j: j[0].update(worldPose=[0, 0, 0]),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                result, journal = fixture(Path(tmp)); mutation(result, journal)
                with self.assertRaises(ValueError):
                    trial.check_actor_inputs(Path(tmp), result, journal)

    def test_trace_path_requires_contiguous_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'trace.jsonl'
            path.write_text(''.join(json.dumps({'totalSteps': i, 'pose': [i * .1, 0, 0]}) + '\n' for i in range(3)))
            audit = trial.truth_navigation_path(path, 0, 2)
            self.assertAlmostEqual(audit['pathM'], .2)
            path.write_text(json.dumps({'totalSteps': 0, 'pose': [0, 0, 0]}) + '\n' +
                            json.dumps({'totalSteps': 2, 'pose': [.2, 0, 0]}) + '\n')
            with self.assertRaises(ValueError):
                trial.truth_navigation_path(path, 0, 2)
            for bad in (float('nan'), float('inf')):
                path.write_text(''.join(json.dumps({'totalSteps': i, 'pose': [bad if i == 1 else i * .1, 0, 0]}) + '\n' for i in range(3)))
                with self.assertRaises(ValueError):
                    trial.truth_navigation_path(path, 0, 2)
            path.write_text(json.dumps({'totalSteps': 0.0, 'pose': [0, 0, 0]}) + '\n')
            with self.assertRaises(ValueError):
                trial.truth_navigation_path(path, 0, 0)

    def test_supervisor_timeout_cleans_detached_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); pidfile = root / 'child.pid'
            child = 'import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)'
            runner = ('import os,signal,subprocess,sys,time;'
                      'p=subprocess.Popen([sys.executable,"-c",sys.argv[2]],start_new_session=True);'
                      'open(sys.argv[1],"w").write(str(p.pid));'
                      'signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)')
            status = trial.supervise([sys.executable, '-c', runner, str(pidfile), child], root, os.environ.copy(), .8)
            self.assertTrue(status['timedOut']); self.assertTrue(pidfile.exists())
            pid = int(pidfile.read_text())
            self.assertFalse(Path(f'/proc/{pid}').exists(), f'detached worker {pid} survived')

    def test_signal_during_spawn_cleans_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = subprocess.Popen; spawned = []
            def launch_and_signal(*args, **kwargs):
                child = original(*args, **kwargs); spawned.append(child.pid)
                os.kill(os.getpid(), signal.SIGTERM)
                return child
            with mock.patch.object(trial.subprocess, 'Popen', side_effect=launch_and_signal):
                status = trial.supervise([sys.executable, '-c', 'import time;time.sleep(30)'],
                                         Path(tmp), os.environ.copy(), 5)
            self.assertEqual(status['signal'], signal.SIGTERM)
            self.assertFalse(Path(f'/proc/{spawned[0]}').exists(), 'spawned runner survived')

    def test_signal_when_short_runner_has_exited_is_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = subprocess.Popen
            def launch_wait_and_signal(*args, **kwargs):
                child = original(*args, **kwargs); child.wait()
                os.kill(os.getpid(), signal.SIGTERM)
                return child
            with mock.patch.object(trial.subprocess, 'Popen', side_effect=launch_wait_and_signal):
                status = trial.supervise(['/usr/bin/true'], Path(tmp), os.environ.copy(), 5)
            self.assertEqual(status['signal'], signal.SIGTERM)

    def test_mock_full_run_reaches_audit_subprocess(self):
        # Exercise the actual orchestration through its post-run subprocess,
        # without rendering, GPU access or pretending the trace is physical.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); model = root / 'model'; model.mkdir(); (model / 'kernels').mkdir()
            (model / 'weights.bin').write_bytes(b'weights'); (model / 'policy').write_bytes(b'policy')
            sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
            kernels = {}
            for i in range(5):
                name = f'kernel{i}'; p = model / 'kernels' / name; p.write_bytes(name.encode()); kernels[name] = sha(p)
            (model / 'receipt.json').write_text(json.dumps({'weightsSHA256': sha(model / 'weights.bin'),
                'binarySHA256': sha(model / 'policy'), 'kernels': kernels}))
            reference = root / 'reference'; reference.mkdir()
            (reference / 'case.json').write_text(json.dumps({'objects': [{'position': [0, 0, 0]}]}))
            environment = root / 'environment.bin'; environment.write_bytes(b'environment')
            asset = root / 'asset.bin'; asset.write_bytes(b'asset')
            python = Path(shutil.which('python3')).absolute()
            worker = {'launchPath': str(python), 'executable': str(python.resolve()), 'files': {}}

            def fake_build(inputs):
                source = inputs / 'flex-source'; audit_dir = source / 'exploration'; audit_dir.mkdir(parents=True)
                (audit_dir / 'manipulation_audit.py').write_text(
                    'import hashlib,json,sys\n'
                    'print(json.dumps({"caseSHA256":hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest(),'
                    '"status":"diagnostic_only","traceMeetsManipulationCriteria":False}))\n')
                library = inputs / 'build/flex/sim/library'; library.mkdir(parents=True)
                (library / 'dependency.flex').write_text('dependency')
                (inputs / 'simulator').write_bytes(b'simulator'); (inputs / 'client').write_bytes(b'client')
                return trial.supervisor.source_hashes(source), trial.supervisor.source_hashes(library), 'compiler-stub'

            def fake_supervise(command, output, env):
                run = output / 'run'; run.mkdir(); result, journal = fixture(run)
                trace = run / 'trace.jsonl'
                trace.write_text(''.join(json.dumps({'totalSteps': i, 'pose': [(i - 100) * .01, 0, 0]}) + '\n' for i in range(100, 111)))
                result['traceSHA256'] = sha(trace); (run / 'result.json').write_text(json.dumps(result))
                (run / 'physical-agent.jsonl').write_text(''.join(json.dumps(v) + '\n' for v in journal))
                manifest = json.loads((output / 'inputs.json').read_text())
                client = {key: manifest[key] for key in ('simulatorSHA256', 'caseSHA256', 'environmentSHA256',
                                                        'weightsSHA256', 'policySHA256', 'receiptSHA256')}
                client.update(robotAssetSHA256=manifest['assetSHA256'], stoppedRescanEnabled=False)
                (run / 'inputs.json').write_text(json.dumps(client))
                return {'clientExit': 0, 'timedOut': False, 'remainingWorkersTerminated': False, 'signal': None}

            with mock.patch.object(trial, 'MODEL', model), mock.patch.object(trial, 'ENVIRONMENT', environment), \
                    mock.patch.object(trial, 'ASSET', asset), mock.patch.object(trial.rescan, 'REFERENCE', reference), \
                    mock.patch.object(trial.rescan, 'build_snapshot', side_effect=fake_build), \
                    mock.patch.object(trial.supervisor, 'worker_snapshot', return_value=worker), \
                    mock.patch.object(trial, 'supervise', side_effect=fake_supervise):
                output = root / 'output'
                trial.run_trial(output)
            report = json.loads((output / 'audit.json').read_text())
            self.assertEqual(report['status'], 'diagnostic_only')
            self.assertEqual(report['actor']['policyActions'], 1)
            self.assertEqual(report['actor']['causalAttribution'], 'unproven')
            self.assertFalse(report['manipulation']['traceMeetsManipulationCriteria'])


if __name__ == '__main__':
    unittest.main()
