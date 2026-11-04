#!/usr/bin/env python3
"""CPU-only launch, telemetry and pinning regressions; no GPU."""
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('pilot_launcher',HERE/'launcher.py')
launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)


class LauncherTest(unittest.TestCase):
    def test_real_dependency_inventory_resolves_before_launch(self):
        pitch=launcher.ROOT/'build/flex/sim/levels-v2/pitch82'
        dependencies=launcher.required(pitch/'sim-stop-pilot-client-v1',
            pitch/'physical-handoff-hint-build-v3/inputs/simulator',pitch/'more1-s0',
            pitch/'physical-hybrid-visible-trial/case.json',
            launcher.ROOT/'build/flex/sim/environments/apartment/apartment.bin')
        self.assertIn(launcher.ROOT/'datasets/visual-control/chase-v1/levels/supervise-selection.py',dependencies)
        self.assertTrue(all(path.is_file() for path in dependencies))

    def test_disabled_entrypoint(self):
        result=subprocess.run([sys.executable,'-I',str(HERE/'launcher.py')],capture_output=True,text=True,timeout=5)
        self.assertNotEqual(result.returncode,0);self.assertIn('Disabled',result.stderr)

    def test_pair_order_pinning_and_final_audit(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source';source.write_bytes(b'input');calls=[]
            def arm(path,build,sim,model,case,environment,fault,log):calls.append((path.name,fault))
            with mock.patch.object(launcher,'required',return_value=[source]),mock.patch.object(launcher,'check_build'),\
                 mock.patch.object(launcher.shutil,'disk_usage',return_value=SimpleNamespace(free=40*launcher.telemetry.GIB)),\
                 mock.patch.object(launcher.telemetry,'baseline'),mock.patch.object(launcher.telemetry,'sample',return_value={'freeBytes':8*launcher.telemetry.GIB}),\
                 mock.patch.object(launcher,'monitor_arm',side_effect=arm),mock.patch.object(launcher.audit,'validate_control',return_value=[(1,b''),(2,b''),(5,b'reset')]),\
                 mock.patch.object(launcher.audit,'control_receipt',return_value={'status':'valid_control'}),mock.patch.object(launcher.audit,'verify_control_receipt'),mock.patch.object(launcher.audit,'audit',return_value={'status':'diagnostic'}):
                self.assertEqual(launcher.worker(root,'build','sim','model','case','environment')['status'],'diagnostic')
            self.assertEqual(calls,[('control','none'),('fault','after-reset')]);self.assertTrue((root/'audit.json').exists())
            self.assertEqual(json.loads((root/'inputs.json').read_text())['files'][str(source)],launcher.digest(source))

    def test_input_change_aborts_before_second_arm(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source';source.write_bytes(b'input');calls=[]
            def arm(path,*args):calls.append(path.name);source.write_bytes(b'changed')
            with mock.patch.object(launcher,'required',return_value=[source]),mock.patch.object(launcher,'check_build'),\
                 mock.patch.object(launcher.shutil,'disk_usage',return_value=SimpleNamespace(free=40*launcher.telemetry.GIB)),\
                 mock.patch.object(launcher.telemetry,'baseline'),mock.patch.object(launcher,'monitor_arm',side_effect=arm),mock.patch.object(launcher.audit,'validate_control',return_value=[(1,b''),(2,b''),(5,b'reset')]),\
                 mock.patch.object(launcher.audit,'control_receipt',return_value={'status':'valid_control'}):
                with self.assertRaisesRegex(ValueError,'inputs changed'):launcher.worker(root,'build','sim','model','case','environment')
            self.assertEqual(calls,['control']);self.assertFalse((root/'audit.json').exists())

    def test_clean_supervisor_with_failed_control_never_launches_fault(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source';source.write_bytes(b'input');calls=[]
            def arm(path,*args):
                calls.append(path.name);path.mkdir();(path/'outer-monitor').mkdir()
                (path/'outer-monitor/supervisor-result.json').write_text(json.dumps({'clientExit':0,'timedOut':False,'signal':None,'remainingWorkersTerminated':False,'processGroup':123}))
                (path/'session.json').write_text(json.dumps({'status':'failed','physicalStop':'unverified','delivery':'unverified','reason':'stream deadline'}))
                (path/'protocol.bin').write_bytes(b'')
            with mock.patch.object(launcher,'required',return_value=[source]),mock.patch.object(launcher,'check_build'),\
                 mock.patch.object(launcher.shutil,'disk_usage',return_value=SimpleNamespace(free=40*launcher.telemetry.GIB)),\
                 mock.patch.object(launcher.telemetry,'baseline'),mock.patch.object(launcher,'monitor_arm',side_effect=arm):
                with self.assertRaisesRegex(ValueError,'missing reset'):launcher.worker(root,'build','sim','model','case','environment')
            self.assertEqual(calls,['control']);self.assertFalse((root/'fault').exists());self.assertFalse((root/'audit.json').exists())
            self.assertEqual(json.loads((root/'control-audit.json').read_text())['status'],'censored')

    def test_changed_control_session_censors_before_fault(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source';source.write_bytes(b'input');calls=[];pin_calls=[];real_pins=launcher.pins
            def arm(path,*args):
                calls.append(path.name);path.mkdir();(path/'outer-monitor').mkdir()
                (path/'protocol.bin').write_bytes(b'protocol');(path/'session.json').write_text('{"status":"ok"}')
                (path/'outer-monitor/supervisor-result.json').write_text('{"clientExit":0}')
            def pins(paths):
                pin_calls.append(1)
                if len(pin_calls)==3:(root/'control/session.json').write_text('{"status":"ok","extra":"changed"}')
                return real_pins(paths)
            with mock.patch.object(launcher,'required',return_value=[source]),mock.patch.object(launcher,'pins',side_effect=pins),mock.patch.object(launcher,'check_build'),\
                 mock.patch.object(launcher.shutil,'disk_usage',return_value=SimpleNamespace(free=40*launcher.telemetry.GIB)),\
                 mock.patch.object(launcher.telemetry,'baseline'),mock.patch.object(launcher,'monitor_arm',side_effect=arm),\
                 mock.patch.object(launcher.audit,'validate_control',return_value=[(1,b''),(2,b''),(5,b'reset')]):
                with self.assertRaisesRegex(ValueError,'control evidence changed'):launcher.worker(root,'build','sim','model','case','environment')
            self.assertEqual(calls,['control']);self.assertFalse((root/'fault').exists());self.assertFalse((root/'audit.json').exists())

    def test_low_or_lost_telemetry_terminates_worker(self):
        for reading in ({'freeBytes':1},RuntimeError('telemetry unavailable')):
            with self.subTest(reading=reading),tempfile.TemporaryDirectory() as temp:
                process=mock.Mock(pid=42,returncode=-15);process.poll.side_effect=[None,None];process.wait.return_value=-15
                sample=mock.Mock(side_effect=reading) if isinstance(reading,Exception) else mock.Mock(return_value=reading)
                with mock.patch.object(launcher.subprocess,'Popen',return_value=process),mock.patch.object(launcher.os,'pidfd_open',return_value=9),\
                     mock.patch.object(launcher.os,'close'),mock.patch.object(launcher.signal,'pidfd_send_signal') as send,\
                     mock.patch.object(launcher.telemetry,'sample',sample):
                    with self.assertRaises(RuntimeError):launcher.monitor_arm(Path(temp)/'arm','build','sim','model','case','environment','none',io.StringIO())
                send.assert_called_once_with(9,launcher.signal.SIGTERM);process.wait.assert_called_once()

    def test_pidfd_open_failure_terminates_spawned_child(self):
        with tempfile.TemporaryDirectory() as temp:
            process=mock.Mock(pid=42,returncode=-15);process.poll.return_value=None
            with mock.patch.object(launcher.subprocess,'Popen',return_value=process),mock.patch.object(launcher.os,'pidfd_open',side_effect=OSError('unavailable')):
                with self.assertRaises(OSError):launcher.monitor_arm(Path(temp)/'arm','build','sim','model','case','env','none',io.StringIO())
            process.terminate.assert_called_once();process.wait.assert_called_once()

    def test_monitor_constructs_fixed_startup_and_io_deadlines(self):
        with tempfile.TemporaryDirectory() as temp:
            process=mock.Mock(pid=42,returncode=0);process.poll.return_value=0
            with mock.patch.object(launcher.subprocess,'Popen',return_value=process) as spawn,mock.patch.object(launcher.os,'pidfd_open',return_value=9),mock.patch.object(launcher.os,'close'):
                launcher.monitor_arm(Path(temp)/'arm','build','sim','model','case','env','none',io.StringIO())
            command=spawn.call_args.args[0]
            self.assertIn('io_seconds=5,stop_seconds=2,wall_seconds=60,startup_seconds=25',command[3]);self.assertEqual(command[-1],'none')

    def test_existing_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'keep').write_text('keep')
            with self.assertRaises(FileExistsError):launcher.launch(root,'build','sim','model','case','env')
            self.assertEqual((root/'keep').read_text(),'keep')

    def test_disk_check_includes_output_workspace_and_home(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);seen=[]
            def usage(path):
                seen.append(path);return SimpleNamespace(free=(33 if path==Path.home() else 40)*launcher.telemetry.GIB)
            with mock.patch.object(launcher.shutil,'disk_usage',side_effect=usage):
                self.assertEqual(launcher.free_disk(root),33*launcher.telemetry.GIB)
            self.assertEqual(seen,[root,launcher.ROOT,Path.home()])

    def test_relative_inputs_are_resolved_before_worker_changes_cwd(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);old=Path.cwd();captured=[]
            def supervise(command,outer,env,seconds):
                captured.extend(command);(root/'output/audit.json').write_text('{"status":"diagnostic"}')
                return {'clientExit':0,'timedOut':False,'signal':None,'remainingWorkersTerminated':False}
            try:
                os.chdir(root)
                with mock.patch.object(launcher,'LOCK',root/'lock'),mock.patch.object(launcher.supervisor,'require_dedicated_process'),\
                     mock.patch.object(launcher,'free_disk',return_value=40*launcher.telemetry.GIB),mock.patch.object(launcher,'required',return_value=[]),\
                     mock.patch.object(launcher,'check_build'),mock.patch.object(launcher.supervisor.hidden,'supervise',side_effect=supervise):
                    launcher.launch('output','build','sim','model','case','environment')
            finally:os.chdir(old)
            self.assertEqual(captured[6:],[str(root/p) for p in ('build','sim','model','case','environment')])

    def test_nested_abort_cleans_detached_child_without_touching_sibling(self):
        # The outer subreaper runs in its own process; the unrelated sibling
        # belongs to this test and must not be adopted, reaped or signaled.
        for mode in ('low-gpu','lost-gpu','low-disk','lost-disk','pidfd'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);pidfile=root/'escaped.pid';outer=root/'outer';outer.mkdir()
                worker=root/'worker.py'
                worker.write_text('''import importlib.util,os,sys,time,subprocess\nfrom pathlib import Path\nfrom types import SimpleNamespace\ns=importlib.util.spec_from_file_location("m",sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)\nroot=Path(sys.argv[2]);mode=sys.argv[3];pidfile=root/"escaped.pid";original=subprocess.Popen\nchild="import os,signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);open(%r,\\"w\\").write(str(os.getpid()));time.sleep(30)" % str(pidfile)\nparent="import subprocess,sys,time;subprocess.Popen([sys.executable,\\"-c\\",%r],start_new_session=True);time.sleep(30)" % child\ndef spawn(*args,**kwargs):return original([sys.executable,"-I","-c",parent],**kwargs)\ndef ready():\n end=time.monotonic()+5\n while not pidfile.exists() and time.monotonic()<end:time.sleep(.01)\n if not pidfile.exists():raise RuntimeError("child did not start")\ndef sample(*args):\n ready()\n if mode=="lost-gpu":raise RuntimeError("telemetry lost")\n return {"freeBytes":1 if mode=="low-gpu" else 8*m.telemetry.GIB}\ndef disk(*args):\n ready()\n if mode=="lost-disk":raise OSError("disk lost")\n return SimpleNamespace(free=(1 if mode=="low-disk" else 40*m.telemetry.GIB))\ndef pidfd(pid):\n ready()\n if mode=="pidfd":raise OSError("pidfd lost")\n return os.pidfd_open(pid)\nm.subprocess.Popen=spawn;m.telemetry.sample=sample;m.shutil.disk_usage=disk\nif mode=="pidfd":m.os.pidfd_open=pidfd\nwith (root/"telemetry").open("w") as log:m.monitor_arm(root/"arm","build","sim","model","case","env","none",log)\n''')
                driver=root/'driver.py'
                driver.write_text('''import importlib.util,sys\nfrom pathlib import Path\ns=importlib.util.spec_from_file_location("m",sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)\nroot=Path(sys.argv[2]);m.supervisor.hidden.supervise([sys.executable,"-I",str(root/"worker.py"),sys.argv[1],str(root),sys.argv[3]],root/"outer",{"PATH":"/usr/bin:/bin","HOME":"/tmp"},15)\n''')
                sibling=subprocess.Popen([sys.executable,'-I','-c','import time;time.sleep(60)'])
                try:
                    result=subprocess.run([sys.executable,'-I',str(driver),str(HERE/'launcher.py'),str(root),mode],capture_output=True,text=True,timeout=25)
                    self.assertEqual(result.returncode,0,result.stderr);self.assertTrue(pidfile.exists())
                    self.assertFalse(Path('/proc',pidfile.read_text()).exists());self.assertIsNone(sibling.poll())
                    status=json.loads((outer/'supervisor-result.json').read_text());self.assertNotEqual(status['clientExit'],0);self.assertTrue(status['remainingWorkersTerminated'])
                    self.assertFalse((root/'audit.json').exists())
                finally:sibling.terminate();sibling.wait()


if __name__=='__main__':unittest.main()
