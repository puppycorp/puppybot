#!/usr/bin/env python3
"""CPU tests for the visual-stall state machine and copied controller build."""
import importlib.util
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


transform = load('visual_transform', HERE / 'transform.py')
audit = load('visual_audit', HERE / 'audit.py')

HOOK_PROBE = r'''import "host.flex";
import "visual-stall.flex";
global ve_state=0;global ve_image=0;global ve_image_bytes=8;global ve_steps=0;
global vx_visual_state=0;global vx_visual_reason=0;global bad_echo=0;
fn ve_step(action) {
    vc_require(!load64(action),"visual stop sent nonzero action");pl_print(2,"ZERO_REQUEST\n");
    let state="{\"controller\":{\"drive\":{\"leftSpeed\":0,\"rightSpeed\":0}}}";
    if bad_echo {state="{\"controller\":{\"drive\":{\"leftSpeed\":60,\"rightSpeed\":60}}}";}
    ve_state=pj_parse(state,pl_size(state));ve_steps=ve_steps+1;return 0;
}
''' + transform.HOOK + r'''
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==3,"expected mode and directory");let mode=load64(argv+8);let directory=load64(argv+16);
    vx_visual_state=alloc(48);let previous=alloc(8);ve_image=alloc(8);pb_zero(ve_image,8);
    vc_require(vs_init(vx_visual_state,previous,8,5),"guard init failed");bad_echo=pl_equal(mode,"bad-echo");
    let action=alloc(8);let text=alloc(1024);let b=alloc(32);let i=0;
    while i<5 {
        let tick=100+i*10;let frame=tick;if pl_equal(mode,"stale-frame") {frame=tick-1;}
        pl_builder(b,text,1024);pl_text(b,"{\"camera\":{\"pose\":\"driving\",\"armSettled\":true},\"totalSteps\":");pl_int(b,tick);
        pl_text(b,",\"case\":{\"perception\":{\"frameId\":");pl_int(b,frame);
        pl_text(b,"}},\"controller\":{\"drive\":{\"leftSpeed\":60,\"rightSpeed\":60}}}");
        ve_state=pj_parse(text,load64(b+8));let stopped=vx_visual_stop_check(directory,action);
        if pl_equal(mode,"stale-frame") {vc_require(stopped && vx_visual_reason==2,"stale frame not reported");return 0;}
        if i<4 {vc_require(!stopped,"visual stop fired early");ve_steps=ve_steps+1;}else {vc_require(stopped && vx_visual_reason==1,"visual stop missing");}
        i=i+1;
    }return 0;
}
'''


class VisualStallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='puppy-visual-stall-')
        root = Path(cls.temp.name); shutil.copytree(ROOT / 'flex', root / 'flex', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        control = root / 'flex/control'; chase = control / 'chase.flex'; main = control / 'main.flex'
        chase_text, main_text = transform.transform(chase.read_text(), main.read_text())
        chase.write_text(chase_text); main.write_text(main_text)
        shutil.copyfile(ROOT / 'experiments/contact-stop-v1/contact-stop.flex', control / 'contact-stop.flex')
        shutil.copyfile(HERE / 'visual-stall.flex', control / 'visual-stall.flex')
        unit = (HERE / 'test.flex').read_text().replace('import "../../flex/control/host.flex";', 'import "host.flex";')
        (control / 'visual-test.flex').write_text(unit)
        (control / 'visual-hook.flex').write_text(HOOK_PROBE)
        compiler = ROOT / 'build/flex/control/compiler'
        for source, binary in (('main.flex', 'control'), ('visual-test.flex', 'unit'), ('visual-hook.flex', 'hook')):
            subprocess.run([str(compiler), str(control / source), '-o', str(root / binary)],
                           cwd=ROOT, check=True, timeout=120, capture_output=True)
        cls.root = root

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_native_detector(self):
        subprocess.run([str(self.root / 'unit')], cwd=ROOT, check=True, timeout=15, capture_output=True)

    def test_blackout_rejected_before_policy_or_simulator_start(self):
        output = self.root / 'blackout-run'
        result = subprocess.run([str(self.root / 'control'), 'run', '--fetch',
                                 '--visual-stall-stop', '--blackout', '--policy',
                                 str(self.root / 'unused-policy'), '--output', str(output)],
                                cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('visual stop requires an isolated simulated fetch policy run without blackout', result.stderr)
        self.assertFalse(output.exists())

    def test_saved_stream_inventory_rejects_missing_and_extra_paths(self):
        with tempfile.TemporaryDirectory(dir=self.root) as directory:
            root = Path(directory); name = audit.GROUPS[0]; expected = audit.expected_streams(name)
            for relative in expected:
                path = root / relative; path.parent.mkdir(parents=True, exist_ok=True); path.touch()
            self.assertEqual({path.relative_to(root) for path in audit.inventory(root, name)}, expected)
            missing = root / next(iter(expected)); missing.unlink()
            with self.assertRaisesRegex(ValueError, 'inventory differs'):
                audit.inventory(root, name)
            missing.touch()
            extra = root / 'extra/steer-probe.jsonl'; extra.parent.mkdir(); extra.touch()
            with self.assertRaisesRegex(ValueError, 'inventory differs'):
                audit.inventory(root, name)

    def test_stop_hook_marks_suspicion_and_requires_zero_echo(self):
        for mode in ('valid', 'stale-frame', 'bad-echo', 'write-fail'):
            with self.subTest(mode=mode):
                directory = Path(tempfile.mkdtemp(dir=self.root)) / 'run'
                if mode != 'write-fail': directory.mkdir()
                result = subprocess.run([str(self.root / 'hook'), mode, str(directory)], cwd=ROOT,
                                        capture_output=True, text=True, timeout=15)
                self.assertIn('ZERO_REQUEST', result.stderr)
                path = directory / 'visual-stall-stop.json'
                if mode in ('bad-echo', 'write-fail'):
                    self.assertNotEqual(result.returncode, 0); self.assertFalse(path.exists())
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    report = json.loads(path.read_text())
                    self.assertEqual(report['reason'], 'invalid_observation' if mode == 'stale-frame' else 'repeated_actor_image')
                    self.assertIs(report['stopCommandAcknowledged'], False)
                    self.assertIs(report['goalGameCompleted'], False)
                    self.assertEqual(report['triggerImageSHA256'], hashlib.sha256(bytes(8)).hexdigest())
                    self.assertEqual(report['triggerTick'], 100 if mode == 'stale-frame' else 140)
                    self.assertEqual(report['triggerFrameId'], 99 if mode == 'stale-frame' else 140)
                    self.assertEqual((report['triggerLeftSpeed'], report['triggerRightSpeed']), (60, 60))
                    if mode == 'valid': self.assertEqual((report['triggerAfterActions'], report['observedActions']), (4, 5))

    def test_camera_frozen_while_truth_moves_is_not_safe_to_call_stopped(self):
        def state(tick, x):
            return {'totalSteps': tick, 'camera': {'pose': 'driving', 'armSettled': True},
                    'case': {'perception': {'frameId': tick}}, 'pose': [x, 0.0, 0.0],
                    'controller': {'drive': {'leftSpeed': 60, 'rightSpeed': 60, 'steeringAngleDeg': 90}}}
        probe = [{'step': i + 1, 'imageSHA256': 'a' * 64, 'echo': [60, 60, 90]} for i in range(5)]
        decisions = [{'sequence': i + 1, 'state': state(110 + i * 10, (i + 1) * 0.02)} for i in range(5)]
        found = audit.runs(probe, decisions, state(100, 0.0))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['truthClass'], 'moving')
        self.assertEqual(found[0]['firstFiveFrameTriggerBeforeDecision'], 5)

    def test_audit_rejects_stale_frame_id(self):
        state = {'totalSteps': 100, 'camera': {'pose': 'driving', 'armSettled': True},
                 'case': {'perception': {'frameId': 99}}, 'pose': [0.0, 0.0, 0.0]}
        with self.assertRaises(ValueError):
            audit.runs([{'step': 1, 'imageSHA256': 'a' * 64}], [{'state': state}], state)


if __name__ == '__main__':
    unittest.main()
