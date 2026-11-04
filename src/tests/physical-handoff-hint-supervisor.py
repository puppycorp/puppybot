#!/usr/bin/env python3
"""CPU-only lifecycle checks for the disabled handoff experiment launcher."""
import importlib.util
import json
import os
import signal
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('handoff_monitor',ROOT/'flex/tests/supervise-physical-handoff-hint.py')
monitor=importlib.util.module_from_spec(spec);spec.loader.exec_module(monitor)


class MonitorTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.output=self.root/'trial';self.monitor=self.root/'monitor'
        self.check=mock.patch.object(monitor.runner,'check',return_value=({'candidateSimulatorSHA256':'candidate'},{}));self.check.start();self.addCleanup(self.check.stop)
        self.disk=mock.patch.object(monitor.shutil,'disk_usage',return_value=mock.Mock(free=20*1024**3));self.disk.start();self.addCleanup(self.disk.stop)

    def test_successful_synthetic_nested_monitor(self):
        code=('import json,pathlib,sys;'
              'o=pathlib.Path(sys.argv[1]);m=pathlib.Path(sys.argv[2]);o.mkdir();'
              '(m/"process-telemetry").mkdir();'
              'a={"status":"diagnostic_only","comparisonEligible":False,"arms":[{"arm":n,"status":"completed"} for n in ("original","candidate-disabled","candidate-enabled")]};'
              '(o/"audit.json").write_text(json.dumps(a));'
              'e={"event":"end","exitCode":0,"errors":[],"hipFileUnchanged":True,"observedPolicies":1,"policiesWithExpectedHipFileMapping":1,"eligibleForQualification":False};'
              '(m/"process-telemetry/observations.jsonl").write_text(json.dumps(e)+"\\n");sys.exit(2)')
        command=[sys.executable,'-c',code,str(self.output),str(self.monitor)]
        with mock.patch.object(monitor,'launch_command',return_value=command):result=monitor.launch(self.output,self.monitor)
        self.assertEqual(result['status'],'diagnostic_only');self.assertFalse(result['comparisonEligible'])
        self.assertEqual(json.loads((self.monitor/'supervisor-result.json').read_text())['clientExit'],2)
        self.assertEqual(json.loads((self.monitor/'launch.json').read_text())['command'],command)
        with self.assertRaises(ValueError):monitor.launch(self.output,self.monitor)

    def test_timeout_reaps_detached_descendant_and_records_signal(self):
        pidfile=self.root/'child.pid'
        child='import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)'
        code=('import signal,subprocess,sys,time;'
              'p=subprocess.Popen([sys.executable,"-c",sys.argv[2]],start_new_session=True);'
              'open(sys.argv[1],"w").write(str(p.pid));signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)')
        command=[sys.executable,'-c',code,str(pidfile),child]
        cleanup=monitor.runner.hidden.supervisor.cleanup_descendants
        def signal_during_cleanup():
            os.kill(os.getpid(),signal.SIGTERM);os.kill(os.getpid(),signal.SIGTERM);return cleanup()
        with mock.patch.object(monitor,'WALL_SECONDS',.4),mock.patch.object(monitor,'launch_command',return_value=command),mock.patch.object(monitor.runner.hidden.supervisor,'cleanup_descendants',side_effect=signal_during_cleanup):
            with self.assertRaises((ValueError,OSError)):monitor.launch(self.output,self.monitor)
        status=json.loads((self.monitor/'supervisor-result.json').read_text())
        self.assertTrue(status['timedOut']);self.assertEqual(status['signal'],signal.SIGTERM);self.assertTrue(pidfile.exists())
        self.assertFalse(Path('/proc',str(status['processGroup'])).exists())
        self.assertFalse(Path('/proc',pidfile.read_text()).exists())

    def test_forged_or_incomplete_terminal_status_fails(self):
        status={'clientExit':2,'timedOut':False,'signal':None,'remainingWorkersTerminated':False}
        telemetry={'event':'end','exitCode':0,'errors':[],'hipFileUnchanged':True,'observedPolicies':1,'policiesWithExpectedHipFileMapping':1,'eligibleForQualification':False}
        audit={'status':'diagnostic_only','comparisonEligible':False,'arms':[{'arm':n,'status':'censored'} for n in ('original','candidate-disabled','candidate-enabled')]}
        monitor.verified_result(status,telemetry,audit)
        for field,value in [('timedOut',True),('signal',15),('clientExit',1),('remainingWorkersTerminated',True)]:
            with self.subTest(field=field),self.assertRaises(ValueError):monitor.verified_result(dict(status,**{field:value}),telemetry,audit)
        with self.assertRaises(ValueError):monitor.verified_result(status,dict(telemetry,observedPolicies=0),audit)
        with self.assertRaises(ValueError):monitor.verified_result(status,telemetry,dict(audit,arms=[]))

    def test_fixed_command_and_independent_reaudit(self):
        command=monitor.launch_command(self.output,self.monitor)
        self.assertEqual(command[:5],[sys.executable,'-I',str(monitor.TELEMETRY),str(self.monitor/'process-telemetry'),'--'])
        self.assertEqual(command[-2:],[str(Path(monitor.__file__).resolve()),str(self.output)])
        self.assertIn('m.worker(sys.argv[2])',command[-3])
        self.output.mkdir();(self.output/'audit.json').write_text('{"status":"diagnostic_only"}')
        auditor=mock.Mock();auditor.audit.return_value={'status':'diagnostic_only'}
        with mock.patch.object(monitor.runner,'run') as run,mock.patch.object(monitor,'load',return_value=auditor):
            monitor.worker(self.output);run.assert_called_once_with(self.output)
            auditor.audit.return_value={'status':'tampered'}
            with self.assertRaisesRegex(ValueError,'re-audit'):monitor.worker(self.output)


if __name__=='__main__':unittest.main()
