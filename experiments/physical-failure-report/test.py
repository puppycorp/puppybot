#!/usr/bin/env python3
"""CPU-only socket peers for isolated simulated failure reports."""
import hashlib
import importlib.util
import json
import os
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('prepare',HERE/'prepare.py')
prepare=importlib.util.module_from_spec(spec);spec.loader.exec_module(prepare)

POLICY='''#!/usr/bin/env python3
import os,socket,struct
s=socket.socket(fileno=3);s.sendall(b"VCPOL001")
def read(n):
 b=b""
 while len(b)<n:
  x=s.recv(n-len(b))
  if not x:raise EOFError()
  b+=x
 return b
try:
 while True:
  frame=read((21168+7+128)*4)
  with open(os.environ["PUPPY_TEST_ACTOR"],"ab") as f:f.write(frame)
  s.sendall(struct.pack("<130f",0.0,0.2,*([0.0]*128)))
except EOFError:pass
'''

SIMULATOR='''#!/usr/bin/env python3
import json,os,socket,struct,sys,time
from pathlib import Path
s=socket.socket(fileno=3);step=100;det=int(os.environ.get("PUPPY_TEST_VISIBLE","1"));mode=os.environ["PUPPY_TEST_MODE"]
Path(sys.argv[sys.argv.index("--record")+1]).write_text("stub trace\\n")
def read(n):
 b=b""
 while len(b)<n:
  x=s.recv(n-len(b))
  if not x:raise EOFError()
  b+=x
 return b
try:
 while True:
  cmd,seq,steer,speed,hold,_,task,_=struct.unpack("<8q",read(64))
  with open(os.environ["PUPPY_TEST_COMMANDS"],"a") as f:f.write(str(cmd)+"\\n")
  owner=0;valid=True;ack=0;drive=[0,0,90]
  if cmd==2:step+=hold;det=1;ack=1;drive=[int(speed*60/1000)]*2+[90+int(int(steer/10)*45/100)]
  elif cmd==6:step+=2;owner=1;valid=False;ack=3
  elif cmd==7:step+=hold;owner=2;valid=False;ack=6 if mode in ("ack6","bad_drive","write_error") else 5
  elif cmd==3:owner=2;valid=False;ack=7
  if cmd==7 and mode=="bad_drive":drive=[1,1,90]
  if cmd==3 and mode=="stop_bad_drive":drive=[1,1,90]
  if cmd==3 and mode=="stop_bad_status":ack=6
  if cmd==3 and mode=="after_stop_change":Path(sys.argv[sys.argv.index("--case-file")+1]).write_text('{"changed":true}')
  if cmd==7 and mode=="write_error":Path(sys.argv[sys.argv.index("--record")+1]).parent.chmod(0o500)
  if (cmd==7 and mode=="eof") or (cmd==3 and mode=="stop_eof"):break
  if cmd==7 and mode=="timeout":time.sleep(55);break
  x={"schema":"puppybot.physical-agent.v1","sequence":seq,"step":step,"timeMs":step*20,"owner":owner,"ack":ack,"imageValid":valid,"rgbDetections":det if valid else None,"totalSteps":step,"cameraFrame":step if valid else -1,"cameraDriving":valid,"cameraStill":valid,"driveCommand":drive,"jointTicks":[1,2,3,4]}
  if cmd==7 and mode=="missing_owner":del x["owner"]
  if cmd==7 and mode=="missing_schema":del x["schema"]
  if cmd==7 and mode=="bad_schema_type":x["schema"]=False
  js=(json.dumps(x)+"\\n").encode()
  if cmd==7 and mode=="bad_json":js=b"{invalid}"
  header=struct.pack("<4q",len(js),640*480*3,seq+(cmd==7 and mode=="bad_sequence"),0)
  if cmd==7 and mode=="partial":s.sendall(header[:8]);break
  s.sendall(header+js+(bytes([128,64,255])*(640*480) if valid else bytes(640*480*3)))
  if cmd==3:break
except (EOFError,BrokenPipeError,ConnectionResetError):pass
'''


class FailureReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='puppy-failure-report-');cls.root=Path(cls.temp.name)
        cls.build=cls.root/'build';prepare.prepare(cls.build)
        cls.model=cls.root/'model';cls.model.mkdir();(cls.model/'kernels').mkdir();(cls.model/'weights.bin').write_bytes(b'weights')
        (cls.model/'policy').write_text(POLICY);(cls.model/'policy').chmod(0o755)
        kernels={}
        for i in range(5):
            name=f'kernel{i}';file=cls.model/'kernels'/name;file.write_bytes(name.encode());kernels[name]=prepare.digest(file)
        (cls.model/'receipt.json').write_text(json.dumps({'weightsSHA256':prepare.digest(cls.model/'weights.bin'),'binarySHA256':prepare.digest(cls.model/'policy'),'memoryWidth':128,'kernels':kernels}))
        cls.sim=cls.root/'simulator';cls.sim.write_text(SIMULATOR);cls.sim.chmod(0o755)
        cls.case=cls.root/'case.json';cls.case.write_text('{}');cls.envfile=cls.root/'environment.bin';cls.envfile.write_bytes(b'env')

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def run_case(self,name,mode,enabled=True,binary='candidate',visible=True,timeout=15):
        out=self.root/name;commands=self.root/(name+'.commands');actor=self.root/(name+'.actor')
        case=self.root/(name+'.case.json');case.write_bytes(self.case.read_bytes())
        env=dict(os.environ,PUPPY_TEST_MODE=mode,PUPPY_TEST_COMMANDS=str(commands),PUPPY_TEST_ACTOR=str(actor),PUPPY_TEST_VISIBLE='1' if visible else '0',PUPPYBOT_SIM_FAILURE_REPORT='1' if enabled else '0')
        result=subprocess.run([str(self.build/binary),str(self.sim),str(self.model),str(case),str(self.envfile),str(out),'--allow-zero-contact'],cwd=ROOT,env=env,capture_output=True,text=True,timeout=timeout)
        return out,result,commands,actor

    def test_normal_disabled_baseline_and_enabled_parity(self):
        runs=[self.run_case('base','normal',False,'baseline',False),self.run_case('disabled','normal',False,visible=False),self.run_case('enabled','normal',True,visible=False)]
        for out,result,commands,actor in runs:
            self.assertEqual(result.returncode,0,result.stderr);self.assertFalse((out/'failure.json').exists())
            self.assertTrue(json.loads((out/'result.json').read_text())['stopCommandAcknowledged']);self.assertEqual(commands.read_text(),'1\n2\n6\n7\n3\n')
        for name in ('result.json','physical-agent.jsonl','actors/actor-1.rgb','actors/actor-1.feedback','actors/actor-1.hidden','actors/actor-1.action'):
            self.assertEqual((runs[0][0]/name).read_bytes(),(runs[1][0]/name).read_bytes());self.assertEqual((runs[0][0]/name).read_bytes(),(runs[2][0]/name).read_bytes())
        self.assertEqual(runs[0][3].read_bytes(),runs[1][3].read_bytes());self.assertEqual(runs[0][3].read_bytes(),runs[2][3].read_bytes())

    def test_ack6_is_peer_report_not_stop_ack_and_latched(self):
        out,result,commands,_=self.run_case('ack6','ack6')
        self.assertNotEqual(result.returncode,0);self.assertEqual(commands.read_text(),'1\n6\n7\n')
        failure=json.loads((out/'failure.json').read_text())
        self.assertEqual(failure['reason'],'collector peer reported failure');self.assertEqual(failure['command'],7)
        self.assertIs(failure['peerReportedZeroDrive'],True);self.assertIs(failure['stopCommandAcknowledged'],False)
        self.assertEqual((failure['physicalStop'],failure['delivery']),('unverified','unverified'));self.assertFalse((out/'result.json').exists())
        disabled,result,_,_=self.run_case('disabled-ack6','ack6',False)
        self.assertNotEqual(result.returncode,0);self.assertFalse((disabled/'failure.json').exists())
        baseline,base_result,_,_=self.run_case('baseline-ack6','ack6',False,'baseline')
        self.assertEqual(result.returncode,base_result.returncode);self.assertEqual(result.stderr,base_result.stderr)
        self.assertEqual((disabled/'physical-agent.jsonl').read_bytes(),(baseline/'physical-agent.jsonl').read_bytes())

    def test_invalid_peer_replies_and_stop_failure_are_unverified(self):
        for mode in ('bad_drive','bad_sequence','bad_json','missing_owner','missing_schema','bad_schema_type','eof','partial','stop_eof','stop_bad_drive','stop_bad_status'):
            with self.subTest(mode=mode):
                out,result,commands,_=self.run_case(mode,mode)
                self.assertNotEqual(result.returncode,0,result.stdout);failure=json.loads((out/'failure.json').read_text())
                self.assertIs(failure['peerReportedZeroDrive'],False);self.assertIs(failure['stopCommandAcknowledged'],False)
                self.assertEqual(failure['delivery'],'unverified');self.assertFalse((out/'result.json').exists())
                if mode.startswith('stop_'):self.assertEqual(failure['command'],3)

    def test_failure_report_is_best_effort(self):
        out,result,_,_=self.run_case('write_error','write_error')
        out.chmod(0o700)
        self.assertNotEqual(result.returncode,0);self.assertFalse((out/'failure.json').exists())
        self.assertIn('Cannot write diagnostic failure report',result.stderr)

    def test_failure_after_valid_stop_ack_remains_physically_unverified(self):
        out,result,commands,_=self.run_case('after-stop','after_stop_change')
        self.assertNotEqual(result.returncode,0);self.assertEqual(commands.read_text(),'1\n6\n7\n3\n')
        failure=json.loads((out/'failure.json').read_text())
        self.assertIs(failure['stopCommandAcknowledged'],True);self.assertIs(failure['peerReportedZeroDrive'],False)
        self.assertEqual(failure['physicalStop'],'unverified');self.assertEqual(failure['delivery'],'unverified')

    def test_peer_timeout_uses_real_45_second_deadline(self):
        out,result,_,_=self.run_case('timeout','timeout',timeout=53)
        self.assertNotEqual(result.returncode,0);failure=json.loads((out/'failure.json').read_text())
        self.assertIn('timeout',failure['reason']);self.assertIs(failure['stopCommandAcknowledged'],False)


if __name__=='__main__':unittest.main()
