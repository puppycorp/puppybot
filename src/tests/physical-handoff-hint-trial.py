#!/usr/bin/env python3
"""CPU-only checks for the staged handoff experiment's fail-closed pieces."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('hint_audit',ROOT/'flex/tests/audit-physical-handoff-hint.py')
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)


class TrialTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)

    def test_prior_protocol_and_rejected_stalled_handoff(self):
        reference=ROOT/'build/flex/sim/levels-v2/pitch82/physical-hybrid-visible-trial/run'
        rows=[json.loads(line) for line in (reference/'physical-agent.jsonl').read_text().splitlines()]
        result=json.loads((reference/'result.json').read_text())
        def write():
            (self.root/'physical-agent.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
        (self.root/'actors').mkdir();write();self.assertEqual(audit.protocol(self.root,result)['policyActions'],0)
        rows[1]['totalSteps']=rows[0]['totalSteps'];rows[1]['step']=rows[0]['step'];write()
        with self.assertRaises(ValueError):audit.protocol(self.root,result)
        rows[1]['totalSteps']=rows[0]['totalSteps']+2;rows[1]['step']=rows[1]['totalSteps']
        rows[2]['ack']=1;write()
        with self.assertRaises(ValueError):audit.protocol(self.root,result)
        rows[2]['ack']=4;write();(self.root/'actors/actor-1.rgb').write_bytes(b'x')
        with self.assertRaises(ValueError):audit.protocol(self.root,result)

    def test_trace_counter_and_fault_checks(self):
        path=self.root/'trace.jsonl'
        rows=[{'step':1,'blocked':False,'physicsFault':0,'handoffHint':{'captures':0,'uses':0}},
              {'step':2,'blocked':True,'physicsFault':0,'handoffHint':{'captures':1,'uses':1}}]
        def write():path.write_text(''.join(json.dumps(row)+'\n' for row in rows))
        write();self.assertEqual(audit.trace_metrics(path,True,0)['hintUses'],1)
        with self.assertRaises(ValueError):audit.trace_metrics(path,True,2)
        with self.assertRaises(ValueError):audit.trace_metrics(path,False)
        rows[1]['handoffHint']['uses']=2;write()
        with self.assertRaises(ValueError):audit.trace_metrics(path,True,0)
        rows[1]['handoffHint']['uses']=1;rows[1]['physicsFault']=1;write()
        with self.assertRaises(ValueError):audit.trace_metrics(path,True,0)

    def test_cli_remains_disabled_and_cpu_preflight(self):
        script=ROOT/'flex/tests/run-physical-handoff-hint.py'
        denied=subprocess.run([sys.executable,'-I',str(script),str(self.root/'run')],capture_output=True,text=True,timeout=30)
        self.assertNotEqual(denied.returncode,0);self.assertFalse((self.root/'run').exists())
        checked=subprocess.run([sys.executable,'-I',str(script),'--check'],capture_output=True,text=True,timeout=30)
        self.assertEqual(checked.returncode,0,checked.stderr);self.assertEqual(json.loads(checked.stdout)['status'],'cpu_preflight_only')

    def test_actual_auditor_censors_missing_arm(self):
        runner=audit.runner;root=self.root
        manifest={'schema':'puppybot.physical-handoff-hint-trial.v1','build':str(runner.BUILD),
                  'original':str(runner.BUILD/'inputs/simulator'),'candidate':str(runner.BUILD/'simulator-hint'),
                  'client':str(runner.BUILD/'inputs/client'),'case':str(root/'inputs/case.json'),
                  'environment':str(root/'inputs/environment.bin'),'model':str(root/'inputs/model'),
                  'asset':'/test/asset','home':'/test/home','navigationLimit':30,'collectorPollLimit':1499,'wallSecondsPerArm':300}
        manifest['files']={path:'hash' for path in (manifest['original'],manifest['candidate'],manifest['client'],manifest['case'],manifest['environment'],manifest['asset'],
            str(Path(manifest['model'])/'weights.bin'),str(Path(manifest['model'])/'policy'),str(Path(manifest['model'])/'receipt.json'))}
        (root/'inputs.json').write_text(json.dumps(manifest))
        source=ROOT/'build/flex/sim/levels-v2/pitch82/physical-hybrid-visible-trial/run'
        for name,sim,flag in (('original',manifest['original'],'0'),('candidate-disabled',manifest['candidate'],'0'),('candidate-enabled',manifest['candidate'],'1')):
            parent=root/name;run=parent/'run';run.mkdir(parents=True);(run/'actors').mkdir();(parent/'monitor').mkdir()
            (parent/'monitor/supervisor-result.json').write_text(json.dumps({'clientExit':0,'timedOut':False,'signal':None,'remainingWorkersTerminated':False}))
            (parent/'command.json').write_text(json.dumps([manifest['client'],sim,manifest['model'],manifest['case'],manifest['environment'],str(run),'--allow-zero-contact']))
            env={'PATH':'/usr/bin:/bin','HOME':manifest['home'],'SDL_VIDEODRIVER':'offscreen','LD_LIBRARY_PATH':str(ROOT/'build/flex/rocm-runtime'),
                 'PUPPYBOT_PHYSICAL_NAV_LIMIT':'30','PUPPYBOT_PHYSICAL_POLL_LIMIT':'1499','PUPPYBOT_PHYSICAL_HANDOFF_HINT':flag}
            (parent/'environment.json').write_text(json.dumps(env))
            (run/'physical-agent.jsonl').write_bytes((source/'physical-agent.jsonl').read_bytes())
            initial={'step':495,'blocked':False,'physicsFault':0,'pose':[0,0,0],
                     'case':{'objects':[{'id':'block','position':[1,0,0],'quaternion':[0,0,0,1]}],
                             'container':{'position':[2,0,0],'quaternion':[0,0,0,1]}}}
            if flag=='1':initial['handoffHint']={'captures':0,'uses':0}
            trace=[initial]
            if flag=='1':trace.append({'step':498,'blocked':False,'physicsFault':0,'handoffHint':{'captures':1,'uses':1}})
            (run/'trace.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in trace))
            result=json.loads((source/'result.json').read_text());result.update(traceSHA256=audit.sha(run/'trace.jsonl'),collectorPollLimit=1499,stoppedRescanEnabled=False)
            (run/'result.json').write_text(json.dumps(result))
            client={'simulatorSHA256':'hash','caseSHA256':'hash','environmentSHA256':'hash','weightsSHA256':'hash','policySHA256':'hash','receiptSHA256':'hash','robotAssetSHA256':'hash'}
            (run/'inputs.json').write_text(json.dumps(client))
        manipulation={'caseSHA256':'hash','captures':[],'releases':[],'settledDeliveries':{},'settledAtEnd':[],'traceMeetsManipulationCriteria':False}
        response=mock.Mock(returncode=0,stdout=json.dumps(manipulation))
        with mock.patch.object(runner,'check',return_value=({},{})),mock.patch.object(runner,'pins',return_value=manifest['files']),mock.patch.object(audit.subprocess,'run',return_value=response):
            report=audit.audit(root)
        self.assertTrue(report['originalVsDisabledOutcomeAndInitialObservationMatch'])
        self.assertTrue(report['comparisonEligible'])
        run=root/'candidate-enabled/run';trace=[json.loads(line) for line in (run/'trace.jsonl').read_text().splitlines()]
        trace[0]['case']['objects'][0]['position'][0]=3;(run/'trace.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in trace))
        result=json.loads((run/'result.json').read_text());result['traceSHA256']=audit.sha(run/'trace.jsonl');(run/'result.json').write_text(json.dumps(result))
        with mock.patch.object(runner,'check',return_value=({},{})),mock.patch.object(runner,'pins',return_value=manifest['files']),mock.patch.object(audit.subprocess,'run',return_value=response):
            report=audit.audit(root)
            self.assertFalse(report['comparisonEligible']);self.assertEqual(report['comparisonCensorReason'],'initial_metadata_or_truth_mismatch')
            (root/'candidate-enabled/monitor/supervisor-result.json').unlink();report=audit.audit(root)
        self.assertEqual(report['arms'][2]['reason'],'not_started_or_no_supervisor');self.assertFalse(report['comparisonEligible'])

    def test_partial_audit_preserves_failure_log(self):
        runner=audit.runner
        with mock.patch.object(runner.subprocess,'run',return_value=mock.Mock(returncode=1,stderr='invalid\n',stdout='')):
            runner.partial_audit(self.root)
        self.assertEqual((self.root/'audit.partial.log').read_text(),'invalid\n')
        self.assertFalse((self.root/'audit.partial.json').exists())


if __name__=='__main__':unittest.main()
