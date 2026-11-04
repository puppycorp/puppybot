#!/usr/bin/env python3
"""Synthetic saved-action stream tests; no policy or GPU runs."""
import copy
import hashlib
import importlib.util
import math
import json
import tempfile
from unittest import mock
import unittest
from pathlib import Path

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('hysteresis_audit',HERE/'audit.py');audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
kick=audit.kick
ZERO=hashlib.sha256(bytes(512)).hexdigest()


def generated(zero_at=None,subnormal_at=None,contact_at=None,carry_at=None,zero_steering=None):
    """One deterministic sequence, independently constructed from the frozen rule."""
    probes=[];decisions=[];journal=[];prior=[0,0];drive=[0,0,90];hidden=ZERO
    remaining=0;used=False;disabled=False;held=0;history=[]
    for i in range(300):
        carrying=carry_at is not None and i>=carry_at;contact=i==contact_at
        if carrying:disabled=True;remaining=0
        if contact and remaining:disabled=True;remaining=0
        proposed=[kick.bits(-.6),kick.bits(-1. if i%2==0 else 1.)]
        if zero_steering is not None and i==1:proposed[0]=kick.bits(zero_steering)
        if i==zero_at:proposed[1]=kick.bits(-0.)
        if i==subnormal_at:proposed[1]=0x80000001
        postkick=proposed.copy()
        if not carrying and i<3 and kick.value(postkick[0])!=0:postkick[0]=kick.sign_flip(postkick[0])
        armed=False
        if not used and not disabled and not contact and len(history)>=8:
            recent=history[-8:];signs=[x[0] for x in recent]
            if all(signs) and sum(a*b<0 for a,b in zip(signs,signs[1:]))>=6:
                armed=True;used=True;remaining=2;held=signs[-1]
        before=remaining;applied=postkick.copy()
        if remaining:
            speed=kick.value(applied[1]);sign=(speed>0)-(speed<0)
            if sign and sign!=held:applied[1]=kick.sign_flip(applied[1])
            remaining-=1
        action=[kick.value(v) for v in applied];command=[round(v*1000) for v in action]
        throttle=math.trunc(command[1]*60/1000) if abs(command[1])>=80 else 0
        echo=[throttle,throttle,90+math.trunc(math.trunc(command[0]/10)*45/100)]
        feedback=prior+[kick.bits(drive[0]/100),kick.bits(drive[1]/100),kick.bits((drive[2]-90)/45),kick.bits(float(contact)),kick.bits(float(carrying))]
        after=hashlib.sha256(str(i).encode()).hexdigest()
        probes.append({'step':i+1,'mode':2,'trigger':True,'cancelled':carrying,'proposed':proposed,'applied':applied,'feedback':feedback,'previousApplied':applied,'command1000':command,'echo':echo,'imageSHA256':'a'*64,'hiddenBeforeSHA256':hidden,'hiddenAfterSHA256':after})
        journal.append({'step':i+1,'trigger':armed,'used':used,'disabled':disabled,'remainingBefore':before,'remainingAfter':remaining,'heldSign':held,'carryBefore':carrying,'contactBefore':contact,'kick':postkick,'applied':applied})
        state={'controller':{'drive':{'leftSpeed':echo[0],'rightSpeed':echo[1],'steeringAngleDeg':echo[2]}},'localization':{'mode':'wheel-drift','source':'wheel-steering-command-integration','pose':[0.,0.,0.]},'step':i*10+100,'totalSteps':i*10+100,'camera':{'pose':'driving','armSettled':True},'case':{'perception':{'frameId':i*10+100}},'findReturn':{'consumedIndex':0 if carry_at is not None and i>=carry_at-1 else -1,'deliveries':0}}
        decisions.append({'action':action,'state':state})
        speed=kick.value(applied[1]);history.append(((speed>0)-(speed<0),[0.,0.,0.]));prior=applied;drive=echo;hidden=after
    return probes,decisions,journal


