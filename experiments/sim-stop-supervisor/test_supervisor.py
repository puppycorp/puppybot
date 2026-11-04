#!/usr/bin/env python3
"""CPU-only copied-client plus supervised fake simulator/policy tests."""
import hashlib
import importlib.util
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


prepare=load('guard_build',HERE/'prepare.py')
supervisor=load('guard_supervisor',HERE/'supervisor.py')
failure_tests=load('failure_fixtures',ROOT/'experiments/physical-failure-report/test.py')


class SupervisorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='puppy-sim-stop-');cls.root=Path(cls.temp.name)
        cls.build=cls.root/'guard-build';prepare.prepare(cls.build)
        cls.baseline=cls.root/'baseline-build';prepare.failure.prepare(cls.baseline)
        cls.model=cls.root/'model';cls.model.mkdir();(cls.model/'kernels').mkdir();(cls.model/'weights.bin').write_bytes(b'weights')
        policy=failure_tests.POLICY.replace('0.0,0.2,*([0.0]*128)', '0.0,(float("nan") if os.environ.get("PUPPY_TEST_NAN")=="1" else 0.2),*([0.0]*128)')
        (cls.model/'policy').write_text(policy);(cls.model/'policy').chmod(0o755)
        kernels={}
        for i in range(5):
            path=cls.model/'kernels'/str(i);path.write_text('kernel'+str(i));kernels[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
        sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
        (cls.model/'receipt.json').write_text(json.dumps({'weightsSHA256':sha(cls.model/'weights.bin'),'binarySHA256':sha(cls.model/'policy'),'memoryWidth':128,'kernels':kernels}))
        sim=failure_tests.SIMULATOR.replace('s=socket.socket(fileno=3);step=100;', 's=socket.socket(fileno=int(sys.argv[sys.argv.index("--agent-fd")+1]));step=100;')
        sim=sim.replace('from pathlib import Path\n','from pathlib import Path\nif os.environ.get("PUPPY_TEST_MODE")=="timeout" and os.environ.get("PUPPY_TEST_CHILD_PID"):\n Path(os.environ["PUPPY_TEST_CHILD_PID"]).write_text(str(os.getpid()))\nif os.environ.get("PUPPY_TEST_MODE")=="escape":\n import subprocess\n p=subprocess.Popen([sys.executable,"-c","import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)"],start_new_session=True)\n Path(os.environ["PUPPY_TEST_CHILD_PID"]).write_text(str(p.pid))\n')
        cls.simulator=cls.root/'simulator';cls.simulator.write_text(sim);cls.simulator.chmod(0o755)
        cls.case=cls.root/'case.json';cls.case.write_text('{}');cls.environment=cls.root/'environment.bin';cls.environment.write_bytes(b'env')

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def env(self,name,mode='normal',visible=False,nan=False):
        return dict(os.environ,PUPPY_TEST_MODE=mode,PUPPY_TEST_COMMANDS=str(self.root/(name+'.commands')),
                    PUPPY_TEST_ACTOR=str(self.root/(name+'.actor')),PUPPY_TEST_VISIBLE='1' if visible else '0',
                    PUPPY_TEST_NAN='1' if nan else '0',PUPPYBOT_PHYSICAL_NAV_LIMIT='3',PUPPYBOT_PHYSICAL_POLL_LIMIT='1')

    def launch(self,name,mode='normal',visible=False,nan=False,io=2):
        output=self.root/name;env=self.env(name,mode,visible,nan)
        result=supervisor.launch(output,self.build/'client',self.simulator,self.model,self.case,self.environment,env,
                                 io_seconds=io,stop_seconds=.5,wall_seconds=8)
        return output,result,env

    def test_normal_copied_client_matches_direct_socket_path(self):
        output,result,env=self.launch('normal')
        self.assertEqual(result['status'],'client_stop_acknowledged');self.assertTrue(result['stopAcknowledged'])
        self.assertFalse(result['stopAttempted']);self.assertEqual(result['physicalStop'],'unverified')
        direct=self.root/'direct';env=dict(env,PUPPYBOT_SIM_FAILURE_REPORT='1',PUPPY_TEST_COMMANDS=str(self.root/'direct.commands'),PUPPY_TEST_ACTOR=str(self.root/'direct.actor'))
        done=subprocess.run([str(self.baseline/'candidate'),str(self.simulator),str(self.model),str(self.case),str(self.environment),str(direct),'--allow-zero-contact'],cwd=ROOT,env=env,capture_output=True,text=True,timeout=15)
        self.assertEqual(done.returncode,0,done.stderr)
        for name in ('result.json','physical-agent.jsonl','actors/actor-1.rgb','actors/actor-1.feedback','actors/actor-1.hidden','actors/actor-1.action'):
            self.assertEqual((output/'client'/name).read_bytes(),(direct/name).read_bytes(),name)
        self.assertEqual((self.root/'normal.commands').read_text(),(self.root/'direct.commands').read_text())
        self.assertEqual((self.root/'normal.actor').read_bytes(),(self.root/'direct.actor').read_bytes())

    def test_failed_policy_causes_fresh_supervisor_stop(self):
        output,result,_=self.launch('nan-policy',nan=True)
        self.assertEqual(result['status'],'failed');self.assertTrue(result['stopAttempted']);self.assertTrue(result['stopAcknowledged'])
        self.assertEqual(result['stopCommandSource'],'supervisor');self.assertEqual(result['physicalStop'],'unverified')
        self.assertNotEqual(result['clientExit'],0);self.assertEqual((self.root/'nan-policy.commands').read_text(),'1\n3\n')
        failure=json.loads((output/'client/failure.json').read_text())
        self.assertFalse(failure['stopCommandAcknowledged']);self.assertEqual(failure['physicalStop'],'unverified')

    def test_collector_failure_and_stalled_inflight_are_unverified(self):
        output,result,_=self.launch('ack6',mode='ack6',visible=True)
        self.assertFalse(result['stopAttempted']);self.assertFalse(result['stopAcknowledged']);self.assertTrue(result['peerReportedZeroDrive'])
        self.assertEqual((self.root/'ack6.commands').read_text(),'1\n6\n7\n')
        self.assertFalse(json.loads((output/'client/failure.json').read_text())['stopCommandAcknowledged'])
        _,result,_=self.launch('stalled',mode='timeout',visible=True,io=.3)
        self.assertIn('in-flight exchange unverified',result['reason']);self.assertFalse(result['stopAttempted']);self.assertFalse(result['stopAcknowledged'])
        self.assertEqual((self.root/'stalled.commands').read_text(),'1\n6\n7\n')

    def test_disabled_cli_and_no_overwrite(self):
        done=subprocess.run([sys.executable,'-I',str(HERE/'supervisor.py')],capture_output=True,text=True,timeout=10)
        self.assertNotEqual(done.returncode,0);self.assertIn('Disabled',done.stderr)
        output=self.root/'existing';output.mkdir();(output/'keep').write_text('preserve')
        with self.assertRaises(FileExistsError):supervisor.launch(output,self.build/'client',self.simulator,self.model,self.case,self.environment,self.env('existing'))
        self.assertEqual((output/'keep').read_text(),'preserve')

    def test_dedicated_process_guard_rejects_children_and_threads_before_output(self):
        child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])
        output=self.root/'unrelated-child'
        try:
            with self.assertRaisesRegex(RuntimeError,'without existing children'):
                supervisor.launch(output,self.build/'client',self.simulator,self.model,self.case,self.environment,self.env('guard-child'))
            self.assertFalse(output.exists());self.assertIsNone(child.poll())
        finally:child.terminate();child.wait()
        event=threading.Event();thread=threading.Thread(target=event.wait);thread.start()
        try:
            with self.assertRaisesRegex(RuntimeError,'single-thread'):
                supervisor.launch(output,self.build/'client',self.simulator,self.model,self.case,self.environment,self.env('guard-thread'))
            self.assertFalse(output.exists())
        finally:event.set();thread.join()

    def test_escaped_stubborn_child_is_cleaned_and_outer_fails_closed(self):
        output=self.root/'escaped';pidfile=self.root/'escaped.pid';env=dict(self.env('escaped',mode='escape'),PUPPY_TEST_CHILD_PID=str(pidfile),UNKNOWN_SECRET='not-for-evidence')
        with self.assertRaisesRegex(RuntimeError,'outer supervisor failed'):
            supervisor.launch(output,self.build/'client',self.simulator,self.model,self.case,self.environment,env,io_seconds=2,stop_seconds=.5,wall_seconds=8)
        self.assertTrue(pidfile.exists());pid=int(pidfile.read_text());self.assertFalse(Path('/proc',str(pid)).exists())
        status=json.loads((output/'outer-monitor/supervisor-result.json').read_text())
        self.assertTrue(status['remainingWorkersTerminated'])
        launch=json.loads((output/'launch.json').read_text());self.assertNotIn('UNKNOWN_SECRET',str(launch))

    def test_repeated_signal_during_inflight_does_not_claim_stop_or_leave_simulator(self):
        output=self.root/'signaled';pidfile=self.root/'signaled.pid';env=dict(self.env('signaled',mode='timeout',visible=True),PUPPY_TEST_CHILD_PID=str(pidfile))
        arguments=[str(output),str(self.build/'client'),str(self.simulator),str(self.model),str(self.case),str(self.environment),env]
        code=('import importlib.util,json,sys;'
              's=importlib.util.spec_from_file_location("m",sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);'
              'm.launch(*json.loads(sys.argv[2]),io_seconds=5,stop_seconds=.5,wall_seconds=12)')
        proc=subprocess.Popen([sys.executable,'-I','-c',code,str(HERE/'supervisor.py'),json.dumps(arguments)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            until=time.monotonic()+8;commands=self.root/'signaled.commands'
            while time.monotonic()<until and (not commands.exists() or commands.read_text()!='1\n6\n7\n'):time.sleep(.02)
            self.assertTrue(commands.exists());self.assertEqual(commands.read_text(),'1\n6\n7\n')
            os.kill(proc.pid,signal.SIGTERM);os.kill(proc.pid,signal.SIGTERM)
            proc.communicate(timeout=15);self.assertNotEqual(proc.returncode,0)
            status=json.loads((output/'outer-monitor/supervisor-result.json').read_text());self.assertEqual(status['signal'],signal.SIGTERM)
            self.assertFalse(Path('/proc',pidfile.read_text()).exists())
            if (output/'session.json').exists():
                session=json.loads((output/'session.json').read_text());self.assertFalse(session['stopAcknowledged']);self.assertEqual(session['physicalStop'],'unverified')
        finally:
            if proc.poll() is None:proc.kill();proc.communicate()


if __name__=='__main__':unittest.main()
