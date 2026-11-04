#!/usr/bin/env python3
"""CPU stub lifecycle checks for the paired simulator runner; no GPU."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('runner', ROOT / 'flex/tests/run-sim-visual-stop-pair.py')
runner = importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)


class RunnerTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.root=Path(self.tmp.name)
        model=self.root/'model'; model.mkdir(); (model/'weights.bin').write_bytes(b'w')
        environment=self.root/'environment'; environment.write_bytes(b'e')
        self.patch(runner,'ROOT',self.root); self.patch(runner,'LOCK',self.root/'lock')
        self.patch(runner.hidden,'MODEL',model); self.patch(runner.hidden,'ENVIRONMENT',environment)
        self.patch(runner.hidden,'prepare_case',lambda:'{}')
        self.patch(runner.rescan,'verify_model',lambda p:None)
        self.patch(runner.hidden.supervisor,'worker_snapshot',lambda env:{'launchPath':'/usr/bin/python3','executable':str(Path('/usr/bin/python3').resolve())})
        self.patch(runner.hidden.supervisor,'verify_worker',lambda worker:None)
        def snapshot(inputs):
            (inputs/'flex-source').mkdir(); (inputs/'simulator').write_bytes(b'simulator')
            return {},{},'compiler'
        self.patch(runner.rescan,'build_snapshot',snapshot)
        def build(output):
            output.mkdir(); (output/'client').write_bytes(b'client'); return {'originalSource':{}}
        self.patch(runner.builder,'prepare',build); self.patch(runner.builder,'hashes',lambda root:{})
        self.patch(runner,'pinned_files',lambda inputs, output:{'stub':'unchanged'})
        self.patch(runner.shutil,'disk_usage',lambda path:SimpleNamespace(free=20*1024**3))
        self.calls=[]; self.status={'signal':None,'timedOut':False,'clientExit':0,'remainingWorkersTerminated':False}
        def supervise(argv, output, env, wall):
            self.calls.append((argv,output,env,wall)); return dict(self.status)
        self.patch(runner.hidden,'supervise',supervise)
        self.patch(runner.subprocess,'run',lambda *args, **kwargs:SimpleNamespace(returncode=0,stdout='{"status":"diagnostic_only"}\n',stderr=''))

    def patch(self, obj, name, value):
        p=mock.patch.object(obj,name,value); p.start(); self.addCleanup(p.stop)

    def test_two_same_binary_arms_and_audit(self):
        output=self.root/'pair'; runner.run(output)
        self.assertEqual(len(self.calls),2)
        left,right=self.calls
        self.assertEqual(left[0][:5],right[0][:5]); self.assertEqual(left[0][6:],right[0][6:])
        a,b=dict(left[2]),dict(right[2]); self.assertEqual(a.pop('PUPPYBOT_SIM_VISUAL_STOP'),'0'); self.assertEqual(b.pop('PUPPYBOT_SIM_VISUAL_STOP'),'1'); self.assertEqual(a,b)
        self.assertEqual(left[3],300); self.assertTrue((output/'audit.json').exists())
        with self.assertRaises(FileExistsError): runner.run(output)

    def test_low_space_preserves_destination(self):
        with mock.patch.object(runner.shutil, 'disk_usage', return_value=SimpleNamespace(free=0)):
            output=self.root/'low-space'
            with self.assertRaisesRegex(ValueError, 'insufficient free space'): runner.run(output)
            self.assertFalse(output.exists()); self.assertEqual(self.calls, [])

    def test_worker_path_change_prevents_second_arm(self):
        with mock.patch.object(runner.shutil, 'which', return_value='/wrong/python3'):
            output=self.root/'worker-change'
            with self.assertRaisesRegex(ValueError, 'interpreter path changed'): runner.run(output)
            self.assertEqual(len(self.calls), 1); self.assertFalse((output/'audit.json').exists())

    def test_timeout_and_cleanup_prevent_second_arm_or_audit(self):
        for key,value in (('timedOut',True),('remainingWorkersTerminated',True),('signal',15),('clientExit',1)):
            self.status={'signal':None,'timedOut':False,'clientExit':0,'remainingWorkersTerminated':False}; self.status[key]=value; self.calls=[]
            output=self.root/key
            with self.assertRaisesRegex(RuntimeError,'failed or needed cleanup'): runner.run(output)
            self.assertEqual(len(self.calls),1); self.assertFalse((output/'audit.json').exists())


if __name__=='__main__': unittest.main()
