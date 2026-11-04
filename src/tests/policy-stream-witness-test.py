#!/usr/bin/env python3
"""CPU-only local-socket and adversarial policy-witness tests."""
import base64
import hashlib
import importlib.util
import json
import os
import socket
import signal
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
WITNESS=ROOT/'flex/tests/policy-stream-witness.py'
spec=importlib.util.spec_from_file_location('auditor',ROOT/'flex/tests/audit-policy-stream-witness.py')
auditor=importlib.util.module_from_spec(spec);spec.loader.exec_module(auditor)


def read(sock,n):
    data=b''
    while len(data)<n:
        part=sock.recv(n-len(data))
        if not part:raise EOFError()
        data+=part
    return data


class WitnessTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.model=self.root/'model';self.model.mkdir();kernels=self.model/'kernels';kernels.mkdir()
        (self.model/'weights.bin').write_bytes(b'weights')
        policy=self.model/'policy';policy.write_text('''#!/usr/bin/python3
import os,struct,time
if os.environ.get('WITNESS_STUB_PIDFILE'):open(os.environ['WITNESS_STUB_PIDFILE'],'w').write(str(os.getpid()))
os.write(3,b'VCPOL001')
def read(n):
 data=b''
 while len(data)<n:
  part=os.read(3,n-len(data))
  if not part:
   if data:raise EOFError()
   return None
  data+=part
 return data
while True:
 data=read((21168+7+128)*4)
 if data is None:break
 if os.environ.get('WITNESS_STUB_MODE')=='partial':os.write(3,b'x');break
 if os.environ.get('WITNESS_STUB_MODE')=='hang':time.sleep(30)
 os.write(3,bytes(520))
''');policy.chmod(0o755)
        hashes={}
        for i in range(5):
            path=kernels/f'kernel{i}';path.write_bytes(str(i).encode());hashes[path.name]=auditor.sha(path)
        (self.model/'receipt.json').write_text(json.dumps({'binarySHA256':auditor.sha(policy),'weightsSHA256':auditor.sha(self.model/'weights.bin'),'kernels':hashes}))
        self.journal=self.root/'witness.jsonl';self.actor=self.root/'actor.bin';self.status=self.root/'supervisor.json'
        self.status.write_text(json.dumps({'clientExit':0,'timedOut':False,'remainingWorkersTerminated':False,'signal':None,'processGroup':123}))
        paths={key:str(self.root/key) for key in ('control','simulator','case','environment','supervisor')}
        for path in paths.values():Path(path).write_bytes(b'fixture')
        paths.update(model=str(self.model),witness=str(WITNESS))
        files={str(path):auditor.sha(path) for path in [*(Path(paths[key]) for key in ('control','simulator','case','environment','witness','supervisor')),self.model/'policy',self.model/'weights.bin',self.model/'receipt.json',*(self.model/'kernels').iterdir()]}
        self.registration=self.root/'registration.json';self.registration.write_text(json.dumps({'schema':'puppybot.policy-witness-registration.v1','paths':paths,'files':files,'intendedControlArgvBase64':[base64.b64encode(os.fsencode(paths['control'])).decode()]}))

    def run_proxy(self,mode='',partial_request=False):
        parent,child=socket.socketpair();parent.settimeout(8);env=dict(os.environ,WITNESS_STUB_MODE=mode,WITNESS_STUB_PIDFILE=str(self.root/'stub.pid'))
        args=[sys.executable,'-I',str(WITNESS),'--fd',str(child.fileno()),'--policy',str(self.model/'policy'),
              '--policy-sha256',auditor.sha(self.model/'policy'),'--weights',str(self.model/'weights.bin'),
              '--weights-sha256',auditor.sha(self.model/'weights.bin'),'--kernels',str(self.model/'kernels'),
              '--receipt',str(self.model/'receipt.json'),'--journal',str(self.journal),'--timeout','3']
        proc=subprocess.Popen(args,pass_fds=(child.fileno(),),env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        child.close();inputs=[];outputs=[]
        try:
            self.assertEqual(read(parent,8),b'VCPOL001')
            for i in range(2):
                data=bytes([i+1])*auditor.INPUT;inputs.append(data)
                parent.sendall(data[:100] if partial_request else data)
                if partial_request:break
                try:outputs.append(read(parent,auditor.OUTPUT))
                except EOFError:break
            parent.shutdown(socket.SHUT_WR)
            stdout,stderr=proc.communicate(timeout=10)
            return proc.returncode,stderr,inputs,outputs
        finally:
            parent.close()
            if proc.poll() is None:proc.kill();proc.wait()

    def actor_file(self,inputs,outputs):
        n=len(inputs);record_bytes=24+21168+auditor.INPUT+auditor.OUTPUT+8
        data=bytearray(struct.pack('<8s6q',b'PBATST01',1,42,n,21168,128,record_bytes))
        for i,(incoming,outgoing) in enumerate(zip(inputs,outputs)):
            data.extend(struct.pack('<3q',i,i+1,(i+1)*10));data.extend(bytes(21168));data.extend(incoming);data.extend(outgoing);data.extend(outgoing[:8])
        data.extend(struct.pack('<8sq',b'PBDONE01',n));self.actor.write_bytes(data)

    def test_real_socket_stream_and_negative_mutations(self):
        code,err,inputs,outputs=self.run_proxy();self.assertEqual(code,0,err.decode());self.assertEqual(len(outputs),2)
        self.actor_file(inputs,outputs);report=auditor.audit(self.journal,self.actor,self.model,self.status,self.registration)
        self.assertEqual((report['status'],report['frames']),('stream_digests_consistent_unverified_provenance',2))
        self.assertEqual(report['supervisorStatus'],'caller_supplied_unverified');self.assertEqual(report['registrationTiming'],'unverified')
        events=[json.loads(line) for line in self.journal.read_text().splitlines()]
        mutations=[]
        mutations.append(events[:-1]);mutations.append([events[0],events[2],events[1],events[-1]])
        mutations.append([events[0],events[1],events[1],events[-1]])
        changed=[dict(v) for v in events];changed[1]['inputSHA256']='0'*64;mutations.append(changed)
        changed=[dict(v) for v in events];changed[-1]['policyExit']=1;mutations.append(changed)
        for bad in mutations:
            self.journal.write_text(''.join(json.dumps(x)+'\n' for x in bad))
            with self.assertRaises(ValueError):auditor.audit(self.journal,self.actor,self.model,self.status,self.registration)
        self.journal.write_text(''.join(json.dumps(x)+'\n' for x in events))
        content=bytearray(self.actor.read_bytes());content[56+24+21168]^=1;self.actor.write_bytes(content)
        with self.assertRaisesRegex(ValueError,'stream mismatch'):auditor.audit(self.journal,self.actor,self.model,self.status,self.registration)

    def test_partial_policy_output_and_request_have_no_complete_footer(self):
        for mode,partial in (('partial',False),('',True)):
            with self.subTest(mode=mode,partial=partial):
                if self.journal.exists():self.journal.unlink()
                code,_,_,_=self.run_proxy(mode,partial);self.assertNotEqual(code,0)
                lines=self.journal.read_text().splitlines()
                self.assertFalse(any(json.loads(x).get('footer')=='complete' for x in lines))

    def test_signal_after_fork_and_repeated_signal_during_cleanup(self):
        # Test-only harness injects a signal exactly after fork returns, then
        # repeats it while the witness kills its child. No hook is shipped in
        # the witness protocol itself.
        harness=self.root/'signal-harness.py';pidfile=self.root/'child.pid'
        harness.write_text("""import importlib.util,os,signal,sys
spec=importlib.util.spec_from_file_location('witness',os.environ['TEST_WITNESS']);w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)
real_fork=os.fork;real_kill=os.kill
def fork_hook():
 pid=real_fork()
 if pid>0:
  open(os.environ['TEST_PIDFILE'],'w').write(str(pid))
  real_kill(os.getpid(),signal.SIGTERM)
 return pid
def kill_hook(pid,sig):
 if pid!=os.getpid():
  real_kill(os.getpid(),signal.SIGTERM);real_kill(os.getpid(),signal.SIGTERM)
 return real_kill(pid,sig)
w.os.fork=fork_hook;w.os.kill=kill_hook
try:w.main()
except (OSError,ValueError,EOFError,TimeoutError):sys.exit(1)
""")
        parent,child=socket.socketpair();env=dict(os.environ,TEST_WITNESS=str(WITNESS),TEST_PIDFILE=str(pidfile))
        args=[sys.executable,'-I',str(harness),'--fd',str(child.fileno()),'--policy',str(self.model/'policy'),
              '--policy-sha256',auditor.sha(self.model/'policy'),'--weights',str(self.model/'weights.bin'),
              '--weights-sha256',auditor.sha(self.model/'weights.bin'),'--kernels',str(self.model/'kernels'),
              '--receipt',str(self.model/'receipt.json'),'--journal',str(self.journal),'--timeout','3']
        proc=subprocess.Popen(args,pass_fds=(child.fileno(),),env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE);child.close()
        try:
            _,error=proc.communicate(timeout=10);self.assertNotEqual(proc.returncode,0,error.decode())
            pid=int(pidfile.read_text())
            with self.assertRaises(ProcessLookupError):os.kill(pid,0)
            self.assertFalse(any(json.loads(x).get('footer')=='complete' for x in self.journal.read_text().splitlines()))
        finally:
            parent.close()
            if proc.poll() is None:proc.kill();proc.wait()

    def test_timeout_kills_direct_child_and_leaves_no_footer(self):
        code,_,_,_=self.run_proxy('hang');self.assertNotEqual(code,0)
        child=int((self.root/'stub.pid').read_text())
        with self.assertRaises(ProcessLookupError):os.kill(child,0)
        self.assertFalse(any(json.loads(x).get('footer')=='complete' for x in self.journal.read_text().splitlines()))

    def test_unclean_supervisor_and_changed_registration_are_rejected(self):
        code,err,inputs,outputs=self.run_proxy();self.assertEqual(code,0,err.decode());self.actor_file(inputs,outputs)
        status=json.loads(self.status.read_text());status['timedOut']=True;self.status.write_text(json.dumps(status))
        with self.assertRaisesRegex(ValueError,'supervisor'):auditor.audit(self.journal,self.actor,self.model,self.status,self.registration)
        status['timedOut']=False;self.status.write_text(json.dumps(status))
        registration=json.loads(self.registration.read_text());registration['intendedControlArgvBase64']=['AA=='];self.registration.write_text(json.dumps(registration))
        with self.assertRaisesRegex(ValueError,'invalid intended argv bytes'):auditor.audit(self.journal,self.actor,self.model,self.status,self.registration)

    def test_receipt_change_rejected(self):
        code,err,inputs,outputs=self.run_proxy();self.assertEqual(code,0,err.decode());self.actor_file(inputs,outputs)
        (self.model/'weights.bin').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'registered input changed'):auditor.audit(self.journal,self.actor,self.model,self.status,self.registration)


if __name__=='__main__':unittest.main()
