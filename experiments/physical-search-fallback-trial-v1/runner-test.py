#!/usr/bin/env python3
"""CPU-only launch-plan and input pin checks, with execution disabled."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('search_trial_runner',HERE/'run.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)


class RunnerTest(unittest.TestCase):
    def test_cli_is_disabled(self):
        result=subprocess.run([sys.executable,str(HERE/'run.py')],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0);self.assertIn('disabled',result.stderr.lower())

    def test_three_arm_commands_and_environment(self):
        root=Path('/tmp/search-test');manifest={'build':'/build','model':'/model','case':'/case','environment':'/environment'}
        for name in runner.ARMS:
            command=runner.command_for(root,manifest,name);env=runner.env_for('1' if name=='candidate-search' else '0')
            self.assertEqual(command[:2],['/build/'+('baseline-client' if name=='baseline' else 'client'),'/build/'+('baseline-simulator' if name=='baseline' else 'simulator')])
            self.assertEqual(command[2:],['/model','/case','/environment',str(root/name/'run'),'--allow-zero-contact'])
            self.assertEqual(env['PUPPYBOT_PHYSICAL_NAV_LIMIT'],'90');self.assertEqual(env['PUPPYBOT_PHYSICAL_POLL_LIMIT'],'1499')
            self.assertEqual(env['PUPPYBOT_PHYSICAL_SEARCH_FALLBACK'],'1' if name=='candidate-search' else '0')

    def test_status_rejects_boolean_exit_or_bad_process_group(self):
        good={'clientExit':0,'signal':None,'timedOut':False,'remainingWorkersTerminated':False,'processGroup':42}
        self.assertTrue(runner.clean_status(good));missing=dict(good);del missing['signal'];self.assertFalse(runner.clean_status(missing))
        for key,value in (('clientExit',False),('processGroup',True),('processGroup',0),('processGroup',None),('timedOut',0)):
            status=dict(good);status[key]=value;self.assertFalse(runner.clean_status(status))

    def test_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);output=path/'existing';output.mkdir();(output/'sentinel').write_text('keep')
            dedicated=types.SimpleNamespace(require_dedicated_process=lambda:None)
            with mock.patch.dict(os.environ,{'PUPPYBOT_SEARCH_TRIAL_REVIEWED_WORKER':'1'}),mock.patch.object(runner,'LOCK',path/'lock'),mock.patch.object(runner,'load',return_value=dedicated):
                with self.assertRaisesRegex(ValueError,'output exists'):runner.launch(output,path/'build',path/'case',path/'environment',path/'model')
            self.assertEqual((output/'sentinel').read_text(),'keep')

    def test_scene_helper_and_transitive_helper_are_required_and_hashed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'inputs/model/kernels').mkdir(parents=True);build=root/'build';build.mkdir()
            required=runner.required(root,build)
            helper_paths=[runner.ROOT/'flex/tests/sim-cases.py',runner.ROOT/'flex/tests/sim.py']
            self.assertTrue(all(p in required for p in helper_paths))
            # Exercise the real pinning function on disposable copies, not live inputs.
            copies=[]
            for i,source in enumerate(helper_paths):
                dest=root/str(i);dest.write_bytes(source.read_bytes());copies.append(dest)
            with mock.patch.object(runner,'required',return_value=copies):
                before=runner.pins(root,build)
                worker={'launchPath':'/usr/bin/python3','executable':str(Path('/usr/bin/python3').resolve())}
                (root/'worker-inputs.json').write_text(json.dumps(worker))
                manifest={'build':str(build),'case':str(root/'inputs/case.json'),'environment':str(root/'inputs/environment.bin'),'model':str(root/'inputs/model'),'wallSecondsPerArm':300,'files':before}
                for p in copies:
                    original=p.read_bytes();p.write_bytes(original+b'\n# changed\n')
                    self.assertNotEqual(runner.pins(root,build),before)
                    with mock.patch.object(runner,'check_build'),mock.patch.object(runner.hidden.rescan,'verify_model'),mock.patch.object(runner.hidden.supervisor,'verify_worker'),mock.patch.object(runner.shutil,'which',return_value='/usr/bin/python3'):
                        with self.assertRaisesRegex(ValueError,'trial inputs changed'):runner.check_manifest(root,manifest)
                    p.write_bytes(original)


if __name__=='__main__':unittest.main()
