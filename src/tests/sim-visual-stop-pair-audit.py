#!/usr/bin/env python3
"""CPU fixture tests for the post-run paired simulated-stop audit."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('pair', ROOT / 'flex/tests/audit-sim-visual-stop-pair.py')
pair = importlib.util.module_from_spec(spec); spec.loader.exec_module(pair)


class PairTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup); self.root = Path(self.temp.name)
        self.paths = {k: str(self.root/k) for k in ('client','simulator','case','environment','asset','model','config','runtime')}
        model = Path(self.paths['model']); model.mkdir(); (model/'kernels').mkdir()
        for key, path in self.paths.items():
            if key != 'model': Path(path).write_bytes(key.encode())
        (model/'policy').write_bytes(b'policy'); (model/'weights.bin').write_bytes(b'weights')
        kernels = {}
        for i in range(5):
            path = model/'kernels'/f'k{i}'; path.write_bytes(str(i).encode()); kernels[path.name] = pair.stop_audit.sha(path)
        self.json(model/'receipt.json', {'kernels': kernels, 'binarySHA256': pair.stop_audit.sha(model/'policy'), 'weightsSHA256': pair.stop_audit.sha(model/'weights.bin')})
        files = {str(p): pair.stop_audit.sha(p) for p in self.root.rglob('*') if p.is_file()}
        self.manifest = {'schema': 'puppybot.sim-visual-stop-pair.v1','files':files,'paths':self.paths,'navigationLimit':90,'wallSecondsPerArm':300}
        self.json(self.root/'inputs.json', self.manifest)
        declared = {'simulatorSHA256':files[self.paths['simulator']],'caseSHA256':files[self.paths['case']],
                    'environmentSHA256':files[self.paths['environment']],'weightsSHA256':files[str(model/'weights.bin')],
                    'policySHA256':files[str(model/'policy')],'receiptSHA256':files[str(model/'receipt.json')],
                    'robotAssetSHA256':files[self.paths['asset']], 'cameraPitch':82,'contactFeedback':'unavailable-forced-zero'}
        for arm, count in (('disabled',12), ('enabled',9)):
            base=self.root/arm; run=base/'run'; (run/'actors').mkdir(parents=True)
            self.json(base/'monitor/supervisor-result.json', {'clientExit':0,'timedOut':False,'signal':None,'remainingWorkersTerminated':False})
            self.json(base/'command.json', [self.paths[k] for k in ('client','simulator','model','case','environment')]+[str(run),'--allow-zero-contact'])
            self.json(base/'environment.json', {'PUPPYBOT_SIM_VISUAL_STOP':'1' if arm=='enabled' else '0','PUPPYBOT_PHYSICAL_NAV_LIMIT':'90','PUPPYBOT_PHYSICAL_POLL_LIMIT':'1499','SDL_VIDEODRIVER':'offscreen'})
            (run/'trace.jsonl').write_text(''.join(json.dumps({'totalSteps':i,'pose':[0,0,0]})+'\n' for i in range(91)))
            self.json(run/'result.json', {'visualStopEnabled':arm=='enabled','stopCommandAcknowledged':True,'handoff':False,'traceSHA256':pair.stop_audit.sha(run/'trace.jsonl'),'stoppedRescanEnabled':False,'visualStopReason':2 if arm=='enabled' else 0,'policyActions':count})
            self.json(run/'inputs.json', declared)
            (run/'physical-agent.jsonl').write_text(''.join(json.dumps({'sequence':i})+'\n' for i in range(1,count+3)))
            for seq in range(1,count+1):
                for ext in ('rgb','feedback','hidden','action'):
                    (run/'actors'/f'actor-{seq}.{ext}').write_bytes(f'{seq}-{ext}'.encode())
        patch = mock.patch.object(pair.stop_audit, 'audit', return_value={'startTick':0,'endTick':90,'reason':2}); patch.start(); self.addCleanup(patch.stop)
        patch = mock.patch.object(pair, 'load_hidden_auditor', return_value=SimpleNamespace(check_actor_inputs=lambda *args: None)); patch.start(); self.addCleanup(patch.stop)

    @staticmethod
    def json(path, value):
        path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(value))

    def test_matched_and_pose_truth(self):
        report=pair.audit(self.root); self.assertTrue(report['commonActorBytesMatch']); self.assertEqual(report['comparedActorSteps'],9)
        self.assertTrue(report['simulatorTruthAfterRun']['withinOneCmAndTwoDegrees'])

    def test_unpinned_binary_rejected(self):
        del self.manifest['files'][self.paths['client']]; self.json(self.root/'inputs.json', self.manifest)
        with self.assertRaisesRegex(ValueError,'required pair input pin'): pair.audit(self.root)

    def test_short_or_zero_baseline_rejected(self):
        p=self.root/'disabled/run/result.json'; result=json.loads(p.read_text())
        for count in (0,8):
            result['policyActions']=count; self.json(p,result)
            with self.assertRaisesRegex(ValueError,'baseline does not cover'): pair.audit(self.root)

    def test_environment_and_prefix_difference(self):
        p=self.root/'enabled/environment.json'; env=json.loads(p.read_text()); env['PATH']='/other'; self.json(p,env)
        with self.assertRaisesRegex(ValueError,'paired environments differ'): pair.audit(self.root)
        env.pop('PATH'); self.json(p,env)
        (self.root/'enabled/run/actors/actor-2.action').write_bytes(b'different')
        self.assertFalse(pair.audit(self.root)['commonActorBytesMatch'])

    def test_missing_or_nonfinite_truth_rejected(self):
        p=self.root/'enabled/run/trace.jsonl'; rows=[json.loads(x) for x in p.read_text().splitlines()]; rows[50]['pose'][0]=float('nan')
        p.write_text(''.join(json.dumps(x)+'\n' for x in rows)); result=self.root/'enabled/run/result.json'; data=json.loads(result.read_text());data['traceSHA256']=pair.stop_audit.sha(p);self.json(result,data)
        with self.assertRaisesRegex(ValueError,'invalid simulator truth'): pair.audit(self.root)


if __name__ == '__main__': unittest.main()
