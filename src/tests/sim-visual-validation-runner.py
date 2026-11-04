#!/usr/bin/env python3
"""CPU-only lifecycle tests for the frozen validation suite runner."""
import importlib.util
import tempfile
import json
import shutil
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('runner',ROOT/'flex/tests/run-sim-visual-validation.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)


class MatrixPreflightTest(unittest.TestCase):
    def test_wrong_family_rejected_against_generator(self):
        base=ROOT/'build/flex/sim/levels-v2/pitch82';pilot=base/'physical-visual-stop-pair-v1';matrix=base/'visual-stop-validation-inputs-v3'
        if not (matrix/'conditions.json').is_file() or not (pilot/'inputs.json').is_file():self.skipTest('frozen pilot artifacts unavailable')
        data=json.loads((matrix/'conditions.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)
            for condition in data['conditions']:(target/condition['name']).symlink_to(matrix/condition['name'],target_is_directory=True)
            data['conditions'][0]['family']='periodic'
            (target/'conditions.json').write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'transformation differs'):runner.check_matrix(pilot.resolve(),target)


class RunnerTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.patch(runner,'LOCK',self.root/'lock');self.patch(runner,'ROOT',self.root)
        self.conditions=[{'name':f'case-{i}','caseSHA256':'a','environmentSHA256':'b'} for i in range(12)]
        self.paths={key:str(self.root/key) for key in ('client','simulator','model','asset','config','runtime')}
        receipt={'paths':self.paths,'files':{}}
        self.patch(runner,'check_matrix',lambda *a:(receipt,{'conditions':self.conditions}))
        self.patch(runner,'pin_files',lambda *a:{'hash':'stable'})
        self.patch(runner.shutil,'disk_usage',lambda p:SimpleNamespace(free=20*1024**3))
        self.patch(runner.hidden.rescan,'verify_model',lambda p:None)
        self.patch(runner.hidden.supervisor,'worker_snapshot',lambda env:{'launchPath':'/usr/bin/python3','executable':str(Path('/usr/bin/python3').resolve())})
        self.patch(runner.hidden.supervisor,'verify_worker',lambda x:None)
        self.status={'signal':None,'timedOut':False,'clientExit':0,'remainingWorkersTerminated':False};self.calls=[]
        def supervise(command, monitor, env, wall):self.calls.append((command,env,wall));return dict(self.status)
        self.patch(runner.hidden,'supervise',supervise)
        self.patch(runner.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=0,stdout='{}\n',stderr=''))

    def patch(self,obj,name,value):
        p=mock.patch.object(obj,name,value);p.start();self.addCleanup(p.stop)

    def test_same_binary_24_bounded_arms_and_no_overwrite(self):
        out=self.root/'out';runner.run(self.root/'pilot',self.root/'matrix',out)
        self.assertEqual(len(self.calls),24);self.assertEqual({c[0][0] for c in self.calls},{self.paths['client']})
        self.assertTrue(all(c[2]==300 for c in self.calls))
        for left,right in zip(self.calls[::2],self.calls[1::2]):
            self.assertEqual(left[0][:5],right[0][:5]);a=dict(left[1]);b=dict(right[1]);self.assertEqual(a.pop('PUPPYBOT_SIM_VISUAL_STOP'),'0');self.assertEqual(b.pop('PUPPYBOT_SIM_VISUAL_STOP'),'1');self.assertEqual(a,b)
        self.assertTrue((out/'audit.json').exists())
        with self.assertRaises(FileExistsError):runner.run(self.root/'pilot',self.root/'matrix',out)

    def test_failed_watchdog_stops_and_preserves_partial_audit(self):
        self.status['timedOut']=True;out=self.root/'failed'
        with self.assertRaisesRegex(RuntimeError,'partial evidence retained'):runner.run(self.root/'pilot',self.root/'matrix',out)
        self.assertEqual(len(self.calls),1);self.assertTrue((out/'audit.partial.json').exists());self.assertFalse((out/'audit.json').exists())

    def test_pilot_audit_and_build_receipt_are_bound(self):
        audit_path=self.root/'flex/tests/audit-sim-visual-stop-pair.py';stop_path=self.root/'flex/tests/audit-sim-visual-stop.py'
        audit_path.parent.mkdir(parents=True);audit_path.write_text('audit');stop_path.write_text('stop')
        helpers=[self.root/'flex/tests'/name for name in ('run-physical-hidden-trial.py','run-physical-rescan-trial.py','run-physical-hybrid-trial.py')]
        for helper in helpers:helper.write_text('helper')
        pilot=self.root/'pilot';receipt=pilot/'inputs/visual-build/build.json';receipt.parent.mkdir(parents=True);receipt.write_text('receipt')
        result={'status':'diagnostic_only','commonActorBytesMatch':True,'visualStop':{'reason':2}}
        (pilot/'audit.json').write_text(json.dumps(result))
        pins={str(p):runner.sha(p) for p in (audit_path,stop_path,receipt,*helpers)}
        with mock.patch.object(runner,'load',return_value=SimpleNamespace(audit=lambda _:result)):
            runner.verify_pilot_audit(pilot,pins)
            (pilot/'audit.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'pilot audit missing'):runner.verify_pilot_audit(pilot,pins)
            (pilot/'audit.json').write_text(json.dumps(result));helpers[0].write_text('changed')
            with self.assertRaisesRegex(ValueError,'pilot auditor or build receipt changed'):runner.verify_pilot_audit(pilot,pins)
            helpers[0].write_text('helper');receipt.write_text('changed')
            with self.assertRaisesRegex(ValueError,'build receipt changed'):runner.verify_pilot_audit(pilot,pins)

    def test_low_disk_never_creates_output(self):
        with mock.patch.object(runner.shutil,'disk_usage',return_value=SimpleNamespace(free=0)):
            out=self.root/'low'
            with self.assertRaisesRegex(ValueError,'insufficient space'):runner.run(self.root/'pilot',self.root/'matrix',out)
            self.assertFalse(out.exists());self.assertFalse(self.calls)


if __name__=='__main__':unittest.main()
