#!/usr/bin/env python3
"""CPU-only copied-client protocol fixtures with fake simulator and policy."""
import hashlib
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
spec=importlib.util.spec_from_file_location('search_build_client',HERE/'prepare.py')
prepare=importlib.util.module_from_spec(spec);spec.loader.exec_module(prepare)
spec=importlib.util.spec_from_file_location('prior_client_fixtures',ROOT/'experiments/physical-failure-report/test.py')
fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)


SIMULATOR='''#!/usr/bin/env python3
import json,os,socket,struct,sys,time
from pathlib import Path
s=socket.socket(fileno=3);step=100;visible=int(os.environ["SEARCH_TEST_VISIBLE"]);mode=os.environ["SEARCH_TEST_MODE"]
Path(sys.argv[sys.argv.index("--record")+1]).write_text("synthetic trace\\n")
def read(n):
 data=b""
 while len(data)<n:
  chunk=s.recv(n-len(data))
  if not chunk:raise EOFError()
  data+=chunk
 return data
try:
 while True:
  cmd,seq,steer,speed,hold,_,task,_=struct.unpack("<8q",read(64));owner=0;valid=True;ack=0;drive=[0,0,90]
  with open(os.environ["SEARCH_TEST_COMMANDS"],"a") as f:f.write(str(cmd)+"\\n")
  if cmd==2:
   step+=hold;ack=1;drive=[int(speed*60/1000)]*2+[90+int(int(steer/10)*45/100)]
   if mode=="detected-after-action":visible=1
  elif cmd==6:
   step+=2
   if mode=="target-vanishes":visible=0;ack=2
   else:owner=1;valid=False;ack=3
  elif cmd==8:
   step+=1 if mode=="stale" else 2
   if mode in ("new-target","target-vanishes"):visible=1;ack=2
   elif mode=="ack2-no-target":ack=2
   else:owner=1;valid=False;ack=8
   if mode=="bad-ack":ack=7
   if mode=="bad-owner":owner=2
   if mode=="valid-image":valid=True
   if mode=="bad-drive":drive=[1,1,90]
   if mode=="eof":break
   if mode=="hang":time.sleep(55);break
  elif cmd==7:step+=hold;owner=2;valid=False;ack=5
  elif cmd==3:owner=2;valid=False;ack=7
  x={"schema":"puppybot.physical-agent.v1","sequence":seq,"step":step,"timeMs":step*20,"owner":owner,"ack":ack,"imageValid":valid,"rgbDetections":visible if valid else None,"totalSteps":step,"cameraFrame":step if valid else -1,"cameraDriving":valid,"cameraStill":valid,"driveCommand":drive,"jointTicks":[1,2,3,4]}
  if cmd==8 and mode=="missing-frame":del x["cameraFrame"]
  if cmd==8 and mode=="missing-joints":del x["jointTicks"]
  if cmd==8 and mode=="changed-joints":x["jointTicks"]=[1,2,3,5]
  if cmd==8 and mode=="malformed-joints":x["jointTicks"]=[1,2,3,"4"]
  body=(json.dumps(x)+"\\n").encode();header=struct.pack("<4q",len(body),640*480*3,seq+(cmd==8 and mode=="bad-sequence"),0)
  pixels=bytes([128,64,255])*(640*480) if valid else bytes(640*480*3)
  if cmd==8 and mode=="nonblank":pixels=bytes([1])+pixels[1:]
  s.sendall(header+body+pixels)
  if cmd==3:break
except (EOFError,BrokenPipeError,ConnectionResetError):pass
'''


class SearchClientTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='puppy-search-client-');cls.root=Path(cls.temp.name);cls.build=cls.root/'build';prepare.build(cls.build)
        cls.shadow=cls.root/'shadow';shutil.copytree(cls.build/'source',cls.shadow)
        original=prepare.ARCHIVE/'inputs/flex-source/control/physical-client.flex'
        candidate=(cls.shadow/'control/physical-client.flex').read_text()
        for name,text in (('candidate',candidate),('baseline',original.read_text()),('journal-fail',candidate)):
            # Substitute the tiny test case for the 84 MB shared robot asset;
            # all protocol and opt-in logic remains the copied real source.
            old='vc_file_sha("build/flex/sim/puppybot.bin")'
            if text.count(old)!=2:raise ValueError('client asset-check shape changed')
            text=text.replace(old,'vc_file_sha(case_path)')
            if name=='journal-fail':
                marker='fn pc_search_intent(command, steering, speed, hold) {'
                if text.count(marker)!=1:raise ValueError('intent journal shape changed')
                text=text.replace(marker,marker+' if command == 8 { syscall(3, pc_search_requests, 0, 0, 0, 0, 0); }',1)
            source=cls.shadow/'control'/('test-'+name+'.flex');source.write_text(text)
            binary=cls.root/('client-'+name);built=subprocess.run([str(prepare.COMPILER),str(source),'-o',str(binary)],cwd=ROOT,capture_output=True,text=True,timeout=120)
            if built.returncode:raise RuntimeError(built.stdout+'\n'+built.stderr)
        # Exercise the real timeout code with a test-only accelerated deadline;
        # the production default remains 45 seconds.
        host=cls.shadow/'control/host.flex';text=host.read_text();old='global vc_io_timeout=45000;'
        if text.count(old)!=1:raise ValueError('stream timeout shape changed')
        host.write_text(text.replace(old,'global vc_io_timeout=250;',1))
        built=subprocess.run([str(prepare.COMPILER),str(cls.shadow/'control/test-candidate.flex'),'-o',str(cls.root/'client-internal-timeout')],cwd=ROOT,capture_output=True,text=True,timeout=120)
        if built.returncode:raise RuntimeError(built.stdout+'\n'+built.stderr)
        cls.model=cls.root/'model';cls.model.mkdir();(cls.model/'kernels').mkdir();(cls.model/'weights.bin').write_bytes(b'weights')
        (cls.model/'policy').write_text(fixtures.POLICY);(cls.model/'policy').chmod(0o755)
        digest=lambda path:hashlib.sha256(path.read_bytes()).hexdigest();kernels={}
        for i in range(5):
            path=cls.model/'kernels'/str(i);path.write_text('kernel'+str(i));kernels[path.name]=digest(path)
        (cls.model/'receipt.json').write_text(json.dumps({'weightsSHA256':digest(cls.model/'weights.bin'),'binarySHA256':digest(cls.model/'policy'),'memoryWidth':128,'kernels':kernels}))
        cls.simulator=cls.root/'simulator';cls.simulator.write_text(SIMULATOR);cls.simulator.chmod(0o755)
        cls.case=cls.root/'case.json';cls.case.write_text('{}');cls.environment=cls.root/'environment.bin';cls.environment.write_bytes(b'env')

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def run_case(self,name,*,enabled=False,mode='normal',visible=False,binary='candidate',rescan=False,timeout=15):
        output=self.root/name;commands=self.root/(name+'.commands');actor=self.root/(name+'.actor')
        env=dict(os.environ,PUPPYBOT_PHYSICAL_NAV_LIMIT='1',PUPPYBOT_PHYSICAL_POLL_LIMIT='1',
                 PUPPYBOT_PHYSICAL_SEARCH_FALLBACK='1' if enabled else '0',PUPPYBOT_PHYSICAL_GUARDED_RESCAN='1' if rescan else '0',
                 SEARCH_TEST_VISIBLE='1' if visible else '0',SEARCH_TEST_MODE=mode,SEARCH_TEST_COMMANDS=str(commands),PUPPY_TEST_ACTOR=str(actor))
        env.pop('PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS',None)
        command=[str(self.root/('client-'+binary)),str(self.simulator),str(self.model),str(self.case),str(self.environment),str(output),'--allow-zero-contact']
        done=subprocess.run(command,cwd=ROOT,env=env,capture_output=True,text=True,timeout=timeout)
        return output,done,commands,actor

    def test_disabled_client_is_byte_equivalent_to_archived_baseline(self):
        a=self.run_case('baseline',binary='baseline');b=self.run_case('disabled')
        for output,done,commands,actor in (a,b):
            self.assertEqual(done.returncode,0,done.stderr);self.assertEqual(commands.read_text(),'1\n2\n3\n')
            self.assertFalse(json.loads((output/'result.json').read_text())['handoff'])
            self.assertFalse((output/'search-requests.jsonl').exists())
        for path in ('result.json','physical-agent.jsonl','inputs.json','actors/actor-1.rgb','actors/actor-1.feedback','actors/actor-1.hidden','actors/actor-1.action'):
            self.assertEqual((a[0]/path).read_bytes(),(b[0]/path).read_bytes(),path)
        self.assertEqual(a[3].read_bytes(),b[3].read_bytes())

    def test_no_target_search_and_visible_target_use_distinct_handoffs(self):
        output,done,commands,_=self.run_case('search',enabled=True)
        self.assertEqual(done.returncode,0,done.stderr);self.assertEqual(commands.read_text(),'1\n2\n8\n7\n3\n')
        result=json.loads((output/'result.json').read_text());self.assertTrue(result['searchFallbackStarted']);self.assertFalse(result['handoff']);self.assertTrue(result['stopCommandAcknowledged']);self.assertEqual(result['outcome'],'unverified')
        rows=[json.loads(x) for x in (output/'physical-agent.jsonl').read_text().splitlines()]
        self.assertEqual([(x['sequence'],x['owner'],x['ack']) for x in rows],[(1,0,0),(2,0,1),(3,1,8),(4,2,5),(5,2,7)])
        self.assertEqual(rows[2]['totalSteps']-rows[1]['totalSteps'],2);self.assertEqual(rows[2]['driveCommand'],[0,0,90])
        intents=[json.loads(x) for x in (output/'search-requests.jsonl').read_text().splitlines()]
        self.assertEqual([x['command'] for x in intents],[1,2,8,7,3]);self.assertEqual([x['sequence'] for x in intents],list(range(1,6)))
        self.assertEqual((intents[2]['steering'],intents[2]['speed'],intents[2]['hold']),(0,0,0))
        self.assertTrue(json.loads((output/'inputs.json').read_text())['searchFallbackEnabled'])
        output,done,commands,_=self.run_case('visible',enabled=True,visible=True)
        self.assertEqual(done.returncode,0,done.stderr);self.assertEqual(commands.read_text(),'1\n6\n7\n3\n')
        result=json.loads((output/'result.json').read_text());self.assertFalse(result['searchFallbackStarted']);self.assertTrue(result['handoff'])
        self.assertEqual([x['command'] for x in map(json.loads,(output/'search-requests.jsonl').read_text().splitlines())],[1,6,7,3])

    def test_target_appearing_at_budget_or_during_search_uses_command6(self):
        for mode,expected in (('detected-after-action','1\n2\n6\n7\n3\n'),('new-target','1\n2\n8\n6\n7\n3\n'),('target-vanishes','1\n2\n8\n6\n3\n')):
            with self.subTest(mode=mode):
                output,done,commands,_=self.run_case(mode,enabled=True,mode=mode)
                self.assertEqual(done.returncode,0,done.stderr);self.assertEqual(commands.read_text(),expected)
                result=json.loads((output/'result.json').read_text());self.assertFalse(result['searchFallbackStarted']);self.assertEqual(result['handoff'],mode!='target-vanishes')
                self.assertEqual([x['command'] for x in map(json.loads,(output/'search-requests.jsonl').read_text().splitlines())],list(map(int,expected.split())))

    def test_bad_search_replies_never_write_a_success_result(self):
        for mode in ('stale','bad-ack','bad-owner','valid-image','nonblank','bad-drive','eof','missing-frame','missing-joints','changed-joints','malformed-joints','bad-sequence','ack2-no-target'):
            with self.subTest(mode=mode):
                output,done,commands,_=self.run_case('bad-'+mode,enabled=True,mode=mode)
                self.assertNotEqual(done.returncode,0,done.stdout);self.assertFalse((output/'result.json').exists());self.assertEqual(commands.read_text(),'1\n2\n8\n')

    def test_search_and_guarded_rescan_are_mutually_exclusive(self):
        output,done,commands,_=self.run_case('both',enabled=True,rescan=True)
        self.assertNotEqual(done.returncode,0);self.assertFalse((output/'result.json').exists());self.assertFalse(commands.exists())

    def test_request_journal_write_failure_stops_before_send_or_poll(self):
        output,done,commands,_=self.run_case('journal-failure',enabled=True,binary='journal-fail')
        self.assertNotEqual(done.returncode,0);self.assertIn('cannot write search request intent',done.stderr)
        self.assertEqual(commands.read_text(),'1\n2\n');self.assertFalse((output/'result.json').exists())
        intents=[json.loads(x) for x in (output/'search-requests.jsonl').read_text().splitlines()]
        self.assertEqual([x['command'] for x in intents],[1,2])

    def test_external_watchdog_timeout_does_not_create_result(self):
        output=self.root/'external-timeout';commands=self.root/'external-timeout.commands';actor=self.root/'external-timeout.actor'
        env=dict(os.environ,PUPPYBOT_PHYSICAL_NAV_LIMIT='1',PUPPYBOT_PHYSICAL_POLL_LIMIT='1',PUPPYBOT_PHYSICAL_SEARCH_FALLBACK='1',
                 SEARCH_TEST_VISIBLE='0',SEARCH_TEST_MODE='hang',SEARCH_TEST_COMMANDS=str(commands),PUPPY_TEST_ACTOR=str(actor))
        proc=subprocess.Popen([str(self.root/'client-candidate'),str(self.simulator),str(self.model),str(self.case),str(self.environment),str(output),'--allow-zero-contact'],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
        try:
            with self.assertRaises(subprocess.TimeoutExpired):proc.communicate(timeout=2)
            self.assertFalse((output/'result.json').exists());self.assertEqual(commands.read_text(),'1\n2\n8\n')
        finally:
            if proc.poll() is None:os.killpg(proc.pid,signal.SIGKILL)
            proc.communicate(timeout=5)

    def test_accelerated_internal_stream_timeout_has_no_result_or_poll(self):
        output,done,commands,_=self.run_case('internal-timeout',enabled=True,mode='hang',binary='internal-timeout')
        self.assertNotEqual(done.returncode,0);self.assertIn('local process stream timed out',done.stderr)
        self.assertEqual(commands.read_text(),'1\n2\n8\n');self.assertFalse((output/'result.json').exists())


if __name__=='__main__':unittest.main()
