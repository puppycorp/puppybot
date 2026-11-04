#!/usr/bin/env python3
"""Lightweight synthetic saved-game and censoring tests; never runs a GPU."""
import copy
import importlib.util
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('teacher_audit',HERE/'audit.py')
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)


class TeacherAuditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='teacher-audit-test-');cls.root=Path(cls.temp.name)
        cls.teacher=cls.root/'teacher-task';cls.student=cls.root/'student-task';cls.models={'control':Path('/a'),'treatment':Path('/b')}
        cls.games={arm:{} for arm in audit.ARMS};cls.rows=[]
        for i in range(300):
            action=i+1;phase='search' if action<60 or action>150 else ('delivered' if action==150 else 'return')
            cls.rows.append({'sequence':i+3+int(i>=150),'step':505+i*10,'action':[0.0,0.1],
                             'state':{'pose':[0,0,0],'findReturn':{'phase':phase,'consumedIndex':-1 if phase=='search' else 0,'deliveries':int(action>=150)}}})
        decisions=''.join(json.dumps(x)+'\n' for x in cls.rows);cls.base_event={'step':0,'event':'start','robot':[0,0,0],'brick':[1,0]}
        for part in range(4):
            folder=cls.teacher/'teacher'/str(part);folder.mkdir(parents=True)
            (folder.parent/(str(part)+'.log')).write_text('ok\n')
            data=folder/'data.bin'
            with data.open('wb') as f:f.write(b'PVDATA01'+struct.pack('<qqq',8,7,300));f.truncate(32+8*300*21212)
            report={'complete':True,'studentDriven':False,'teacher':'exploring fetch teacher','episodes':8,'trainingEpisodes':7,
                    'validationEpisodes':1,'sequenceLength':300,'seed':audit.BASE+part*8,'teacherUsesCameraDetections':True,
                    'teacherUsesReferenceGeometryForWallsOnly':True,'teacherUsesTargetCoordinates':False,
                    'actorUsesReferencePose':False,'actorUsesTargetCoordinates':False,'dataSHA256':'mock-data'}
            (folder/'report.json').write_text(json.dumps(report))
            for i in range(8):
                index=part*8+i;seed=audit.BASE+index;out=folder/f'expert-{i}';(out/'scene').mkdir(parents=True)
                (out/'scene/case.json').write_text('case');(out/'scene/environment.bin').write_bytes(b'env')
                result={'seed':seed,'game':'fetch','controller':'exploring fetch teacher','steps':300,'actionSeconds':60,
                        'level':2,'levelPlacement':'just off view','blackout':False,'exploreTeacher':True,'sweepTeacher':False,
                        'farBricks':False,'suppliedMap':False,'taskEventHint':False,'carryCue':True,'maximumBrickDistanceM':.35,
                        'policyWeightsSHA256':None,'deliveries':1,'deliveriesPerMinute':1.0,'backForthSteps':0,
                        'reaches':1,'reachesPerMinute':1.0,'contactSteps':0,'pingPongSteps':0,'pathM':0.0}
                events=[cls.base_event,{'step':150,'event':'delivery','robot':[0,0,0],'brick':[1,0]}]
                (out/'result.json').write_text(json.dumps(result));(out/'decisions.jsonl').write_text(decisions)
                (out/'chase.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in events));(out/'native.log').write_text('ok')
                scene=tuple(audit.digest(out/'scene'/name) for name in ('case.json','environment.bin'))
                for arm in audit.ARMS:
                    game=cls.student/arm/str(part)/str(seed);game.mkdir(parents=True)
                    (game/'result.json').write_text('{}');(game/'chase.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in events))
                    result_student={'deliveries':1,'deliveriesPerMinute':1,'backForthSteps':0,'reaches':1,'reachesPerMinute':1,'contactSteps':0,'pingPongSteps':0,'pathM':0}
                    cls.games[arm][seed]=(result_student,cls.rows,copy.deepcopy(cls.base_event),scene)
        (cls.teacher/'score-teacher.json').write_text(json.dumps({'player':'teacher','games':32,'reaches':32,'gamesWithAReach':32,
            'reachesBySeed':[1]*32,'deliveries':32,'gamesWithADelivery':32,'deliveriesBySeed':[1]*32,'meanDeliveriesPerMinute':1.0,
            'meanReachesPerMinute':1.0,'meanContactSteps':0,'meanPathM':0,'meanPingPongShare':0,'meanBackForthShare':0,
            'gamesMostlyPingPong':0,'gamesMostlyBackForth':0}))
        for arm in audit.ARMS:
            score=json.loads((cls.teacher/'score-teacher.json').read_text());score['player']=arm
            (cls.student/('score-'+arm+'.json')).write_text(json.dumps(score))

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def run_audit(self):
        original=audit.digest
        def digest(path):return 'mock-data' if Path(path).name=='data.bin' else original(path)
        def students(root,model,level,*args):return self.games[root.name]
        with mock.patch.object(audit,'digest',side_effect=digest),mock.patch.object(audit.qualification,'strict_games',side_effect=students):
            return audit.audit_task('L2',self.teacher,self.student,self.models)

    def test_complete_matched_rates_and_undefined_zero_ratio(self):
        report=self.run_audit();self.assertEqual(report['status'],'complete_diagnostic',report)
        self.assertEqual(report['results']['teacher']['deliveriesPerMinute'],1)
        self.assertEqual(report['results']['control']['fractionGamesWithDelivery'],1)
        self.assertEqual(report['studentToTeacherRateRatio']['control'],1)
        zero=copy.deepcopy(report);zero['results']['teacher']['deliveries']=0;zero['results']['teacher']['gamesWithDelivery']=0
        pool={f'L{i}':copy.deepcopy(zero) for i in range(1,6)}
        for i in range(1,6):pool[f'L{i}'].update(task=f'L{i}',level=i)
        combined=audit.audit_pool(pool);self.assertEqual(combined['status'],'complete_diagnostic')
        self.assertEqual(combined['results']['teacher']['simulatedMinutes'],160)
        self.assertIsNone(combined['studentToTeacherRateRatio']['control'])
        pool['L1']['level']=True;self.assertEqual(audit.audit_pool(pool)['status'],'censored')

    def test_missing_game_short_trace_wrong_score_and_mismatch_censor(self):
        folder=self.teacher/'teacher/0/expert-0';decisions=folder/'decisions.jsonl';saved=decisions.read_text()
        try:
            decisions.write_text(''.join(saved.splitlines(keepends=True)[:-1]));report=self.run_audit()
            self.assertEqual(report['status'],'censored');self.assertNotIn('results',report)
        finally:decisions.write_text(saved)
        score=self.teacher/'score-teacher.json';saved=score.read_text()
        try:
            data=json.loads(saved);data['deliveries']=31;score.write_text(json.dumps(data))
            self.assertEqual(self.run_audit()['status'],'censored')
        finally:score.write_text(saved)
        score=self.student/'score-control.json';saved=score.read_text()
        try:
            data=json.loads(saved);data['deliveriesBySeed'][0]=4;score.write_text(json.dumps(data))
            self.assertEqual(self.run_audit()['status'],'censored')
        finally:score.write_text(saved)
        old=copy.deepcopy(self.games['control'][audit.BASE]);bad=list(old);bad[2]=dict(bad[2],brick=[2,0]);self.games['control'][audit.BASE]=tuple(bad)
        try:self.assertEqual(self.run_audit()['status'],'censored')
        finally:self.games['control'][audit.BASE]=old
        file=folder/'result.json';saved=file.read_text()
        try:file.unlink();self.assertEqual(self.run_audit()['status'],'censored')
        finally:file.write_text(saved)

    def test_bad_part_header_wrong_teacher_and_pool_completeness(self):
        path=self.teacher/'teacher/0/report.json';saved=path.read_text()
        try:
            report=json.loads(saved);report['teacherUsesTargetCoordinates']=True;path.write_text(json.dumps(report))
            self.assertEqual(self.run_audit()['status'],'censored')
        finally:path.write_text(saved)
        try:
            path.write_text('[]');self.assertEqual(self.run_audit()['status'],'censored')
        finally:path.write_text(saved)
        self.assertEqual(audit.audit_pool({'L1':{'status':'censored'}})['status'],'censored')
        self.assertNotIn('results',audit.audit_pool({}))

    def test_zero_teacher_games_return_no_ratio_and_no_reliability_pass(self):
        saved={};score=self.teacher/'score-teacher.json'
        try:
            saved[score]=score.read_bytes();s=json.loads(saved[score]);s.update(deliveries=0,gamesWithADelivery=0,deliveriesBySeed=[0]*32,meanDeliveriesPerMinute=0,reaches=0,gamesWithAReach=0,reachesBySeed=[0]*32,meanReachesPerMinute=0);score.write_text(json.dumps(s))
            for part in range(4):
                for index in range(8):
                    folder=self.teacher/'teacher'/str(part)/f'expert-{index}'
                    for name in ('result.json','decisions.jsonl','chase.jsonl'):
                        path=folder/name;saved[path]=path.read_bytes()
                    result=json.loads(saved[folder/'result.json']);result.update(deliveries=0,deliveriesPerMinute=0,reaches=0,reachesPerMinute=0);(folder/'result.json').write_text(json.dumps(result))
                    (folder/'chase.jsonl').write_text(json.dumps(self.base_event)+'\n')
                    rows=copy.deepcopy(self.rows)
                    for i,row in enumerate(rows):
                        row['sequence']=i+3;row['state']['findReturn']={'phase':'search','consumedIndex':-1,'deliveries':0}
                    (folder/'decisions.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
            report=self.run_audit();self.assertEqual(report['status'],'complete_diagnostic',report)
            self.assertEqual(report['results']['teacher']['deliveriesPerMinute'],0)
            self.assertFalse(report['results']['teacher']['deliveryReliabilityAtLeast90Percent'])
            self.assertIsNone(report['studentToTeacherRateRatio']['control'])
        finally:
            for path,data in saved.items():path.write_bytes(data)

    def test_nonfinite_delivery_and_unaccounted_sequence_jump_censor(self):
        folder=self.teacher/'teacher/0/expert-0';events=folder/'chase.jsonl';saved=events.read_text()
        try:
            rows=[json.loads(line) for line in saved.splitlines()];rows[1]['brick'][0]=float('nan')
            events.write_text(''.join(json.dumps(row)+'\n' for row in rows));self.assertEqual(self.run_audit()['status'],'censored')
        finally:events.write_text(saved)
        path=folder/'decisions.jsonl';saved=path.read_text()
        try:
            rows=[json.loads(line) for line in saved.splitlines()];rows[5]['sequence']+=1
            path.write_text(''.join(json.dumps(row)+'\n' for row in rows));self.assertEqual(self.run_audit()['status'],'censored')
        finally:path.write_text(saved)

    def test_delivery_event_must_match_per_action_state(self):
        result={'deliveries':1,'reaches':1};events=[self.base_event,{'event':'delivery','step':150}]
        audit.validate_transitions(result,self.rows,events,'fixture')
        altered=copy.deepcopy(self.rows);altered[149]['state']['findReturn']['deliveries']=0
        with self.assertRaisesRegex(ValueError,'disagrees'):audit.validate_transitions(result,altered,events,'fixture')
        altered=copy.deepcopy(self.rows);altered[149]['state']['findReturn']['phase']='return'
        with self.assertRaisesRegex(ValueError,'disagrees'):audit.validate_transitions(result,altered,events,'fixture')

    def test_doorway_censor_and_zero_time_placement(self):
        events=[{'event':'start','step':0,'robot':[-1,0,0],'brick':[1,0]},
                {'event':'delivery','step':60,'robot':[-1,0,0],'brick':[-2,0]},
                {'event':'delivery','step':300,'robot':[-1,0,0],'brick':[1,0]}]
        self.assertEqual(audit.doorway_cases(events,0),(2,1,1,1))
        self.assertEqual(audit.doorway_cases([{'event':'start','step':0,'robot':[-1,0,0],'brick':[-2,0]}],0),(0,0,0,0))


if __name__=='__main__':unittest.main()
