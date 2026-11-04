#!/usr/bin/env python3
"""Synthetic fixed-plan, registration and runner fixtures; no GPU."""
import importlib.util
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('hys_runner_test',HERE/'runner.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class RunnerTest(unittest.TestCase):
    def test_fixed_matrix_and_exact_commands(self):
        design=m.plan.design();rows=design['conditions'];self.assertEqual(len(rows),12);self.assertEqual(design['arms'],['control','kick','kick-hysteresis'])
        self.assertEqual([r['seed'] for r in rows],list(range(6800200,6800212)))
        self.assertEqual([(r['layout'],r['variant']) for r in rows],[(layout,variant) for layout in (13,15,17) for variant in range(4,8)])
        for row in rows:
            commands=[m.command(row,arm) for arm in design['arms']]
            self.assertEqual(len({c[0] for c in commands}),1);self.assertEqual(commands[0][-1],'--steer-probe-control')
            self.assertEqual(commands[1][-1],'--steer-probe-enabled');self.assertEqual(commands[2][-2:],['--steer-probe-enabled','--steer-hysteresis'])
            self.assertTrue(all(c[c.index('--seed')+1]==str(row['seed']) and c[c.index('--scene')+1]==row['scene'] for c in commands))
        self.assertEqual(design['gate']['windowAppliedActions'],8);self.assertTrue(design['gate']['allSpeedValuesNonzero']);self.assertEqual(design['gate']['minimumAdjacentReversals'],6)

    def test_registration_history_includes_prior_kick(self):
        reg=m.registration
        self.assertIn(m.plan.P/'l5-steering-kick-diagnostic-v1',reg.HISTORY)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'source';p.write_text('x');calls=[]
            with mock.patch.object(reg.prepare,'verify',return_value={'build':'ok'}),mock.patch.object(reg.base.package,'verify'),mock.patch.object(reg,'source_paths',return_value=[p]),mock.patch.object(reg.old,'runtime_chain',return_value={}),mock.patch.object(reg.old,'scene_rows',return_value=[]),mock.patch.object(reg.old,'historical_inventory',side_effect=lambda **kw:(calls.append(kw) or {'records':1})):
                result=reg.current();self.assertEqual(result['status'],'frozen_before_play');self.assertIn(m.plan.P/'l5-steering-kick-diagnostic-v1',calls[0]['roots']);self.assertTrue(calls[0]['require_known'])
                self.assertIsNone(reg.current(include_history=False)['history']);self.assertEqual(len(calls),1)

    def test_history_and_scene_preflight_fail_closed(self):
        old=m.registration.old
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);prior=root/'prior';prior.mkdir();(prior/'result.json').write_text(json.dumps({'seed':6800201}))
            with self.assertRaisesRegex(ValueError,'overlaps'):old.historical_inventory((root,),(),require_known=False)
            (prior/'result.json').write_text(json.dumps({'seed':7000001}));self.assertEqual(old.historical_inventory((root,),(),require_known=False)['records'],1)
            scene=root/'scene';scene.mkdir();(scene/'case.json').write_text('{}')
            env=bytearray(728);env[:8]=b'PBENV001';struct.pack_into('<qqq',env,8,2,3,3);struct.pack_into('<3d',env,96,0.,.04,.35)
            for offset in (256,384):env[offset:offset+14]=b'Wall.partition';struct.pack_into('<d',env,offset+48,1.)
            (scene/'environment.bin').write_bytes(env);layout=scene/'layout.json'
            valid={'layoutId':13,'fit':True,'startRoom':0,'rooms':[[-3.,-3.,1.,3.],[1.,-3.,4.,3.]]}
            layout.write_text(json.dumps(valid));design={'conditions':[{'index':0,'layout':13,'variant':4,'seed':6800200,'scene':str(scene)}]}
            with mock.patch.object(m.plan,'design',return_value=design):
                self.assertEqual(old.scene_rows()[0]['spawn'],[0.,.04,.35])
                invalid=dict(valid,rooms=[[],[]]);layout.write_text(json.dumps(invalid))
                with self.assertRaisesRegex(ValueError,'room bounds'):old.scene_rows()
                layout.write_text(json.dumps(valid));(scene/'case.json').unlink();(scene/'case.json').symlink_to(layout)
                with self.assertRaisesRegex(ValueError,'symlink scene'):old.scene_rows()

    def test_no_overwrite_before_registration_or_spawn(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);out=root/'out';out.mkdir();(out/'sentinel').write_text('keep')
            with mock.patch.object(m.guard,'require_dedicated_process'),mock.patch.object(m.plan,'P',root),mock.patch.object(m.plan,'OUTPUT',out),mock.patch.object(m.registration,'verify') as verify:
                with self.assertRaises((FileExistsError,ValueError)):m.run()
                verify.assert_not_called()
            self.assertEqual((out/'sentinel').read_text(),'keep')

    def test_all_36_statuses_and_comparison_are_required(self):
        clean={'clientExit':0,'timedOut':False,'signal':None,'remainingWorkersTerminated':False,'processGroup':123}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);out=root/'out';out.mkdir();design=m.plan.design();scenes=[dict(row,files={'case.json':'case','environment.bin':'environment'}) for row in design['conditions']]
            manifest={'status':'frozen_before_play','design':design,'scenes':scenes,'files':{str(m.plan.MODEL/'weights.bin'):'weights'}}
            (out/'inputs.json').write_text(json.dumps(manifest))
            with mock.patch.object(m.plan,'OUTPUT',out),mock.patch.object(m.selection,'snapshot',return_value='weights'),mock.patch.object(m.audit,'saved_three',side_effect=lambda a,b,c,seed,expected:{'seed':seed}),mock.patch.object(m.audit,'report',side_effect=lambda rows:{'games':len(rows)}):
                for row in scenes:
                    for arm in design['arms']:
                        directory=out/'monitors'/str(row['index'])/arm;directory.mkdir(parents=True)
                        (directory/'invocation.json').write_text(json.dumps({'argv':m.command(row,arm),'environment':m.environment(),'wallSeconds':600}))
                        (directory/'supervisor-result.json').write_text(json.dumps(clean))
                self.assertEqual(m.reaudit(manifest),{'games':12})
                bad=out/'monitors/7/kick-hysteresis/supervisor-result.json';bad.write_text(json.dumps({k:v for k,v in clean.items() if k!='signal'}))
                with self.assertRaisesRegex(ValueError,'unclean'):m.reaudit(manifest)

    def test_failed_arm_saves_partial_censor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);out=root/'out';design=m.plan.design();manifest={'scenes':[dict(design['conditions'][0])]}
            def fail(*args):return {'clientExit':1,'signal':None,'timedOut':False,'remainingWorkersTerminated':False,'processGroup':123}
            with mock.patch.object(m.guard,'require_dedicated_process'),mock.patch.object(m.plan,'P',root),mock.patch.object(m.plan,'OUTPUT',out),mock.patch.object(m.base,'require_capacity'),mock.patch.object(m.registration,'verify',return_value=manifest),mock.patch.object(m,'live_check'),mock.patch.object(m.base.hidden,'supervise',side_effect=fail):
                with self.assertRaisesRegex(ValueError,'unclean'):m.run()
            partial=json.loads((out/'partial.json').read_text());self.assertEqual(partial['status'],'censored');self.assertEqual(partial['finished'],[]);self.assertFalse((out/'report.json').exists())


if __name__=='__main__':unittest.main()
