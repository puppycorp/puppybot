#!/usr/bin/env python3
"""CPU-only registration watchdog boundary tests."""
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
spec = importlib.util.spec_from_file_location('steering_registration_supervisor_fixture', HERE / 'register-supervisor.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


class SupervisorTests(unittest.TestCase):
    def test_disabled_and_fixed_command(self):
        p = subprocess.run([sys.executable, '-I', str(HERE / 'register-supervisor.py')], capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0); self.assertIn('Disabled', p.stderr)
        self.assertEqual(m.WALL_SECONDS, 3600); self.assertIn('m.freeze()', m.command()[-2])

    def test_no_overwrite_and_bound_result(self):
        clean = {'clientExit':0,'timedOut':False,'signal':None,'remainingWorkersTerminated':False,'processGroup':123}
        for mode in ('ok','bad-plan','bad-status','existing'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); monitor = root/'monitor'; manifest = root/'plan.json'; output = root/'output'; build=root/'build';build.mkdir()
                (build/'build.json').write_text('{}')
                if mode == 'existing': manifest.write_text('preserve')
                def supervise(path, command, env, limit):
                    self.assertEqual(limit, 3600);self.assertEqual(command,m.command())
                    report = {'schema':'puppybot.l5-steering-kick-plan.v1',
                              'status':'wrong' if mode=='bad-plan' else 'frozen_before_play', 'design':m.plan.design(),
                              'files':{str(m.FREEZE):'sha',str(Path(m.__file__)):'sha'}}
                    manifest.write_text(json.dumps(report));(path/'client.log').write_text(json.dumps({'status':'frozen_before_play'}))
                    (path/'supervisor-result.json').write_text(json.dumps(dict(clean, processGroup=999) if mode=='bad-status' else clean))
                    return clean, 0
                patches = [mock.patch.object(m,'P',root),mock.patch.object(m,'MONITOR',monitor),
                           mock.patch.object(m.registration,'MANIFEST',manifest),mock.patch.object(m.plan,'OUTPUT',output),
                           mock.patch.object(m.plan,'BUILD',build),mock.patch.object(m.standalone,'require_dedicated_process'),
                           mock.patch.object(m.shutil,'disk_usage',return_value=type('D',(),{'free':40*1024**3})()),
                           mock.patch.object(m.base,'sha',return_value='sha'),mock.patch.object(m.watch,'supervise',side_effect=supervise)]
                import contextlib
                with contextlib.ExitStack() as stack:
                    for patch in patches: stack.enter_context(patch)
                    if mode == 'existing':
                        with self.assertRaises(ValueError): m.launch()
                        self.assertEqual(manifest.read_text(),'preserve');self.assertFalse(monitor.exists())
                    else:
                        self.assertEqual(m.launch(), 0 if mode=='ok' else 1)
                        self.assertEqual(json.loads((monitor/'result.json').read_text())['wrapperExit'],0 if mode=='ok' else 1)

    def test_clean_status_requires_all_fields(self):
        clean = {'clientExit':0,'timedOut':False,'signal':None,'remainingWorkersTerminated':False,'processGroup':123}
        self.assertEqual(m.watch.exit_code(clean),0)
        for field in clean:
            bad=dict(clean);del bad[field];self.assertNotEqual(m.watch.exit_code(bad),0)


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
                result = subprocess.run([sys.executable, '-c', code, str(HERE / 'register-supervisor.py'), tmp, str(pidfile), child, grandchild],
                                        capture_output=True, text=True, timeout=20, check=True)
                row = json.loads(result.stdout); self.assertEqual(row['result'], 124); self.assertTrue(row['status']['timedOut'])
                self.assertIsNone(other.poll())
                for pid in map(int, pidfile.read_text().split()): self.assertFalse(Path(f'/proc/{pid}').exists())
        finally:
            other.terminate(); other.wait(timeout=5)


if __name__ == '__main__': unittest.main()
