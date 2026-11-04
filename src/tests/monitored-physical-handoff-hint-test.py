#!/usr/bin/env python3
"""CPU-only GPU-monitor lifecycle tests using synthetic telemetry."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

ROOT=Path(__file__).resolve().parents[2]
MODULE=ROOT/'flex/tests/monitored-physical-handoff-hint.py'
spec=importlib.util.spec_from_file_location('m',MODULE);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class GpuMonitorTest(unittest.TestCase):
    def test_positive_synthetic_worker_and_fixed_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp);process=mock.Mock(pid=123,returncode=0);process.poll.return_value=0
            with mock.patch.object(m,'require_disk'),mock.patch.object(m.telemetry,'baseline'),mock.patch.object(m.telemetry,'sample',return_value={'freeBytes':8*m.telemetry.GIB}),mock.patch.object(m.subprocess,'Popen',return_value=process) as spawn,mock.patch.object(m.os,'pidfd_open',return_value=456),mock.patch.object(m.os,'close'):
                m.monitor_worker(out)
            self.assertEqual(spawn.call_args.args[0],m.worker_command(out))
            self.assertEqual(json.loads((out/'gpu-monitor-result.json').read_text())['status'],'completed_diagnostic')
            self.assertEqual(m.worker_command(out)[-3:],[str(m.SUPERVISOR),str(out/'trial'),str(out/'process-monitor')])

    def test_baseline_failure_and_disabled_cli(self):
        with tempfile.TemporaryDirectory() as tmp,mock.patch.object(m,'require_disk'),mock.patch.object(m.telemetry,'baseline',side_effect=RuntimeError('low baseline')):
            with self.assertRaisesRegex(RuntimeError,'low baseline'):m.monitor_worker(Path(tmp))
            self.assertEqual(json.loads((Path(tmp)/'gpu-monitor-result.json').read_text())['status'],'failed')
        result=subprocess.run([sys.executable,'-I',str(MODULE)],capture_output=True,text=True,timeout=10)
        self.assertNotEqual(result.returncode,0);self.assertIn('Disabled',result.stderr)

    def test_outer_success_requires_both_monitor_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def supervise(command,outer,env,seconds):
                output=outer.parent;(output/'gpu-monitor-result.json').write_text('{"status":"completed_diagnostic"}')
                (output/'process-monitor').mkdir();(output/'process-monitor/result.json').write_text('{"status":"diagnostic_only","comparisonEligible":false}')
                return {'clientExit':0,'timedOut':False,'signal':None,'remainingWorkersTerminated':False}
            with mock.patch.object(m,'require_disk'),mock.patch.object(m.handoff.runner,'check'),mock.patch.object(m.handoff.runner.hidden,'supervise',side_effect=supervise):
                output=root/'first';report=m.launch(output)
                self.assertEqual(report['status'],'diagnostic_only')
                self.assertEqual(json.loads((output/'launch.json').read_text())['wallSeconds'],m.OUTER_SECONDS)
                with self.assertRaises(ValueError):m.launch(output)
            def failed(command,outer,env,seconds):return {'clientExit':1,'timedOut':False,'signal':None,'remainingWorkersTerminated':False}
            with mock.patch.object(m,'require_disk'),mock.patch.object(m.handoff.runner,'check'),mock.patch.object(m.handoff.runner.hidden,'supervise',side_effect=failed):
                with self.assertRaisesRegex(RuntimeError,'partial evidence'):m.launch(root/'failed')

    def test_nested_failure_cleanup_preserves_unrelated_process(self):
        child='import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)'
        worker=('import os,signal,subprocess,sys,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);'
                'p=subprocess.Popen([sys.executable,"-c",sys.argv[2]],start_new_session=True);'
                'open(sys.argv[1],"w").write(str(os.getpid())+" "+str(p.pid));time.sleep(30)')
        inner=textwrap.dedent('''
            import importlib.util,os,signal,subprocess,sys,time
            from pathlib import Path
            s=importlib.util.spec_from_file_location('m',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
            out=Path(sys.argv[2]);mode=sys.argv[3];pidfile=out/'workers.pid';original=m.subprocess.Popen
            def spawn(*a,**kw):return original([sys.executable,'-c',sys.argv[4],str(pidfile),sys.argv[5]],**kw)
            def ready():
                end=time.monotonic()+4
                while not pidfile.exists() and time.monotonic()<end:time.sleep(.01)
                if not pidfile.exists():raise RuntimeError('fixture worker did not start')
            def sample(log,phase):
                ready()
                if mode=='death':os.kill(os.getpid(),signal.SIGKILL)
                if mode=='telemetry':raise RuntimeError('GPU telemetry unavailable')
                return {'freeBytes':m.telemetry.GIB}
            pidfd=os.pidfd_open
            def openfd(pid):
                if mode=='pidfd':ready();raise OSError('pidfd failure')
                return pidfd(pid)
            wait=subprocess.Popen.wait
            def shortwait(self,timeout=None):return wait(self,timeout=min(timeout,.1) if timeout is not None else None)
            subprocess.Popen.wait=shortwait;m.require_disk=lambda p:None;m.telemetry.baseline=lambda log:None
            m.telemetry.sample=sample;m.subprocess.Popen=spawn;m.os.pidfd_open=openfd
            m.monitor_worker(out)
        ''')
        outer=textwrap.dedent('''
            import importlib.util,json,os,sys
            from pathlib import Path
            s=importlib.util.spec_from_file_location('h',sys.argv[1]);h=importlib.util.module_from_spec(s);s.loader.exec_module(h)
            r=h.supervise([sys.executable,'-c',sys.argv[3],sys.argv[4],sys.argv[2],sys.argv[5],sys.argv[6],sys.argv[7]],Path(sys.argv[2]),os.environ.copy(),15)
            print(json.dumps(r))
        ''')
        other=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])
        try:
            for mode in ('low','telemetry','death','pidfd'):
                with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                    args=[sys.executable,'-c',outer,str(ROOT/'flex/tests/run-physical-hidden-trial.py'),tmp,inner,str(MODULE),mode,worker,child]
                    result=subprocess.run(args,capture_output=True,text=True,timeout=25,check=True)
                    self.assertNotEqual(json.loads(result.stdout)['clientExit'],0);self.assertIsNone(other.poll())
                    for pid in map(int,(Path(tmp)/'workers.pid').read_text().split()):self.assertFalse(Path(f'/proc/{pid}').exists())
                    if mode!='death':self.assertEqual(json.loads((Path(tmp)/'gpu-monitor-result.json').read_text())['status'],'failed')
        finally:other.terminate();other.wait(timeout=5)


if __name__=='__main__':unittest.main()
