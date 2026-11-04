#!/usr/bin/env python3
"""CPU-only tests of the copied waypoint trial and saved-trace auditor."""
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


build=load('short_test_build',HERE/'build.py')
runner=load('short_test_runner',HERE/'run.py')
monitor=load('short_test_monitor',HERE/'monitor.py')
audit=load('short_test_audit',HERE/'audit.py')
fixture=load('short_test_fixture',ROOT/'experiments/physical-search-fallback-trial-v1/fixture_support.py')


class TrialTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='puppy-short-waypoint-build-')
        cls.root=Path(cls.temp.name);cls.output=cls.root/'build';cls.report=build.build(cls.output)

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def trace(self,name,records):
        path=self.root/name;path.write_text(''.join(json.dumps(row)+'\n' for row in records));return path

    def test_same_binary_build_option_and_no_overwrite(self):
        self.assertEqual(build.verify(self.output),self.report)
        for value,expected in (('0',0),('1',0),('bad',2)):
            done=subprocess.run([str(self.output/'simulator'),'--help'],cwd=ROOT,
                env=dict(os.environ,PUPPYBOT_SIM_DOCK_SHORT_WAYPOINT=value),capture_output=True,text=True,timeout=20)
            self.assertEqual(done.returncode,expected,done.stderr)
        with self.assertRaises(FileExistsError):build.build(self.output)

    def test_arm_environments_and_pins(self):
        pins=monitor.source_pins()
        for arm in runner.ARMS:
            env=runner.env_for('/tmp/trial',arm)
            self.assertEqual(env['PUPPYBOT_SIM_DOCK_FLOOR_RETRY'],'1')
            self.assertEqual(env['PUPPYBOT_SIM_WORKER_BARRIER'],'1')
            self.assertEqual(env['PUPPYBOT_SIM_OBSERVED_FOOTPRINT_V2'],'1')
            self.assertEqual(env['PUPPYBOT_DOCK_HIGH_SURVEY'],'1')
            self.assertEqual(env[build.FLAG],'1' if arm=='candidate-search' else '0')
        for path in (HERE/'audit.py',HERE/'build.py',HERE/'transform.py',
                     ROOT/'experiments/dock-floor-refresh-v1/audit.py',ROOT/'experiments/dock-floor-refresh-v1/barrier.py'):
            self.assertIn(str(path),pins)

    def test_real_manifest_and_wrong_arm_flag(self):
        root=self.root/'trial';root.mkdir();inputs=root/'inputs';inputs.mkdir()
        reference=runner.prior.base.base.REFERENCE/'inputs'
        for name in ('case.json','environment.bin'):shutil.copyfile(reference/name,inputs/name)
        shutil.copytree(reference/'model',inputs/'model')
        worker=runner.hidden.supervisor.worker_snapshot(runner.env_for(root,'baseline'))
        (root/'worker-inputs.json').write_text(json.dumps(worker))
        manifest={'schema':'puppybot.physical-search-fallback-trial.v1','build':str(self.output),
                  'case':str(inputs/'case.json'),'environment':str(inputs/'environment.bin'),'model':str(inputs/'model'),
                  'navigationLimit':90,'collectorPollLimit':1499,'wallSecondsPerArm':300,
                  'files':runner.prior.base.base.pins(root,self.output)}
        runner.check_manifest(root,manifest)
        for arm in runner.ARMS:
            parent=root/arm;parent.mkdir()
            (parent/'command.json').write_text(json.dumps(runner.prior.base.base.command_for(root,manifest,arm)))
            (parent/'environment.json').write_text(json.dumps(runner.env_for(root,arm)))
            runner.check_invocation(root,manifest,arm)
        env=runner.env_for(root,'candidate-search');env[build.FLAG]='0'
        (root/'candidate-search/environment.json').write_text(json.dumps(env))
        with self.assertRaises(ValueError):runner.check_invocation(root,manifest,'candidate-search')

    def test_waypoint_metadata_latch_and_validation(self):
        def state(t,attempted=False,accepted=False,plans=0,path=0):
            return {'step':t,'case':{'boxSearch':{'shortWaypoint':{'attempted':attempted,'accepted':accepted,'plans':plans}},
                                    'navigation':{'pathCount':path}},'gripper':{'held':True}}
        items=[state(1),state(2,True,True,1,4),state(3,True,True,1,4)]
        out=audit.waypoint_report(self.trace('good.jsonl',items),True)
        self.assertEqual((out['attemptTick'],out['acceptedTick'],out['plans']),(2,2,1))
        with self.assertRaises(ValueError):audit.waypoint_report(self.trace('disabled.jsonl',items),False)
        for index,bad in enumerate((state(2,False,True,1,4),state(2,True,True,0,4),state(2,True,True,10,4),
                                    state(2,True,True,1,9),state(2,True,True,1,0))):
            with self.subTest(index=index),self.assertRaises(ValueError):audit.waypoint_report(self.trace(f'bad-{index}.jsonl',[state(1),bad]),True)
        with self.assertRaises(ValueError):audit.waypoint_report(self.trace('reset.jsonl',items+[state(4)]),True)

    def test_complete_synthetic_audit_uses_floor_retry_in_all_arms(self):
        root=self.root/'synthetic';root.mkdir();case=root/'case.json';case.write_text('{}')
        case_hash=hashlib.sha256(case.read_bytes()).hexdigest();binary,model,environment=root/'build',root/'model',root/'environment.bin'
        environment.write_bytes(b'PBENV001'+bytes(112));base=audit.prior.prior.original.base
        files={str(case):case_hash,str(environment):'environment',str(base.hidden.ASSET):'asset'}
        files.update({str(binary/name):name for name in ('simulator','baseline-simulator')})
        files.update({str(model/name):name for name in ('policy','weights.bin','receipt.json')})
        fixture.write_json(root/'inputs.json',{'schema':'puppybot.physical-search-fallback-trial.v1',
            'navigationLimit':90,'collectorPollLimit':1499,'case':str(case),'environment':str(environment),
            'build':str(binary),'model':str(model),'files':files})
        keys=audit.prior.prior.original.clearance.KEYS
        for arm in runner.ARMS:
            run=root/arm/'run';journal,intents,result=fixture.build_protocol(run,'search',polls=1)
            journal[-2].update(owner=2,ack=5);result['collectorTerminal']=True
            client=json.loads((run/'inputs.json').read_text());client.update({'simulatorSHA256':'baseline-simulator' if arm=='baseline' else 'simulator',
                'caseSHA256':case_hash,'environmentSHA256':'environment','weightsSHA256':'weights.bin','policySHA256':'policy',
                'receiptSHA256':'receipt.json','robotAssetSHA256':'asset','cameraPitch':82,'contactFeedback':'unavailable-forced-zero'})
            fixture.write_json(run/'inputs.json',client);diagnostic=run.parent/'diagnostic';diagnostic.mkdir()
            high={'attempts':0,'accepted':0,'ikRejected':0,'moveRejected':0,'requestId':0,'settledStep':-1,'armStillMatching':False,'targetTicks':None}
            dock={'frameId':-1,'valid':False,'surveyDiagnostic':{'count':0,'planCount':0,'writeErrors':0},'clearanceDiagnostic':dict.fromkeys(keys,0)}
            trace=[]
            for tick in range(100,journal[-1]['step']+1):
                active=tick>=104;state={'waits':0,'lastFrameId':-1,'lastWorkerCompleteTick':-1,'lastWallMs':-1,'failures':0}
                if tick>=102:state={'waits':1,'lastFrameId':101,'lastWorkerCompleteTick':102,'lastWallMs':500,'failures':0}
                if tick>=105:state={'waits':2,'lastFrameId':104,'lastWorkerCompleteTick':105,'lastWallMs':600,'failures':0}
                frame=(0 if tick<102 else 101) if not active else (0 if tick==104 else 104)
                box={'mapRefreshes':int(active),'floorRetry':{'attempted':active,'mapping':active and tick<106}}
                if arm=='candidate-search':box['shortWaypoint']={'attempted':tick>=107,'accepted':tick>=107,'plans':int(tick>=107)}
                pickup={'localDockMap':active,'mappingHeldFloor':active and tick<106}
                trace.append({'step':tick,'totalSteps':tick,'timeMs':tick*20+1280,'pose':[0,0,0],
                    'gripper':{'held':True},'case':{'objects':[{'id':'brick'}],'container':{'position':[1,2,0]},
                    'dockVision':dock,'surveyHigh':high,'boxSearch':box,'navigation':{'pathCount':4 if tick>=107 else 0}},
                    'discovery':{'workerBarrier':state,'mapFrameId':frame,'pickup':pickup}})
            (run/'trace.jsonl').write_text(''.join(json.dumps(item)+'\n' for item in trace))
            result['traceSHA256']=base.sha(run/'trace.jsonl');fixture.write_protocol(run,journal,intents,result,True)
            receipt=run.parent/'monitor';receipt.mkdir();fixture.write_json(receipt/'supervisor-result.json',{'clientExit':0,'timedOut':False,
                'signal':None,'remainingWorkersTerminated':False,'processGroup':123})
        fake_runner=type('FixtureRunner',(),{'check_manifest':lambda *args:None,'check_invocation':lambda *args:None})()
        manipulation={'caseSHA256':case_hash,'captures':[],'releases':[],'settledDeliveries':[],
                      'settledAtEnd':False,'traceMeetsManipulationCriteria':False}
        done=subprocess.CompletedProcess([],0,json.dumps(manipulation),'')
        with mock.patch.object(base,'load',return_value=fake_runner),mock.patch.object(base.subprocess,'run',return_value=done):
            report=audit.audit(root)
        self.assertTrue(report['comparisonEligible']);self.assertFalse(report['mechanismEligible'])
        self.assertEqual(report['shortWaypoint']['candidate-search']['acceptedTick'],107)
        self.assertEqual(report['floorRetry']['baseline']['attemptTick'],104)
        self.assertEqual(report['floorRetry']['candidate-disabled']['attemptTick'],104)


if __name__=='__main__':unittest.main()
