#!/usr/bin/env python3
"""CPU-only v4 launcher, smoke and evidence-boundary regression tests."""
import importlib.util
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT=Path(__file__).resolve().parents[2]


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);obj=importlib.util.module_from_spec(spec);spec.loader.exec_module(obj);return obj


v4=load('v4',ROOT/'flex/tests/run-sim-visual-validation-v4.py')
smoke=load('smoke',ROOT/'flex/tests/sim-visual-v4-smoke.py')
audit_v4=load('audit_v4',ROOT/'flex/tests/audit-sim-visual-validation-v4.py')
BASE=ROOT/'build/flex/sim/levels-v2/pitch82';PILOT=BASE/'physical-visual-stop-pair-v1';MATRIX=BASE/'visual-stop-validation-inputs-v4'


class PreflightTest(unittest.TestCase):
    def test_real_pilot_v3_metadata_and_12_cpu_resets(self):
        if not (PILOT/'inputs.json').is_file() or not (MATRIX/'conditions.json').is_file():self.fail('required frozen evidence missing')
        _,data=v4.check_matrix(PILOT,MATRIX);self.assertEqual(len(data['conditions']),12)

    def test_smoke_gate_requires_matching_status_and_pinned_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);evidence=root/'report.json';evidence.write_text('{}')
            manifest={'smoke':str(root),'pilot':str(root/'pilot')};files={str(evidence):smoke.sha(evidence)}
            stub=SimpleNamespace(audit=lambda *args:{'status':'simulated_rendered_startup_observed'},evidence_files=lambda *args:[evidence])
            audit_v4.verify_smoke_gate(manifest,files,root/'matrix',stub)
            evidence.write_text('changed')
            with self.assertRaisesRegex(ValueError,'not pinned'):audit_v4.verify_smoke_gate(manifest,files,root/'matrix',stub)
            stub.audit=lambda *args:{'status':'unverified'}
            with self.assertRaisesRegex(ValueError,'not verified'):audit_v4.verify_smoke_gate(manifest,files,root/'matrix',stub)

    def test_cli_scaffolds_are_hard_disabled(self):
        for script in ('run-sim-visual-validation-v4.py','sim-visual-v4-smoke.py'):
            done=subprocess.run([sys.executable,'-I',str(ROOT/'flex/tests'/script)],capture_output=True,text=True,timeout=10)
            self.assertNotEqual(done.returncode,0);self.assertIn('Disabled pending independent review',done.stderr)


class LaunchTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.conditions=[{'name':f'case-{i}'} for i in range(12)];self.paths={key:str(self.root/key) for key in ('client','simulator','model','asset','config','runtime')}
        self.receipt={'paths':self.paths};self.patch(v4,'ROOT',self.root);self.patch(v4,'LOCK',self.root/'lock')
        self.patch(v4,'check_matrix',lambda *args:(self.receipt,{'conditions':self.conditions}));self.patch(v4,'pin_files',lambda *args:{'fixed':'hash'})
        self.patch(v4.shutil,'disk_usage',lambda path:SimpleNamespace(free=20*1024**3))
        self.patch(v4.base.hidden.supervisor,'worker_snapshot',lambda env:{'launchPath':'/usr/bin/python3','executable':str(Path('/usr/bin/python3').resolve())})
        self.patch(v4.base.hidden.supervisor,'verify_worker',lambda worker:None);self.patch(v4.base.hidden.rescan,'verify_model',lambda path:None)
        self.calls=[];self.status={'signal':None,'timedOut':False,'clientExit':0,'remainingWorkersTerminated':False}
        def supervise(command,monitor,env,wall):self.calls.append((command,env,wall));return dict(self.status)
        self.patch(v4.base.hidden,'supervise',supervise)
        self.patch(v4.subprocess,'run',lambda *args,**kwargs:SimpleNamespace(returncode=0,stdout='{}\n',stderr=''))
        self.smoke_file=self.root/'smoke-evidence';self.smoke_file.write_text('evidence')
        self.smoke=SimpleNamespace(audit=lambda *args:{'status':'simulated_rendered_startup_observed'},evidence_files=lambda *_:[self.smoke_file])
        self.original_load=v4.load;self.patch(v4,'load',lambda name,path:self.smoke if name=='v4_smoke' else self.original_load(name,path))

    def patch(self,obj,name,value):
        patch=mock.patch.object(obj,name,value);patch.start();self.addCleanup(patch.stop)

    def test_same_binary_24_bounded_arms_and_no_overwrite(self):
        output=self.root/'suite';v4.run(self.root/'pilot',self.root/'matrix',self.root/'smoke',output)
        self.assertEqual(len(self.calls),24);self.assertEqual({x[0][0] for x in self.calls},{self.paths['client']});self.assertTrue(all(x[2]==300 for x in self.calls))
        for left,right in zip(self.calls[::2],self.calls[1::2]):
            self.assertEqual(left[0][:5],right[0][:5]);a=dict(left[1]);b=dict(right[1]);self.assertEqual(a.pop('PUPPYBOT_SIM_VISUAL_STOP'),'0');self.assertEqual(b.pop('PUPPYBOT_SIM_VISUAL_STOP'),'1');self.assertEqual(a,b)
        self.assertTrue((output/'audit.json').exists())
        with self.assertRaises(FileExistsError):v4.run(self.root/'pilot',self.root/'matrix',self.root/'smoke',output)

    def test_unverified_smoke_and_timeout_fail_closed(self):
        self.smoke.audit=lambda *args:{'status':'unverified'};output=self.root/'missing-smoke'
        with self.assertRaisesRegex(ValueError,'smoke did not establish'):v4.run(self.root/'pilot',self.root/'matrix',self.root/'smoke',output)
        self.assertFalse(output.exists());self.assertEqual(self.calls,[])
        self.smoke.audit=lambda *args:{'status':'simulated_rendered_startup_observed'};self.status['timedOut']=True;output=self.root/'failed'
        with self.assertRaisesRegex(RuntimeError,'partial evidence retained'):v4.run(self.root/'pilot',self.root/'matrix',self.root/'smoke',output)
        self.assertEqual(len(self.calls),1);self.assertTrue((output/'audit.partial.json').exists());self.assertFalse((output/'audit.json').exists())

    def test_smoke_is_one_action_one_poll_and_120s(self):
        self.patch(smoke,'ROOT',self.root);self.patch(smoke,'LOCK',self.root/'smoke-lock')
        self.patch(smoke.v4,'check_matrix',lambda *args:(self.receipt,{'conditions':self.conditions}));self.patch(smoke.v4,'pin_files',lambda *args:{'fixed':'hash'})
        self.patch(smoke.v4.base.hidden.supervisor,'worker_snapshot',lambda env:{'launchPath':'/usr/bin/python3','executable':str(Path('/usr/bin/python3').resolve())})
        self.patch(smoke.v4.base.hidden.supervisor,'verify_worker',lambda worker:None);self.patch(smoke.v4.base.hidden.rescan,'verify_model',lambda path:None)
        self.patch(smoke.v4.base.hidden,'supervise',lambda command,monitor,env,wall:(self.calls.append((command,env,wall)) or dict(self.status)))
        self.patch(smoke.shutil,'disk_usage',lambda path:SimpleNamespace(free=20*1024**3));self.patch(smoke,'audit',lambda *args:{'status':'simulated_rendered_startup_observed'})
        out=self.root/'smoke-output';smoke.run(self.root/'pilot',self.root/'matrix',out)
        self.assertEqual(len(self.calls),1);command,env,wall=self.calls[0]
        self.assertEqual((env['PUPPYBOT_PHYSICAL_NAV_LIMIT'],env['PUPPYBOT_PHYSICAL_POLL_LIMIT'],env['PUPPYBOT_SIM_VISUAL_STOP'],wall),('1','1','0',120))
        self.assertTrue(command[3].endswith('/room-13/case.json'));self.assertTrue((out/'report.json').exists())


class SmokeAuditTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.pilot=self.root/'pilot';self.matrix=self.root/'matrix';self.output=self.root/'smoke';self.output.mkdir()
        scene=self.matrix/'room-13';scene.mkdir(parents=True);case=scene/'case.json';case.write_text('{}')
        environment=scene/'environment.bin';header=bytearray(256);header[:8]=b'PBENV001';struct.pack_into('<3d',header,96,0,0,0);environment.write_bytes(header)
        model=self.root/'model';model.mkdir();(model/'kernels').mkdir()
        for name in ('policy','weights.bin'):(model/name).write_text(name)
        kernels={}
        for i in range(5):
            path=model/'kernels'/f'k{i}';path.write_text(str(i));kernels[path.name]=smoke.sha(path)
        (model/'receipt.json').write_text(json.dumps({'binarySHA256':smoke.sha(model/'policy'),'weightsSHA256':smoke.sha(model/'weights.bin'),'kernels':kernels}))
        self.paths={key:str(self.root/key) for key in ('client','simulator','asset','config','runtime')};self.paths['model']=str(model)
        for key,path in self.paths.items():
            if key!='model':Path(path).write_text(key)
        pins={str(path):smoke.sha(path) for path in (case,environment,model/'policy',model/'weights.bin',model/'receipt.json',*(Path(self.paths[k]) for k in ('client','simulator','asset','config','runtime')))}
        for path in (model/'kernels').iterdir():pins[str(path)]=smoke.sha(path)
        self.write(self.output/'worker-inputs.json',{'launchPath':'/usr/bin/python3','executable':str(Path('/usr/bin/python3').resolve())})
        self.patch(smoke.v4.base.hidden.supervisor,'verify_worker',lambda worker:None)
        self.receipt={'paths':self.paths};self.patch(smoke.v4,'check_matrix',lambda *args:(self.receipt,{'conditions':[]}));self.patch(smoke.v4,'pin_files',lambda *args:pins)
        self.write(self.output/'inputs.json',{'schema':'puppybot.visual-v4-smoke.v1','pilot':str(self.pilot),'matrix':str(self.matrix),'paths':self.paths,'case':'room-13','wallSeconds':120,'home':'/tmp','files':pins})
        run=self.output/'run';(run/'actors').mkdir(parents=True);(self.output/'monitor').mkdir()
        self.write(self.output/'command.json',[self.paths['client'],self.paths['simulator'],self.paths['model'],str(case),str(environment),str(run),'--allow-zero-contact'])
        self.write(self.output/'environment.json',{'PATH':'/usr/bin:/bin','HOME':'/tmp','SDL_VIDEODRIVER':'offscreen','LD_LIBRARY_PATH':str(Path(self.paths['runtime']).parent),'PUPPYBOT_PHYSICAL_NAV_LIMIT':'1','PUPPYBOT_PHYSICAL_POLL_LIMIT':'1','PUPPYBOT_SIM_VISUAL_STOP':'0'})
        self.write(self.output/'monitor/supervisor-result.json',{'clientExit':0,'timedOut':False,'signal':None,'remainingWorkersTerminated':False,'processGroup':123})
        (run/'trace.jsonl').write_text(''.join(json.dumps({'totalSteps':tick,'pose':[0,0,0]})+'\n' for tick in (100,110)))
        self.write(run/'result.json',{'policyActions':1,'handoff':False,'navigationActionLimit':1,'collectorPollLimit':1,'visualStopEnabled':False,'stoppedRescanEnabled':False,'stopCommandAcknowledged':True,'outcome':'unverified','traceSHA256':smoke.sha(run/'trace.jsonl')})
        self.write(run/'inputs.json',{'simulatorSHA256':pins[self.paths['simulator']],'caseSHA256':pins[str(case)],'environmentSHA256':pins[str(environment)],'weightsSHA256':pins[str(model/'weights.bin')],'policySHA256':pins[str(model/'policy')],'receiptSHA256':pins[str(model/'receipt.json')],'robotAssetSHA256':pins[self.paths['asset']]})
        def row(seq,tick,owner,ack,valid,drive):return {'schema':'puppybot.physical-agent.v1','sequence':seq,'step':tick,'timeMs':tick*20,'owner':owner,'ack':ack,'imageValid':valid,'rgbDetections':0 if valid else None,'driveCommand':drive,'jointTicks':[1,2,3,4],'totalSteps':tick,'cameraFrame':tick if valid else -1,'cameraDriving':valid,'cameraStill':valid}
        self.rows=[row(1,100,0,0,True,[0,0,90]),row(2,110,0,1,True,[12,12,90]),row(3,110,2,7,False,[0,0,90])];self.save_rows()
        (run/'actors/actor-1.rgb').write_bytes(bytes(21168));(run/'actors/actor-1.feedback').write_bytes(bytes(28));(run/'actors/actor-1.hidden').write_bytes(bytes(512));(run/'actors/actor-1.action').write_bytes(struct.pack('<2f',0,.2))

    def patch(self,obj,name,value):
        patch=mock.patch.object(obj,name,value);patch.start();self.addCleanup(patch.stop)

    @staticmethod
    def write(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))

    def save_rows(self):
        (self.output/'run/physical-agent.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in self.rows))

    def test_real_v4_auditor_censors_incomplete_and_mismatched_pairs_and_binds_smoke(self):
        # Real smoke audit and real v4 aggregation; fake only the expensive
        # frozen matrix verification and the unrelated per-run trace checks.
        report=smoke.audit(self.output,self.pilot,self.matrix);self.write(self.output/'report.json',report)
        for path in (self.output/'monitor/client.log',self.output/'run/native.log',self.output/'run/policy.log'):path.write_text('')
        conditions=[]
        for family in audit_v4.generator.FAMILIES:
            for heading in audit_v4.generator.HEADINGS:conditions.append({'name':f'{family}-yaw-{heading:+.2f}','family':family})
        for layout in audit_v4.generator.ROOM_LAYOUTS:conditions.append({'name':f'room-{layout}','family':'natural-room'})
        for row in conditions:
            scene=self.matrix/row['name'];scene.mkdir(parents=True,exist_ok=True)
            for filename,key in (('case.json','caseSHA256'),('environment.bin','environmentSHA256')):
                path=scene/filename
                if not path.exists():path.write_bytes(filename.encode())
                row[key]=smoke.sha(path)
        self.write(self.matrix/'conditions.json',{'conditions':conditions})
        files={str(path):smoke.sha(path) for path in smoke.evidence_files(self.output)}
        for row in conditions:
            for filename in ('case.json','environment.bin'):
                path=self.matrix/row['name']/filename;files[str(path)]=smoke.sha(path)
        files[str(self.matrix/'conditions.json')]=smoke.sha(self.matrix/'conditions.json')
        for key in ('client','simulator','asset','config','runtime'):
            files[self.paths[key]]=smoke.sha(Path(self.paths[key]))
        model=Path(self.paths['model'])
        for path in [model/'policy',model/'weights.bin',model/'receipt.json',*(model/'kernels').iterdir()]:files[str(path)]=smoke.sha(path)
        suite=self.root/'suite';suite.mkdir();self.write(suite/'inputs.json',{'schema':'puppybot.sim-visual-validation.v1','version':'v4','conditions':conditions,'files':files,'paths':self.paths,'pilot':str(self.pilot),'matrix':str(self.matrix),'smoke':str(self.output),'navigationLimit':90,'wallSecondsPerArm':300,'home':'/tmp'})
        fake_runner=SimpleNamespace(check_matrix=lambda *args:(self.receipt,{'conditions':conditions}))
        original_load=audit_v4.load
        def loader(name,path):
            if name=='suite_runner':return fake_runner
            if name=='v4_smoke':return smoke
            return original_load(name,path)
        with mock.patch.object(audit_v4,'load',side_effect=loader):
            result=audit_v4.audit(suite)
            self.assertEqual(result['metrics']['censoredCases'],12);self.assertEqual(result['metrics']['completedPairs'],0)
            first=conditions[0];base=suite/'cases'/first['name']
            self.write(base/'disabled/monitor/supervisor-result.json',{'clientExit':-9,'timedOut':True,'signal':None,'remainingWorkersTerminated':False})
            result=audit_v4.audit(suite)
            self.assertEqual(result['episodes'][0]['censoring'][0]['reason'],'supervisor_failure_or_cleanup')
            # Both synthetic arms are nominally complete but their actor RGB
            # differs. They must remain censored and contribute no miss count.
            model=Path(self.paths['model']);client={'simulatorSHA256':files[self.paths['simulator']],'caseSHA256':first['caseSHA256'],'environmentSHA256':first['environmentSHA256'],'weightsSHA256':files[str(model/'weights.bin')],'policySHA256':files[str(model/'policy')],'receiptSHA256':files[str(model/'receipt.json')],'robotAssetSHA256':files[self.paths['asset']],'cameraPitch':82,'contactFeedback':'unavailable-forced-zero'}
            rows=[{'sequence':1,'rgbDetections':0,'totalSteps':100},{'sequence':2,'owner':2,'ack':7,'driveCommand':[0,0,90]}]
            for arm in ('disabled','enabled'):
                parent=base/arm;run=parent/'run';actors=run/'actors';actors.mkdir(parents=True)
                self.write(parent/'monitor/supervisor-result.json',{'clientExit':0,'timedOut':False,'signal':None,'remainingWorkersTerminated':False})
                self.write(parent/'command.json',[self.paths['client'],self.paths['simulator'],self.paths['model'],str(self.matrix/first['name']/'case.json'),str(self.matrix/first['name']/'environment.bin'),str(run),'--allow-zero-contact'])
                self.write(parent/'environment.json',{'PATH':'/usr/bin:/bin','HOME':'/tmp','SDL_VIDEODRIVER':'offscreen','LD_LIBRARY_PATH':str(Path(self.paths['runtime']).parent),'PUPPYBOT_PHYSICAL_NAV_LIMIT':'90','PUPPYBOT_PHYSICAL_POLL_LIMIT':'1499','PUPPYBOT_SIM_VISUAL_STOP':'1' if arm=='enabled' else '0'})
                (run/'trace.jsonl').write_text('trace');self.write(run/'inputs.json',client)
                self.write(run/'result.json',{'policyActions':90,'handoff':False,'stoppedRescanEnabled':False,'visualStopEnabled':arm=='enabled','visualStopReason':0,'stopCommandAcknowledged':True,'outcome':'unverified','traceSHA256':smoke.sha(run/'trace.jsonl')})
                (run/'physical-agent.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in rows))
                for seq in range(1,91):
                    for ext in ('rgb','feedback','hidden','action'):(actors/f'actor-{seq}.{ext}').write_bytes((arm if ext=='rgb' else 'same').encode())
            fake_window={'truth':'stationary','visualCode':0,'horizontalPeriodMAD':1}
            with mock.patch.object(audit_v4,'baseline_windows',return_value=(rows,[fake_window],{100:[0,0,0]})),mock.patch.object(audit_v4,'truth_trace',return_value={100:[0,0,0]}),mock.patch.object(audit_v4,'require_spawn_match'),mock.patch.object(audit_v4,'verify_enabled_no_stop',return_value=list(range(1,91))):
                result=audit_v4.audit(suite)
            self.assertEqual(result['metrics']['casesCensoredForPrefixMismatch'],1)
            self.assertEqual(result['metrics']['casesWithStationaryWindowsWithoutSuspicion'],0)
            (self.output/'report.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'pinned suite input changed'):audit_v4.audit(suite)
            self.write(self.output/'report.json',report);(self.output/'monitor/client.log').unlink()
            with self.assertRaises(OSError):audit_v4.audit(suite)

    def test_smoke_audit_and_adversarial_protocol(self):
        report=smoke.audit(self.output,self.pilot,self.matrix);self.assertEqual(report['status'],'simulated_rendered_startup_observed')
        self.rows[1]['driveCommand']=[0,0,90];self.save_rows()
        with self.assertRaisesRegex(ValueError,'drive echo'):smoke.audit(self.output,self.pilot,self.matrix)
        self.rows[1]['driveCommand']=[12,12,90];self.rows[-1]['ack']=6;self.save_rows()
        with self.assertRaisesRegex(ValueError,'final stop'):smoke.audit(self.output,self.pilot,self.matrix)

    def test_smoke_rejects_timeout_bad_spawn_and_report_tamper(self):
        status=self.output/'monitor/supervisor-result.json';value=json.loads(status.read_text());value['timedOut']=True;self.write(status,value)
        with self.assertRaisesRegex(ValueError,'supervisor'):smoke.audit(self.output,self.pilot,self.matrix)
        value['timedOut']=False;self.write(status,value)
        trace=self.output/'run/trace.jsonl';trace.write_text(json.dumps({'totalSteps':100,'pose':[1,0,0]})+'\n'+json.dumps({'totalSteps':110,'pose':[1,0,0]})+'\n')
        result=self.output/'run/result.json';value=json.loads(result.read_text());value['traceSHA256']=smoke.sha(trace);self.write(result,value)
        with self.assertRaisesRegex(ValueError,'initial pose differs'):smoke.audit(self.output,self.pilot,self.matrix)
        trace.write_text(''.join(json.dumps({'totalSteps':tick,'pose':[0,0,0]})+'\n' for tick in (100,110)));value['traceSHA256']=smoke.sha(trace);self.write(result,value)
        self.write(self.output/'report.json',{'status':'fabricated'})
        with self.assertRaisesRegex(ValueError,'report changed'):smoke.audit(self.output,self.pilot,self.matrix)


if __name__=='__main__':unittest.main()
