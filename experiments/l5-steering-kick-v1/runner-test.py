#!/usr/bin/env python3
"""CPU-only metadata inventory, registration and paired-runner tests."""
import contextlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent


def load(name):
    spec = importlib.util.spec_from_file_location('steering_fixture_' + name, HERE / f'{name}.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


register = load('register'); runner = load('runner')


class RunnerTests(unittest.TestCase):
    def test_historical_inventory_rejects_overlap_and_skips_holdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); prior = root / 'prior'; prior.mkdir(); held = root / 'held-out'; held.mkdir()
            (prior / 'report.json').write_text(json.dumps({'seed': 100, 'episodes': 2}))
            (held / 'result.json').write_text('intentionally unreadable')
            result = register.historical_inventory((root,), (), require_known=False)
            self.assertEqual(result['records'], 1)
            (prior / 'result.json').write_text(json.dumps({'seed': 6800103}))
            with self.assertRaisesRegex(ValueError, 'overlaps'): register.historical_inventory((root,), (), require_known=False)
            (prior / 'result.json').write_text(json.dumps({'seed': True}))
            with self.assertRaisesRegex(ValueError, 'invalid historical seed'): register.historical_inventory((root,), (), require_known=False)
            (prior / 'result.json').write_text('invalid')
            with self.assertRaisesRegex(ValueError, 'invalid historical metadata'): register.historical_inventory((root,), (), require_known=False)
            def broken_walk(*args, **kwargs):
                kwargs['onerror'](PermissionError('inaccessible history'))
                return iter(())
            with mock.patch.object(register.os, 'walk', side_effect=broken_walk):
                with self.assertRaisesRegex(PermissionError, 'inaccessible history'):
                    register.historical_inventory((root,), (), require_known=False)

    def test_runtime_symlink_inventory_detects_changes_and_cycles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); link = root/'build/flex/rocm-runtime/libamdhip64.so'; link.parent.mkdir(parents=True)
            (link.parent/'lib1').write_bytes(b'one'); (link.parent/'lib2').write_bytes(b'two'); link.symlink_to('lib1')
            with mock.patch.object(register, 'ROOT', root):
                before = register.runtime_chain(); link.unlink(); link.symlink_to('lib2')
                self.assertNotEqual(before, register.runtime_chain())
                link.unlink(); link.symlink_to(link.name)
                with self.assertRaisesRegex(ValueError, 'cycle'): register.runtime_chain()

    def test_scene_roles_spawn_and_symlink_fail_closed(self):
        import struct
        with tempfile.TemporaryDirectory() as tmp:
            scene = Path(tmp) / 'scene'; scene.mkdir()
            (scene/'case.json').write_text('{}')
            environment = bytearray(728); environment[:8] = b'PBENV001'; struct.pack_into('<qqq', environment, 8, 2, 3, 3); struct.pack_into('<3d', environment, 96, 0., .04, .35)
            for offset in (256, 384):
                environment[offset:offset+14] = b'Wall.partition'; struct.pack_into('<d', environment, offset+48, 1.)
            (scene/'environment.bin').write_bytes(environment)
            layout = scene/'layout.json'; layout.write_text(json.dumps({'layoutId':13,'fit':True,'startRoom':0,'rooms':[[-3.,-3.,1.,3.],[1.,-3.,4.,3.]]}))
            design = {'conditions':[{'index':0,'layout':13,'variant':0,'seed':6800100,'scene':str(scene)}]}
            with mock.patch.object(register.plan, 'design', return_value=design):
                self.assertEqual(register.scene_rows()[0]['spawn'], [0., .04, .35])
                layout.write_text(json.dumps({'layoutId':13,'fit':True,'startRoom':0,'rooms':[[-3.,-3.,1.,3.],[1.,-3.,4.,3.]],'reservedHeldOut':True}))
                with self.assertRaisesRegex(ValueError, 'training fit'): register.scene_rows()
                layout.write_text(json.dumps({'layoutId':13,'fit':True,'startRoom':0,'rooms':[[-3.,-3.,1.,3.],[1.,-3.,4.,3.]]}))
                for rooms in ([[],[]], [[1.,-3.,-3.,3.],[1.,-3.,4.,3.]],
                              [[-3.,-3.,1.,float('nan')],[1.,-3.,4.,3.]],
                              [[-3.,-3.,.9,3.],[1.,-3.,4.,3.]],
                              [[1.1,-3.,2.,3.],[1.,-3.,4.,3.]]):
                    layout.write_text(json.dumps({'layoutId':13,'fit':True,'startRoom':0,'rooms':rooms}))
                    with self.assertRaisesRegex(ValueError, 'room bounds'): register.scene_rows()
                layout.write_text(json.dumps({'layoutId':13,'fit':True,'startRoom':0,'rooms':[[-3.,-3.,1.,3.],[1.,-3.,4.,3.]]}))
                canonical = scene.parent / 'environment.bin'; canonical.write_bytes(environment)
                (scene/'environment.bin').unlink(); (scene/'environment.bin').symlink_to('../environment.bin')
                self.assertEqual(register.scene_rows()[0]['sceneLinks']['environment.bin'], '../environment.bin')
                other = scene.parent / 'other.bin'; other.write_bytes(environment)
                (scene/'environment.bin').unlink(); (scene/'environment.bin').symlink_to('../other.bin')
                with self.assertRaisesRegex(ValueError, 'symlink target'): register.scene_rows()
                (scene/'environment.bin').unlink(); (scene/'environment.bin').write_bytes(environment)
                struct.pack_into('<d', environment, 432, 2.)
                (scene/'environment.bin').write_bytes(environment)
                with self.assertRaisesRegex(ValueError, 'partition'): register.scene_rows()
                (scene/'case.json').unlink(); (scene/'case.json').symlink_to(layout)
                with self.assertRaisesRegex(ValueError, 'symlink scene'): register.scene_rows()

    def test_real_selected_scene_inventory_resolves_safely(self):
        rows = register.scene_rows()
        self.assertEqual(len(rows), 12)
        self.assertTrue(all(row['sceneLinks']['environment.bin'] and row['sceneLinks']['layout.json'] for row in rows))

    def test_registration_exclusive_and_rechecks_frozen_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); manifest = root/'plan.json'; output = root/'diagnostic'
            frozen = {'status': 'frozen_before_play', 'identity': 'unchanged'}
            common = [mock.patch.object(register, 'P', root), mock.patch.object(register, 'MANIFEST', manifest),
                      mock.patch.object(register.plan, 'OUTPUT', output),
                      mock.patch.object(register.base, 'acquire_lock', return_value=contextlib.nullcontext()),
                      mock.patch.object(register.base, 'require_capacity')]
            with contextlib.ExitStack() as stack:
                for patch in common: stack.enter_context(patch)
                with mock.patch.object(register, 'current', side_effect=[frozen, dict(frozen, identity='changed')]):
                    with self.assertRaisesRegex(ValueError, 'inputs changed'): register.freeze()
                self.assertFalse(manifest.exists())
                with mock.patch.object(register, 'current', return_value=frozen):
                    self.assertEqual(register.freeze(), frozen)
                    self.assertEqual(register.verify(), frozen)
                    with self.assertRaisesRegex(ValueError, 'already exists'): register.freeze()
                with mock.patch.object(register, 'current', return_value=dict(frozen, identity='changed')):
                    with self.assertRaisesRegex(ValueError, 'inputs or prior metadata changed'): register.verify()

    def test_fixed_commands_and_disabled_entrypoints(self):
        d = runner.plan.design(); row = d['conditions'][0]
        c = runner.command(row, 'control'); t = runner.command(row, 'intervention')
        self.assertEqual(c[:8], t[:8]); self.assertEqual(c[9:-1], t[9:-1])
        self.assertTrue(c[8].endswith('/control')); self.assertTrue(t[8].endswith('/intervention'))
        self.assertEqual(c[-1], '--steer-probe-control'); self.assertEqual(t[-1], '--steer-probe-enabled')
        self.assertEqual(runner.ARM_SECONDS, 600); self.assertIn('--wheel-odometry', c); self.assertEqual(c[c.index('--camera-pitch')+1], '82')
        sources = register.source_paths()
        for name in ('prepare-route-factorial.py', 'audit-matched-training.py', 'proxy.py', 'build-supervisor.py'):
            self.assertTrue(any(path.name == name for path in sources), name)
        with self.assertRaises(ValueError): runner.command(row, 'teacher')
        for name in ('register.py', 'runner.py'):
            result = subprocess.run([sys.executable, '-I', str(HERE / name)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0); self.assertIn('Disabled pending', result.stderr)

    def test_reaudit_requires_every_arm_invocation_status_and_pair(self):
        design = runner.plan.design(); scenes = [{**row, 'files': {'case.json':'case','environment.bin':'env'}, 'spawn':[0.,0.,0.]} for row in design['conditions']]
        manifest = {'status':'frozen_before_play', 'design':design, 'scenes':scenes,
                    'files':{str(runner.plan.MODEL/'weights.bin'):'weights'}}
        clean = {'clientExit':0,'timedOut':False,'signal':None,'remainingWorkersTerminated':False,'processGroup':123}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/'out'; out.mkdir(); (out/'inputs.json').write_text(json.dumps(manifest))
            for row in scenes:
                for arm in design['arms']:
                    directory = out/'monitors'/str(row['index'])/arm; directory.mkdir(parents=True)
                    with mock.patch.object(runner.plan,'OUTPUT',out): argv = runner.command(row,arm)
                    (directory/'invocation.json').write_text(json.dumps({'argv':argv,'environment':runner.environment(),'wallSeconds':600}))
                    (directory/'supervisor-result.json').write_text(json.dumps(clean))
            def fake_pair(c,t,seed,expected):
                return {'seed':seed,'triggered':False,'controlEarly':False,'interventionEarly':False,
                        'controlDelivered':False,'interventionDelivered':False,
                        'controlMostlyBackForth':False,'interventionMostlyBackForth':False}
            with mock.patch.object(runner.plan,'OUTPUT',out), mock.patch.object(runner.selection,'snapshot',return_value='weights'), \
                 mock.patch.object(runner.audit,'saved_pair',side_effect=fake_pair):
                report = runner.reaudit(manifest)
                self.assertEqual(len(report['pairs']),12); self.assertEqual(report['screen']['games'],12)
                directory = out/'monitors/0/intervention'
                (directory/'supervisor-result.json').write_text(json.dumps(dict(clean,timedOut=True)))
                with self.assertRaisesRegex(ValueError,'did not complete'): runner.reaudit(manifest)
                (directory/'supervisor-result.json').write_text(json.dumps(clean))
                path = directory/'invocation.json'; data=json.loads(path.read_text());data['argv'].append('--blackout');path.write_text(json.dumps(data))
                with self.assertRaisesRegex(ValueError,'invocation'): runner.reaudit(manifest)
                path.write_text(json.dumps({'argv':runner.command(scenes[0], 'intervention'),
                                            'environment':runner.environment(),'wallSeconds':600}))
                missing_signal = dict(clean); del missing_signal['signal']
                (directory/'supervisor-result.json').write_text(json.dumps(missing_signal))
                with self.assertRaisesRegex(ValueError,'did not complete'): runner.reaudit(manifest)

    def test_no_overwrite_and_timeout_preserve_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); out=root/'out'; out.mkdir(); lock=contextlib.nullcontext(); d=runner.plan.design(); row={**d['conditions'][0], 'files':{'case.json':'c','environment.bin':'e'}}
            manifest={'scenes':[row]}
            patches=[mock.patch.object(runner.plan,'P',root),mock.patch.object(runner.plan,'OUTPUT',out),
                     mock.patch.object(runner.standalone,'require_dedicated_process'),mock.patch.object(runner.base,'acquire_lock',return_value=lock),
                     mock.patch.object(runner.base,'require_capacity'),mock.patch.object(runner.registration,'verify',return_value=manifest),
                     mock.patch.object(runner,'live_check')]
            with contextlib.ExitStack() as stack:
                for patch in patches: stack.enter_context(patch)
                with self.assertRaisesRegex(ValueError,'already exists'): runner.run()
            out.rmdir(); status={'clientExit':-15,'timedOut':True,'signal':None,'remainingWorkersTerminated':False,'processGroup':123}
            patches.append(mock.patch.object(runner.base.hidden,'supervise',return_value=status))
            with contextlib.ExitStack() as stack:
                for patch in patches: stack.enter_context(patch)
                with self.assertRaisesRegex(ValueError,'did not complete'): runner.run()
            partial=json.loads((out/'partial.json').read_text());self.assertEqual(partial['status'],'censored')
            self.assertEqual(partial['finished'],[]);self.assertFalse((out/'report.json').exists())

    def test_clean_return_requires_same_persisted_supervisor_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); out=root/'out'; d=runner.plan.design()
            row={**d['conditions'][0], 'files':{'case.json':'c','environment.bin':'e'}}; manifest={'scenes':[row]}
            clean={'clientExit':0,'timedOut':False,'signal':None,'remainingWorkersTerminated':False,'processGroup':123}
            def supervise(argv, directory, env, seconds):
                (directory/'supervisor-result.json').write_text(json.dumps(dict(clean, processGroup=999)))
                return clean
            with mock.patch.object(runner.plan,'P',root), mock.patch.object(runner.plan,'OUTPUT',out), \
                 mock.patch.object(runner.standalone,'require_dedicated_process'), \
                 mock.patch.object(runner.base,'acquire_lock',return_value=contextlib.nullcontext()), \
                 mock.patch.object(runner.base,'require_capacity'), mock.patch.object(runner.registration,'verify',return_value=manifest), \
                 mock.patch.object(runner,'live_check'), mock.patch.object(runner.base.hidden,'supervise',side_effect=supervise):
                with self.assertRaisesRegex(ValueError,'status differs'): runner.run()
            self.assertEqual(json.loads((out/'partial.json').read_text())['status'],'censored')
            self.assertFalse((out/'report.json').exists())


if __name__ == '__main__': unittest.main()