class SavedTest(unittest.TestCase):
    def test_300_action_activation_and_retrigger_latch(self):
        p,d,j=generated();result=audit.audit_hysteresis(p,d,j)
        self.assertEqual(result['hysteresisActivations'],[9]);self.assertEqual(j[8]['remainingBefore'],2);self.assertEqual(j[9]['remainingAfter'],0)
        self.assertNotEqual(j[8]['kick'][1],j[8]['applied'][1]);self.assertEqual(j[10]['kick'],j[10]['applied'])

    def test_zero_subnormal_and_safety_cancellation(self):
        self.assertEqual(audit.audit_hysteresis(*generated(zero_at=6))['hysteresisActivations'],[16])
        self.assertEqual(audit.audit_hysteresis(*generated(subnormal_at=6))['hysteresisActivations'],[9])
        for kwargs in ({'contact_at':9},{'carry_at':9}):
            p,d,j=generated(**kwargs);result=audit.audit_hysteresis(p,d,j)
            self.assertEqual(result['hysteresisActivations'],[9]);self.assertTrue(j[9]['disabled']);self.assertEqual(j[9]['remainingBefore'],0)

    def test_signed_zero_steering_is_not_flipped_by_kick(self):
        for zero in (0.,-0.):
            with self.subTest(zero=zero):
                p,d,j=generated(zero_steering=zero)
                self.assertEqual(p[1]['proposed'][0],j[1]['applied'][0])
                self.assertEqual(audit.audit_hysteresis(p,d,j)['hysteresisActivations'],[9])

    def test_saved_three_arm_prefix_and_noop_accounting(self):
        with tempfile.TemporaryDirectory() as tmp:
            p,d,j=generated();root=Path(tmp);(root/'hysteresis.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in j))
            metric={'completedDelivery':False,'firstVirtualConsumptionAction':None}
            hys={'startBytes':b'start','initialBytes':b'initial','probe':p,'decisions':d,'result':{'contactSteps':0},'metrics':metric,'backForthSteps':0}
            old=copy.deepcopy(hys);old['probe'][8]['applied'][1]=kick.sign_flip(old['probe'][8]['applied'][1])
            original=copy.deepcopy(old);checks={'control':{'contactActions':0},'intervention':{'contactActions':0}}
            def run():
                with mock.patch.object(audit.kick,'saved_game',side_effect=[original,old,hys]),mock.patch.object(audit.kick,'audit_pair',return_value=checks):
                    return audit.saved_three(root/'c',root/'k',root,6800200,{})
            result=run();self.assertEqual(result['firstHysteresisDifference'],9);self.assertEqual(result['hysteresisProbe']['hysteresisActivations'],[9])
            old['probe'][0]['imageSHA256']='b'*64
            with self.assertRaisesRegex(ValueError,'prefix differs'):run()

    def test_complete_report_includes_noops_and_rejects_missing_seed(self):
        metric={'completedDelivery':True,'firstVirtualConsumptionAction':100}
        pairs=[{'seed':6800200+i,'control':dict(metric),'kick':dict(metric),'kickHysteresis':dict(metric),
                'controlBackForthSteps':0,'kickBackForthSteps':0,'hysteresisBackForthSteps':0,
                'hysteresisProbe':{'hysteresisActivations':[120] if i<2 else []},'firstHysteresisDifference':120 if i<2 else None}
               for i in range(12)]
        report=audit.report(pairs);self.assertEqual(report['totals']['hysteresisActivatedGames'],2);self.assertEqual(report['totals']['hysteresisChangedGames'],2)
        self.assertEqual(report['totals']['hysteresisNoActivationGames'],10);self.assertEqual(report['totals']['kick']['games'],12)
        with self.assertRaises(ValueError):audit.report(pairs[:-1])
        pairs[0]['seed']=pairs[1]['seed']
        with self.assertRaises(ValueError):audit.report(pairs)

    def test_tampering_is_rejected(self):
        for field in ('missing','trigger','carry','contact','odometry','source','frame','stale-tick','action','echo','journal','oneshot','hidden','float-mode','float-command','float-echo'):
            with self.subTest(field=field):
                p,d,j=generated()
                if field=='missing':j.pop()
                elif field=='trigger':j[8]['trigger']=False
                elif field=='carry':j[8]['carryBefore']=True
                elif field=='contact':j[8]['contactBefore']=True
                elif field=='odometry':d[7]['state']['localization']['pose'][0]=.2
                elif field=='source':d[7]['state']['localization']['source']='truth'
                elif field=='frame':d[7]['state']['case']['perception']['frameId']-=1
                elif field=='stale-tick':
                    for key in ('step','totalSteps'):d[7]['state'][key]-=10
                    d[7]['state']['case']['perception']['frameId']-=10
                elif field=='action':d[8]['action'][1]*=-1
                elif field=='echo':p[8]['echo'][0]+=1
                elif field=='journal':j[9]['remainingAfter']=1
                elif field=='oneshot':j[20]['trigger']=True
                elif field=='hidden':p[20]['hiddenBeforeSHA256']='b'*64
                elif field=='float-mode':p[0]['mode']=2.0
                elif field=='float-command':p[0]['command1000'][0]=float(p[0]['command1000'][0])
                elif field=='float-echo':p[0]['echo'][0]=float(p[0]['echo'][0])
                with self.assertRaises((ValueError,KeyError,TypeError)):audit.audit_hysteresis(p,d,j)


if __name__=='__main__':unittest.main()
