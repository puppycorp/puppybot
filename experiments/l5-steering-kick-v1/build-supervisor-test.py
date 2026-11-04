#!/usr/bin/env python3
"""CPU-only build watchdog tests; no real build output or GPU."""
import contextlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('steering_build_supervisor_fixture', HERE / 'build-supervisor.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


class BuildWatchdogTests(unittest.TestCase):
    def test_disabled_fixed_command_and_limit(self):
        p = subprocess.run([sys.executable, '-I', str(HERE / 'build-supervisor.py')], capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0); self.assertIn('Disabled', p.stderr)
        self.assertEqual(m.WALL_SECONDS, 1800); self.assertIn('m.prepare()', m.command()[-2])

    def test_no_overwrite_and_matching_saved_status(self):
        clean = {'clientExit':0,'timedOut':False,'signal':None,'remainingWorkersTerminated':False,'processGroup':123}
        for mode in ('ok','bad-report','bad-status','existing'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);monitor=root/'monitor';build=root/'build';output=root/'output'
                if mode=='existing': build.mkdir()
                def supervise(path, command, env, limit):
                    self.assertEqual(limit,1800);self.assertEqual(command,m.command());build.mkdir()
                    report={'schema':'puppybot.l5-steer-build.v1','status':'wrong' if mode=='bad-report' else 'diagnostic_build_only',
                            'inputs':{str(m.PREPARE):'sha',str(HERE/'transform.py'):'sha',str(HERE/'probe.flex'):'sha'}}
                    (build/'build.json').write_text(json.dumps(report))
                    (path/'client.log').write_text('CPU probe passed\n'+json.dumps({'status':'diagnostic_build_only'})+'\n')
                    (path/'supervisor-result.json').write_text(json.dumps(dict(clean,processGroup=999) if mode=='bad-status' else clean))
                    return clean,0
                patches=[mock.patch.object(m,'P',root),mock.patch.object(m,'MONITOR',monitor),mock.patch.object(m.plan,'BUILD',build),
                         mock.patch.object(m.plan,'OUTPUT',output),mock.patch.object(m.standalone,'require_dedicated_process'),
                         mock.patch.object(m.shutil,'disk_usage',return_value=type('D',(),{'free':40*1024**3})()),
                         mock.patch.object(m.base,'sha',return_value='sha'),mock.patch.object(m.watch,'supervise',side_effect=supervise)]
                with contextlib.ExitStack() as stack:
                    for patch in patches:stack.enter_context(patch)
                    if mode=='existing':
                        with self.assertRaises(ValueError):m.launch()
                        self.assertFalse(monitor.exists())
                    else:
                        self.assertEqual(m.launch(),0 if mode=='ok' else 1)
                        self.assertEqual(json.loads((monitor/'result.json').read_text())['wrapperExit'],0 if mode=='ok' else 1)
                        pins = json.loads((monitor/'launch.json').read_text())['sourcePins']
                        for name in ('plan.py','run-route-factorial.py','prepare-route-factorial.py',
                                     'audit-matched-training.py','run-physical-hidden-trial.py'):
                            self.assertTrue(any(Path(path).name == name for path in pins), name)

    def test_status_fields_fail_closed(self):
        status={'clientExit':0,'timedOut':False,'signal':None,'remainingWorkersTerminated':False,'processGroup':123}
        self.assertEqual(m.watch.exit_code(status),0)
        for field in status:
            bad=dict(status);del bad[field];self.assertNotEqual(m.watch.exit_code(bad),0)

    def test_timeout_cleans_detached_descendant_and_spares_sibling(self):
        grandchild = 'import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)'
        child = ('import os,signal,subprocess,sys,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);'
                 'p=subprocess.Popen([sys.executable,"-c",sys.argv[2]],start_new_session=True);'
                 'open(sys.argv[1],"w").write(str(os.getpid())+" "+str(p.pid));time.sleep(30)')
        code = textwrap.dedent('''
            import importlib.util,json,os,sys
            from pathlib import Path
            s=importlib.util.spec_from_file_location('w',sys.argv[1]);w=importlib.util.module_from_spec(s);s.loader.exec_module(w)
            status,result=w.watch.supervise(Path(sys.argv[2]),[sys.executable,'-c',sys.argv[4],sys.argv[3],sys.argv[5]],os.environ.copy(),.5)
            print(json.dumps({'status':status,'result':result}))
        ''')
        other = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(30)'])
        try:
            with tempfile.TemporaryDirectory() as tmp:
                pidfile = Path(tmp) / 'workers.pid'
                result = subprocess.run([sys.executable, '-c', code, str(HERE / 'build-supervisor.py'), tmp, str(pidfile), child, grandchild],
                                        capture_output=True, text=True, timeout=20, check=True)
                row = json.loads(result.stdout); self.assertEqual(row['result'], 124); self.assertTrue(row['status']['timedOut'])
                self.assertIsNone(other.poll())
                for pid in map(int, pidfile.read_text().split()): self.assertFalse(Path(f'/proc/{pid}').exists())
        finally:
            other.terminate(); other.wait(timeout=5)


if __name__ == '__main__': unittest.main()
