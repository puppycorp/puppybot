#!/usr/bin/env python3
"""Synthetic whole-trial audit and censoring checks, without GPU."""
import hashlib
import importlib.util
import json
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('search_fixture',HERE/'fixture_support.py')
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
spec=importlib.util.spec_from_file_location('trial_audit',HERE/'audit.py')
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)


class TrialAuditTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.case=self.root/'case.json';self.case.write_text('{}')
        self.case_hash=hashlib.sha256(self.case.read_bytes()).hexdigest()
        self.build=self.root/'build';self.model=self.root/'model';self.environment=self.root/'environment.bin'
        self.environment.write_bytes(b'PBENV001'+bytes(112))
        files={str(self.case):self.case_hash,str(self.environment):'environment',str(audit.hidden.ASSET):'asset'}
        files.update({str(self.build/name):name for name in ('simulator','baseline-simulator')})
        files.update({str(self.model/name):name for name in ('policy','weights.bin','receipt.json')})
        fixture.write_json(self.root/'inputs.json',{'schema':'puppybot.physical-search-fallback-trial.v1','navigationLimit':90,'collectorPollLimit':1499,'case':str(self.case),'environment':str(self.environment),'build':str(self.build),'model':str(self.model),'files':files})
        self.protocols={}
        for arm,mode in [('baseline','baseline'),('candidate-disabled','baseline'),('candidate-search','search')]:
            run=self.root/arm/'run';fixture.build_protocol(run,mode)
            client=json.loads((run/'inputs.json').read_text());client.update({'simulatorSHA256':'baseline-simulator' if arm=='baseline' else 'simulator','caseSHA256':self.case_hash,'environmentSHA256':'environment','weightsSHA256':'weights.bin','policySHA256':'policy','receiptSHA256':'receipt.json','robotAssetSHA256':'asset','cameraPitch':82,'contactFeedback':'unavailable-forced-zero'});fixture.write_json(run/'inputs.json',client)
            rows=audit.rows(run/'physical-agent.jsonl');trace=[{'step':rows[0]['step'],'pose':[0,0,0],'case':{'objects':[{'id':'brick'}],'container':{'position':[1,2,0]}}},{'step':rows[-1]['step'],'pose':[0,0,0],'case':{'objects':[{'id':'brick'}],'container':{'position':[1,2,0]}}}]
            (run/'trace.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in trace))
            result=json.loads((run/'result.json').read_text());result['traceSHA256']=audit.sha(run/'trace.jsonl');fixture.write_json(run/'result.json',result)
            self.protocols[arm]=audit.protocol(run,mode=='search')
            mon=run.parent/'monitor';mon.mkdir();fixture.write_json(mon/'supervisor-result.json',{'clientExit':0,'timedOut':False,'signal':None,'remainingWorkersTerminated':False,'processGroup':123})
        self.manip={'caseSHA256':self.case_hash,'captures':[],'releases':[]}
        self.runner=types.SimpleNamespace(check_manifest=lambda *x:None,check_invocation=lambda *x:None)

    def checked(self):
        completed=subprocess.CompletedProcess([],0,json.dumps(self.manip),'')
        with mock.patch.object(audit,'load',return_value=self.runner),mock.patch.object(audit.subprocess,'run',return_value=completed):
            return audit.audit(self.root)

    def test_matching_is_diagnostic_only_and_no_pickup_inferred(self):
        result=self.checked();self.assertTrue(result['comparisonEligible']);self.assertTrue(result['matchedSavedPrefix'])
        self.assertEqual(result['status'],'diagnostic_only');self.assertTrue(all(not a['manipulation']['captures'] for a in result['arms']))
        self.assertIn('no held-out',result['scope'])

    def test_missing_or_failed_arm_censored(self):
        path=self.root/'candidate-search/monitor/supervisor-result.json';path.unlink()
        result=self.checked();self.assertFalse(result['comparisonEligible']);self.assertEqual(result['censorReason'],'incomplete_arm');self.assertEqual(result['arms'][2]['reason'],'missing_supervisor')
        fixture.write_json(path,{'clientExit':1,'timedOut':True,'signal':None,'remainingWorkersTerminated':False,'processGroup':123})
        self.assertEqual(self.checked()['arms'][2]['reason'],'supervisor_failure')
        fixture.write_json(path,{'clientExit':0,'timedOut':False,'remainingWorkersTerminated':False,'processGroup':123})
        self.assertEqual(self.checked()['arms'][2]['reason'],'supervisor_failure')

    def test_preownership_capture_is_rejected(self):
        self.manip['captures']=[{'step':100}]
        with self.assertRaisesRegex(ValueError,'outside collector ownership'):self.checked()

    def test_actor_difference_censors(self):
        actor=self.root/'candidate-search/run/actors/actor-1.rgb';data=bytearray(actor.read_bytes());data[0]=1;actor.write_bytes(data)
        result=self.checked();self.assertFalse(result['comparisonEligible']);self.assertEqual(result['censorReason'],'saved_prefix_or_initial_truth_mismatch')

    def test_changed_input_during_audit_is_rejected(self):
        self.runner.check_manifest=mock.Mock(side_effect=[None,ValueError('changed during audit')])
        with self.assertRaisesRegex(ValueError,'changed during audit'):self.checked()
        self.assertEqual(self.runner.check_manifest.call_count,2)

    def test_identical_wrong_spawn_is_censored(self):
        for arm in audit.ARMS:
            run=self.root/arm/'run';path=run/'trace.jsonl';rows=audit.rows(path)
            for row in rows:row['pose'][0]=0.1
            path.write_text(''.join(json.dumps(row)+'\n' for row in rows))
            result=json.loads((run/'result.json').read_text());result['traceSHA256']=audit.sha(path);fixture.write_json(run/'result.json',result)
        report=self.checked();self.assertFalse(report['comparisonEligible'])
        self.assertTrue(all(a['reason']=='start_pose_differs_from_pinned_environment' for a in report['arms']))

    def test_denied_handoff_is_part_of_saved_prefix(self):
        # Exercise comparison independently of protocol validity: protocol's own
        # tests cover its validation, while this checks no rows are dropped.
        protocols={k:dict(v) for k,v in self.protocols.items()}
        p=protocols['candidate-search'];p['journal']=list(p['journal']);p['journal'].insert(1,{'ack':2,'sequence':2})
        def fake(run,enabled):return protocols[Path(run).parent.name]
        with mock.patch.object(audit,'protocol',side_effect=fake):result=self.checked()
        self.assertFalse(result['comparisonEligible']);self.assertEqual(result['censorReason'],'saved_prefix_or_initial_truth_mismatch')


if __name__=='__main__':unittest.main()
