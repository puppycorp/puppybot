#!/usr/bin/env python3
"""CPU-only synthetic protocol checks; no simulator or GPU."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('search_fixture',HERE/'fixture_support.py')
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
spec=importlib.util.spec_from_file_location('trial_audit',HERE/'audit.py')
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)


class ProtocolTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.run=Path(self.tmp.name)/'run'

    def case(self,mode='search',polls=1499):
        self.rows,self.intents,self.result=fixture.build_protocol(self.run,mode,polls)
        self.enabled=mode!='baseline'

    def check(self):
        fixture.write_protocol(self.run,self.rows,self.intents,self.result,self.enabled)
        return audit.protocol(self.run,self.enabled)

    def rejected(self):
        with self.assertRaises((ValueError,KeyError,TypeError)):
            self.check()

    def test_valid_control_and_search_transfers(self):
        for mode,expected,handoff in [('baseline',False,False),('search',True,False),('target-race',False,True),('lost-target',False,False)]:
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                run=Path(tmp)/'run';fixture.build_protocol(run,mode)
                p=audit.protocol(run,mode!='baseline')
                self.assertEqual(p['searchStep'] is not None,expected)
                self.assertEqual(p['handoffStep'] is not None,handoff)
                self.assertFalse(p['terminal']);self.assertEqual(p['actions'],90)

    def test_short_collector_cutoff_is_rejected(self):
        self.case(polls=1);self.rejected()

    def test_search_ack_fields_are_required(self):
        cases=[('owner',0),('ack',3),('imageValid',True),('rgbDetections',0),('cameraFrame',0),('cameraStill',True),('cameraDriving',True),('jointTicks',[1,2,3,5]),('driveCommand',[1,1,90])]
        for field,value in cases:
            with self.subTest(field=field),tempfile.TemporaryDirectory() as tmp:
                run=Path(tmp)/'run';rows,intents,result=fixture.build_protocol(run,'search')
                rows[91][field]=value;fixture.write_protocol(run,rows,intents,result,True)
                with self.assertRaises((ValueError,KeyError,TypeError)):audit.protocol(run,True)

    def test_stop_tick_and_clock_mismatch(self):
        self.case();self.rows[91]['totalSteps']+=1;self.rows[91]['step']+=1;self.rejected()

    def test_intent_tampering_despite_same_drive_echo(self):
        self.case();self.intents[1]['speed']=201;self.rejected()

    def test_replay_and_false_result_rejected(self):
        self.case();self.rows[5]['sequence']=self.rows[4]['sequence'];self.rejected()
        self.rows[5]['sequence']=6;self.result['searchFallbackStarted']=False;self.rejected()

    def test_rejected_search_requires_ordinary_retry(self):
        self.case('target-race');self.intents[92]['command']=8;self.rejected()

    def test_handoff_without_detection_after_action_limit_is_rejected(self):
        self.case();self.intents[91]['command']=6;self.rows[91]['ack']=3
        self.result['searchFallbackStarted']=False;self.result['handoff']=True
        self.rejected()

    def test_disabled_cannot_emit_opt_in_files(self):
        self.case('baseline');(self.run/'search-requests.jsonl').write_text('')
        self.rejected()

    def test_invalid_final_stop(self):
        self.case();self.rows[-1]['driveCommand']=[1,1,90];self.rejected()

    def test_strict_result_types_and_rescan_fields(self):
        cases=[('handoff',0),('collectorTerminal',0),('stopCommandAcknowledged',1),('stoppedRescanEnabled',0),('stoppedRescanAttempts',1),('stoppedRescanHandoff',True),('stoppedRescanStopReason',1),('stoppedRescanStopReasonText','unsafe')]
        for field,value in cases:
            with self.subTest(field=field),tempfile.TemporaryDirectory() as tmp:
                run=Path(tmp)/'run';rows,intents,result=fixture.build_protocol(run,'search')
                result[field]=value;fixture.write_protocol(run,rows,intents,result,True)
                with self.assertRaises((ValueError,KeyError,TypeError)):audit.protocol(run,True)

    def test_collector_owned_camera_fields_must_be_blank(self):
        for index in (92,-1):
            for field,value in [('rgbDetections',0),('cameraFrame',0),('cameraDriving',True),('cameraStill',True)]:
                with self.subTest(index=index,field=field),tempfile.TemporaryDirectory() as tmp:
                    run=Path(tmp)/'run';rows,intents,result=fixture.build_protocol(run,'search')
                    rows[index][field]=value;fixture.write_protocol(run,rows,intents,result,True)
                    with self.assertRaises((ValueError,KeyError,TypeError)):audit.protocol(run,True)


if __name__=='__main__':unittest.main()
