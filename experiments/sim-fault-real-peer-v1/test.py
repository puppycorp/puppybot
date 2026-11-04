#!/usr/bin/env python3
"""CPU-only build and synthetic-peer coverage of the fault relay."""
import importlib.util
import json
import os
from contextlib import nullcontext
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
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


build = load('real_fault_build', HERE / 'build.py')
trial = load('real_fault_trial', HERE / 'trial.py')
experiment = load('real_fault_experiment', HERE / 'experiment.py')

FAKE = r'''import json,os,socket,struct,sys
fd=int(sys.argv[sys.argv.index('--agent-fd')+1]); sock=socket.socket(fileno=fd)
def read(n):
    b=b''
    while len(b)<n:
        p=sock.recv(n-len(b))
        if not p: raise EOFError()
        b+=p
    return b
state={'step':100,'totalSteps':100,'pose':[0.,0.,0.],'physicsFault':0,
 'vehicle':{'queryFault':0},'trainingOracle':{'enabled':False,'queries':0},
 'gripper':{'held':False,'grasps':0,'releases':0},
 'discovery':{'suppliedMap':False,'worldPoseInput':False,'scans':0,'freeCells':0,'occupiedCells':0},
 'camera':{'pose':'driving','armSettled':True},'case':{'passed':False,'perception':{'frameId':100}},
 'jointAnglesRad':[0.,0.,0.,0.],'findReturn':{'consumedIndex':-1},
 'controller':{'drive':{'leftSpeed':0,'rightSpeed':0,'steeringAngleDeg':90}}}
while True:
    c,seq,steer,speed,hold,_,task,_=struct.unpack('<8q',read(64))
    if c==3:
        print('FAULT_TEST_SIM_STOP_ZERO',flush=True);break
    if c==2:
        state['step']+=hold;state['totalSteps']=state['step'];state['case']['perception']['frameId']=state['step']
        state['controller']['drive'].update(leftSpeed=int(speed*60/1000),rightSpeed=int(speed*60/1000),steeringAngleDeg=90)
    body=json.dumps(state,separators=(',',':')).encode()
    sock.sendall(struct.pack('<4q',len(body),640*480*3,seq,0)+body+bytes(640*480*3))
'''


class TrialTests(unittest.TestCase):
    def test_current_and_freeze_check_real_build_and_runtime(self):
        # Exercise the real permanent build receipt and runtime chain.  Keep
        # the plan and output names disposable and do not start a simulator.
        with tempfile.TemporaryDirectory(prefix='real-peer-plan-') as temp:
            root = Path(temp)
            with (mock.patch.object(experiment, 'MANIFEST', root / 'plan.json'),
                  mock.patch.object(experiment, 'OUTPUT', root / 'output'),
                  mock.patch.object(experiment, 'MONITOR', root / 'monitor'),
                  mock.patch.object(experiment.guard, 'require_dedicated_process'),
                  mock.patch.object(experiment.base, 'acquire_lock', return_value=nullcontext())):
                expected_runtime = experiment.prior.runtime_chain()
                current = experiment.current()
                self.assertEqual(current['runtime'], expected_runtime)
                self.assertEqual(current['status'], 'frozen_before_play')
                frozen = experiment.freeze()
                self.assertEqual(frozen, current)
                self.assertEqual(experiment.verify(), frozen)
                # Imported helpers are executed again in fresh subprocesses;
                # changing one after registration must censor the attempt.
                helper = ROOT / 'datasets/visual-control/chase-v1/levels/prepare-route-factorial.py'
                self.assertIn(str(helper), frozen['files'])
                actual_sha = experiment.builder.sha
                def changed_sha(path):
                    if Path(path) == helper: return '0' * 64
                    return actual_sha(path)
                with mock.patch.object(experiment.builder, 'sha', side_effect=changed_sha):
                    with self.assertRaisesRegex(ValueError, 'registered fault inputs changed'):
                        experiment.verify()
                with mock.patch.object(experiment.prior, 'runtime_chain', return_value={'changed': True}):
                    with self.assertRaisesRegex(ValueError, 'registered fault inputs changed'):
                        experiment.verify()

    def test_fresh_process_uses_isolated_monitor_bindings(self):
        raw = subprocess.check_output(experiment.python_call('describe_configuration'), cwd=ROOT, text=True, timeout=10)
        config = json.loads(raw)
        self.assertEqual(config['output'], str(experiment.OUTPUT))
        self.assertEqual(config['registration'], str(HERE / 'experiment.py'))
        self.assertEqual(config['worker'], experiment.python_call('run'))

    def test_transform_and_pair_with_synthetic_simulator(self):
        with tempfile.TemporaryDirectory(prefix='real-peer-build-') as temp:
            root = Path(temp); artifact = root / 'build'; receipt = build.build(artifact)
            self.assertEqual(receipt['simulatorSHA256'], build.sha(artifact / 'simulator'))
            self.assertEqual(receipt['probeSHA256'], build.sha(artifact / 'probe'))
            fake = root / 'fake.py'; fake.write_text(FAKE)
            env = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home())}
            first = trial.run_arm(root / 'control', [sys.executable, fake], artifact / 'probe', 'control', env)
            second = trial.run_arm(root / 'fault', [sys.executable, fake], artifact / 'probe', 'fault', env)
            self.assertEqual(first['probeExit'], 0); self.assertNotEqual(second['probeExit'], 0)
            self.assertTrue(trial.audit(root / 'control', root / 'fault')['simulatorStopZeroMarker'])
            # A matched pair with corrupted saved echoes or a changed command
            # must not pass merely because its two records agree.
            for mutate in (
                lambda item: item['states'][1]['drive'].update(leftSpeed=0, rightSpeed=0),
                lambda item: item['requests'][1].update(speed=0),
                lambda item: item['states'][1].update(sequence=99),
            ):
                for name, value in (('control', first), ('fault', second)):
                    changed = json.loads(json.dumps(value)); mutate(changed)
                    (root / name / 'result.json').write_text(json.dumps(changed))
                with self.assertRaises(ValueError): trial.audit(root / 'control', root / 'fault')
            for name, value in (('control', first), ('fault', second)):
                (root / name / 'result.json').write_text(json.dumps(value))
            self.assertTrue(trial.audit(root / 'control', root / 'fault')['simulatorStopZeroMarker'])
            # An apparently completed simulator without the post-stop marker
            # must never be treated as a successful command-3 observation.
            original = trial.MARKER
            with mock.patch.object(trial, 'MARKER', 'ABSENT_MARKER'):
                with self.assertRaises(ValueError):
                    trial.run_arm(root / 'missing', [sys.executable, fake], artifact / 'probe', 'fault', env)
            self.assertEqual(trial.MARKER, original)
            with (artifact / 'probe').open('ab') as stream: stream.write(b'tamper')
            with self.assertRaises(ValueError): build.verify(artifact)


if __name__ == '__main__': unittest.main()
