#!/usr/bin/env python3
"""CPU tests for multi-scene post-run labels and censored coverage."""
import importlib.util
import json
import math
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from types import SimpleNamespace

import numpy as np

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('audit',ROOT/'flex/tests/audit-sim-visual-validation.py')
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)


class ValidationAuditTest(unittest.TestCase):
    def test_asymmetric_initial_detection_and_zero_actions_are_censored(self):
        quiet=[{'rgbDetections':0}]; seen=[{'rgbDetections':1}]
        self.assertFalse(audit.initial_censor(quiet,quiet,9,9))
        self.assertTrue(audit.initial_censor(quiet,seen,9,9))
        self.assertTrue(audit.initial_censor(seen,quiet,9,9))
        self.assertTrue(audit.initial_censor(quiet,quiet,9,0))

    def test_trigger_image_mismatch_and_absence_cannot_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            left=Path(tmp)/'left';right=Path(tmp)/'right';left.mkdir();right.mkdir()
            for ext in ('rgb','feedback','hidden','action'):
                (left/f'actor-1.{ext}').write_bytes(b'same');(right/f'actor-1.{ext}').write_bytes(b'same')
            (left/'actor-2.rgb').write_bytes(b'trigger');(right/'visual-2.rgb').write_bytes(b'trigger')
            self.assertEqual(audit.compare_actor_prefix(left,right,[1],2),[])
            (right/'visual-2.rgb').write_bytes(b'changed')
            self.assertIn('trigger image differs',audit.compare_actor_prefix(left,right,[1],2))
            (left/'actor-2.rgb').unlink()
            self.assertIn('missing trigger image',audit.compare_actor_prefix(left,right,[1],2))

    def test_spawn_mismatch_and_environment_injection_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'environment';data=bytearray(256);data[:8]=b'PBENV001';struct.pack_into('<3d',data,96,0,0,.25);path.write_bytes(data)
            rows=[{'totalSteps':5}];good={5:[0,0,.25]};bad={5:[0,0,.5]}
            audit.require_spawn_match(path,rows,rows,good,good)
            with self.assertRaisesRegex(ValueError,'initial pose differs'):audit.require_spawn_match(path,rows,rows,good,bad)
        env={'PATH':'/usr/bin:/bin','HOME':'/test','SDL_VIDEODRIVER':'offscreen','LD_LIBRARY_PATH':'/runtime',
             'PUPPYBOT_PHYSICAL_NAV_LIMIT':'90','PUPPYBOT_PHYSICAL_POLL_LIMIT':'1499','PUPPYBOT_SIM_VISUAL_STOP':'1'}
        audit.require_arm_environment(env,'enabled','/test','/runtime/libamdhip64.so')
        with self.assertRaisesRegex(ValueError,'environment differs'):audit.require_arm_environment(dict(env,LD_PRELOAD='/evil'),'enabled','/test','/runtime/libamdhip64.so')

    def test_no_stop_missing_enabled_artifact_and_action_count_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp);actors=run/'actors';actors.mkdir()
            for ext in ('rgb','feedback','hidden','action'):(actors/f'actor-1.{ext}').write_bytes(b'x')
            (actors/'visual-1.rgb').write_bytes(b'x')
            with mock.patch.object(audit.hidden,'check_actor_inputs',return_value={}):
                self.assertEqual(audit.verify_enabled_no_stop(run,{'policyActions':1,'handoff':False},[]),[1])
                with self.assertRaisesRegex(ValueError,'count differs'):audit.verify_enabled_no_stop(run,{'policyActions':2,'handoff':False},[])
                (actors/'actor-1.action').unlink()
                with self.assertRaisesRegex(ValueError,'artifacts incomplete'):audit.verify_enabled_no_stop(run,{'policyActions':1,'handoff':False},[])

    def test_enabled_no_stop_must_not_ignore_a_qualifying_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp);actors=run/'actors';actors.mkdir();rows=[]
            for seq in range(1,11):
                rows.append({'totalSteps':seq*10})
                for ext in ('rgb','feedback','hidden'):(actors/f'actor-{seq}.{ext}').write_bytes(bytes(21168) if ext=='rgb' else b'x')
                (actors/f'actor-{seq}.action').write_bytes(struct.pack('<2f',0,.2));(actors/f'visual-{seq}.rgb').write_bytes(bytes(21168))
            with mock.patch.object(audit.hidden,'check_actor_inputs',return_value={}):
                with self.assertRaisesRegex(ValueError,'unreported qualifying visual stop'):audit.verify_enabled_no_stop(run,{'policyActions':10,'handoff':False},rows)

    def test_enabled_no_stop_checks_real_protocol_and_drive_echo(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp);actors=run/'actors';actors.mkdir()
            (actors/'actor-1.rgb').write_bytes(bytes(21168));(actors/'visual-1.rgb').write_bytes(bytes(21168))
            (actors/'actor-1.feedback').write_bytes(bytes(28));(actors/'actor-1.hidden').write_bytes(bytes(512))
            (actors/'actor-1.action').write_bytes(struct.pack('<2f',0,.2))
            def row(seq,tick,owner,ack,valid,drive):
                return {'schema':'puppybot.physical-agent.v1','sequence':seq,'step':tick,'timeMs':tick*20,'owner':owner,'ack':ack,'imageValid':valid,'rgbDetections':0 if valid else None,'driveCommand':drive,'jointTicks':[1,2,3,4], 'totalSteps':tick,'cameraFrame':tick if valid else -1,'cameraDriving':valid,'cameraStill':valid}
            rows=[row(1,100,0,0,True,[0,0,90]),row(2,110,0,1,True,[12,12,90]),row(3,110,2,7,False,[0,0,90])]
            result={'policyActions':1,'handoff':False,'stopCommandAcknowledged':True,'outcome':'unverified'}
            self.assertEqual(audit.verify_enabled_no_stop(run,result,rows),[1])
            rows[1]['driveCommand']=[0,0,90]
            with self.assertRaisesRegex(ValueError,'drive echo'):audit.verify_enabled_no_stop(run,result,rows)
            rows[1]['driveCommand']=[12,12,90];rows[1]['sequence']=7
            with self.assertRaisesRegex(ValueError,'sequence'):audit.verify_enabled_no_stop(run,result,rows)

    def test_prefix_censor_counts_are_not_hidden(self):
        episodes=[{'status':'completed'},{'status':'censored','censoring':[{'reason':'actor_prefix_or_trigger_image_mismatch'}]},
                  {'status':'censored','censoring':[{'reason':'visual_stop_audit_unsupported_or_failed'}]}]
        self.assertEqual(audit.censor_count(episodes,'actor_prefix_or_trigger_image_mismatch'),1)
        self.assertEqual(audit.censor_count(episodes,'visual_stop_audit_unsupported_or_failed'),1)
        self.assertEqual(audit.compare_observation_prefix([{'sequence':1}],[{'sequence':1}],[1]),[])
        self.assertEqual(audit.compare_observation_prefix([{'sequence':1}],[{'sequence':1,'ack':2}],[1]),['observation-1'])

    def test_motion_labels_have_an_ambiguous_zone(self):
        self.assertEqual(audit.truth_class([[0,0,0],[.009,0,0]])[0],'stationary')
        self.assertEqual(audit.truth_class([[0,0,0],[.03,0,0]])[0],'ambiguous')
        self.assertEqual(audit.truth_class([[0,0,0],[.051,0,0]])[0],'moving')
        self.assertEqual(audit.truth_class([[0,0,0],[0,0,math.radians(11)]])[0],'moving')

    def test_stationary_timing_is_retrospective_and_detects_missing_tick(self):
        poses={i:[0 if i>=20 else -.1,0,0] for i in range(111)}
        self.assertEqual(audit.retrospective_stationary_ticks(poses,0,110),90)
        del poses[50]
        with self.assertRaises(ValueError): audit.retrospective_stationary_ticks(poses,0,110)

    def test_window_low_texture_and_no_drive_censor(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp); actors=run/'actors'; actors.mkdir(); rows=[]
            for seq in range(1,12):
                tick=(seq-1)*10;rows.append({'sequence':seq,'totalSteps':tick})
                if seq<=10:
                    (actors/f'actor-{seq}.rgb').write_bytes(bytes([80])*21168)
                    (actors/f'actor-{seq}.action').write_bytes(struct.pack('<2f',0,.2))
            (run/'physical-agent.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
            (run/'trace.jsonl').write_text(''.join(json.dumps({'totalSteps':i,'pose':[0,0,0]})+'\n' for i in range(101)))
            result={'traceSHA256':audit.visual.sha(run/'trace.jsonl')}
            with mock.patch.object(audit.hidden,'check_actor_inputs',return_value={}):
                _, windows, _=audit.baseline_windows(run,result)
                self.assertEqual((len(windows),windows[0]['truth'],windows[0]['visualCode']),(1,'stationary',3))
                (actors/'actor-3.action').write_bytes(struct.pack('<2f',0,0))
                self.assertEqual(len(audit.baseline_windows(run,result)[1]),0)

    def test_periodic_alias_can_be_visual_suspicion_while_truth_moves(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp);actors=run/'actors';actors.mkdir();rows=[]
            stripe=np.tile(np.array([50]*3+[170]*4,dtype=np.uint8),12)
            image=np.broadcast_to(stripe,(3,84,84)).copy()
            for seq in range(1,12):
                tick=(seq-1)*10;rows.append({'sequence':seq,'totalSteps':tick})
                if seq<=10:
                    (actors/f'actor-{seq}.rgb').write_bytes(np.roll(image,(seq-1)*7,axis=2).tobytes())
                    (actors/f'actor-{seq}.action').write_bytes(struct.pack('<2f',0,.2))
            (run/'physical-agent.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
            (run/'trace.jsonl').write_text(''.join(json.dumps({'totalSteps':i,'pose':[i*.002,0,0]})+'\n' for i in range(101)))
            result={'traceSHA256':audit.visual.sha(run/'trace.jsonl')}
            with mock.patch.object(audit.hidden,'check_actor_inputs',return_value={}):
                _,windows,_=audit.baseline_windows(run,result)
                self.assertEqual((windows[0]['truth'],windows[0]['visualCode']),('moving',2))
                self.assertLess(windows[0]['horizontalPeriodMAD'],.25)

    def test_censored_suite_is_not_counted_as_negative(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); matrix=root/'matrix';matrix.mkdir(); model=root/'model';model.mkdir();(model/'kernels').mkdir()
            files={};paths={}
            def pin(path,data=b'x'):
                path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);files[str(path)]=audit.visual.sha(path);return str(path)
            for key in ('client','simulator','asset','config','runtime'):paths[key]=pin(root/key)
            paths['model']=str(model);pin(model/'policy');pin(model/'weights.bin')
            kernels={}
            for i in range(5):
                name=f'k{i}';pin(model/'kernels'/name);kernels[name]=files[str(model/'kernels'/name)]
            pin(model/'receipt.json',json.dumps({'kernels':kernels,'binarySHA256':files[str(model/'policy')],'weightsSHA256':files[str(model/'weights.bin')]}).encode())
            conditions=[]
            for family in audit.generator.FAMILIES:
                for heading in audit.generator.HEADINGS: conditions.append({'name':f'{family}-yaw-{heading:+.2f}','family':family})
            for layout in audit.generator.ROOM_LAYOUTS: conditions.append({'name':f'room-{layout}','family':'natural-room'})
            for condition in conditions:
                for filename,key in (('case.json','caseSHA256'),('environment.bin','environmentSHA256')):
                    path=pin(matrix/condition['name']/filename);condition[key]=files[path]
            pin(matrix/'conditions.json',json.dumps({'conditions':conditions}).encode())
            (root/'inputs.json').write_text(json.dumps({'schema':'puppybot.sim-visual-validation.v1','conditions':conditions,'files':files,'paths':paths,'pilot':str(root/'pilot'),'matrix':str(matrix),'navigationLimit':90,'wallSecondsPerArm':300}))
            fake=SimpleNamespace(check_matrix=lambda *args:({'paths':paths},{'conditions':conditions}))
            original_load=audit.load
            with mock.patch.object(audit,'load',side_effect=lambda name,path:fake if name=='suite_runner' else original_load(name,path)):
                report=audit.audit(root)
            self.assertEqual(len(report['episodes']),12)
            self.assertTrue(all(row['status']=='censored' for row in report['episodes']))
            self.assertTrue(all('windowCounts' not in row for row in report['episodes']))
            # A pair whose actors diverge must be censored before its
            # retrospective stationary window can affect suite metrics.
            condition=conditions[0];client={'simulatorSHA256':files[paths['simulator']], 'caseSHA256':condition['caseSHA256'],
                'environmentSHA256':condition['environmentSHA256'],'weightsSHA256':files[str(model/'weights.bin')],
                'policySHA256':files[str(model/'policy')],'receiptSHA256':files[str(model/'receipt.json')],
                'robotAssetSHA256':files[paths['asset']],'cameraPitch':82,'contactFeedback':'unavailable-forced-zero'}
            rows=[{'sequence':1,'rgbDetections':0,'totalSteps':0}, {'sequence':2,'owner':2,'ack':7,'driveCommand':[0,0,90]}]
            for arm in ('disabled','enabled'):
                base=root/'cases'/condition['name']/arm;run=base/'run';actors=run/'actors';actors.mkdir(parents=True)
                (base/'monitor').mkdir();(base/'monitor/supervisor-result.json').write_text(json.dumps({'clientExit':0,'timedOut':False,'signal':None,'remainingWorkersTerminated':False}))
                (base/'command.json').write_text(json.dumps([paths['client'],paths['simulator'],paths['model'],str(matrix/condition['name']/'case.json'),str(matrix/condition['name']/'environment.bin'),str(run),'--allow-zero-contact']))
                env={'PATH':'/usr/bin:/bin','HOME':'/tmp','SDL_VIDEODRIVER':'offscreen','LD_LIBRARY_PATH':str(Path(paths['runtime']).parent),'PUPPYBOT_PHYSICAL_NAV_LIMIT':'90','PUPPYBOT_PHYSICAL_POLL_LIMIT':'1499','PUPPYBOT_SIM_VISUAL_STOP':'1' if arm=='enabled' else '0'}
                (base/'environment.json').write_text(json.dumps(env));(run/'trace.jsonl').write_text('trace')
                (run/'result.json').write_text(json.dumps({'policyActions':90,'handoff':False,'stoppedRescanEnabled':False,'visualStopEnabled':arm=='enabled','visualStopReason':0,'stopCommandAcknowledged':True,'outcome':'unverified','traceSHA256':audit.visual.sha(run/'trace.jsonl')}))
                (run/'inputs.json').write_text(json.dumps(client));(run/'physical-agent.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in rows))
                for seq in range(1,91):
                    for ext in ('rgb','feedback','hidden','action'):(actors/f'actor-{seq}.{ext}').write_bytes((arm if ext=='rgb' else 'same').encode())
            manifest=json.loads((root/'inputs.json').read_text());manifest['home']='/tmp';(root/'inputs.json').write_text(json.dumps(manifest))
            window={'truth':'stationary','visualCode':0,'horizontalPeriodMAD':1}
            with mock.patch.object(audit,'load',side_effect=lambda name,path:fake if name=='suite_runner' else original_load(name,path)), mock.patch.object(audit,'baseline_windows',return_value=(rows,[window],{0:[0,0,0]})), mock.patch.object(audit,'truth_trace',return_value={0:[0,0,0]}), mock.patch.object(audit,'require_spawn_match'), mock.patch.object(audit,'verify_enabled_no_stop',return_value=[1]):
                censored=audit.audit(root)
            self.assertEqual(censored['metrics']['casesCensoredForPrefixMismatch'],1)
            self.assertEqual(censored['metrics']['casesWithStationaryWindowsWithoutSuspicion'],0)
            self.assertEqual(censored['episodes'][0]['status'],'censored')


if __name__=='__main__':unittest.main()
