#!/usr/bin/env python3
"""CPU-only fixtures for the independent attested pair verifier."""
import base64
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('audit_pair', ROOT / 'flex/tests/audit-attested-pair.py')
audit_pair = importlib.util.module_from_spec(spec); spec.loader.exec_module(audit_pair)


class PairAuditTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.work = self.root / 'work'; self.model = self.root / 'model'; self.scene = self.root / 'catalog/0'
        self.original = self.root / 'control'; self.instrumented = self.root / 'control-attested'
        self.files = {}
        def pin(path, contents=b'data'):
            path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(contents); self.files[str(path)] = audit_pair.sha(path)
        for path in (self.original, self.instrumented, self.work / 'build/flex/control/simulator', self.work / 'build/flex/sim/puppybot.bin', self.work / 'puppybot.json', self.scene / 'case.json', self.scene / 'environment.bin', self.scene / 'layout.json', self.model / 'policy', self.model / 'weights.bin'):
            pin(path)
        for i in range(5): pin(self.model / 'kernels' / f'kernel-{i}.hip')
        pin(self.model / 'receipt.json', json.dumps({'kernels': {f'kernel-{i}.hip': 'x' for i in range(5)}}).encode())
        manifest = {'schema': 'puppybot.actor-pilot.v1', 'seed': 7, 'horizon': 2, 'files': self.files, 'sceneCatalog': str(self.scene.parent), 'model': str(self.model), 'originalControl': str(self.original), 'instrumentedControl': str(self.instrumented), 'cwd': str(self.work)}
        self.write(self.root / 'inputs.json', manifest)
        self.argv = []
        for arm, binary in (('original', self.original), ('instrumented', self.instrumented)):
            base = self.root / arm; run = base / 'run'; game = run / '7'; game.mkdir(parents=True)
            command = [str(binary), 'run', '--chase', '--fetch', '--policy', str(self.model), '--scene-catalog', str(self.scene.parent), '--output', str(run), '--episodes', '1', '--horizon', '2', '--seed', '7', '--level', '5', '--wheel-odometry', '--camera-pitch', '82']
            self.write(base / 'command.json', command)
            self.write(base / 'monitor/supervisor-result.json', {'clientExit': 0, 'timedOut': False, 'signal': None, 'remainingWorkersTerminated': False, 'processGroup': 123})
            self.write(run / 'summary.json', {'complete': True, 'episodes': 1})
            self.write(game / 'result.json', {'seed': 7, 'steps': 2})
            self.write(game / 'initial.json', {'totalSteps': 10})
            (game / 'chase.jsonl').write_text(json.dumps({'step': 0, 'event': 'start', 'brick': [1, 2], 'robot': [0, 0, 0]}) + '\n')
            rows = [{'action': [0, 1], 'proprio': [0, 1, 0, 0, 0, 0, 0], 'state': {'totalSteps': tick}} for tick in (20, 30)]
            (game / 'decisions.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
            for tick in (10, 20, 30):
                (game / f'actor-{tick}.rgb').write_bytes(bytes([tick]) * 21168)
                (game / f'actor-{tick}.feedback').write_bytes(bytes([tick]) * 28)
            for name in ('case.json', 'environment.bin'):
                dest = game / 'scene' / name; dest.parent.mkdir(exist_ok=True); dest.write_bytes((self.scene / name).read_bytes())
            for path in (self.model / 'policy', self.model / 'weights.bin', self.model / 'receipt.json', *(self.model / 'kernels').iterdir()):
                dest = run / 'policy' / path.relative_to(self.model); dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(path.read_bytes())
            if arm == 'instrumented':
                # The first pre-action image can differ from the reset image after placement.
                record = lambda image: b'\0' * 24 + image + b'\0' * ((21168 + 7 + 128) * 4 + (2 + 128) * 4 + 8)
                (game / 'actor-attestation.bin').write_bytes(b'\0' * 56 + record(b'\xff' * 21168) + record(bytes([20]) * 21168))
                policy = [str(run / 'policy/policy'), str(run / 'policy/weights.bin'), audit_pair.sha(self.model / 'weights.bin'), str(run / 'policy/kernels'), '3']
                sim = [str(self.work) + '/./build/flex/control/simulator', '--hidden', '--case-file', str(game / 'scene/case.json'), '--environment', str(game / 'scene/environment.bin'), '--steps', '1000000', '--bind', '127.0.0.1:0', '--agent-fd', '3', '--observer-distance-mm', '2500', '--tcp-view', '--no-visual-odometry', '--camera-pitch', '82', '--video', str(game / 'mission.mp4'), '--video-fps', '5', '--record', str(game / 'trace.jsonl'), '--capture', str(game / 'outcome.png'), '--search-output', str(game / 'sensor')]
                self.argv = [{'kind': kind, 'argvBase64': [base64.b64encode(x.encode()).decode() for x in args]} for kind, args in zip(('control', 'child_exec_intent', 'child_exec_intent'), (command, policy, sim))]
        self.old_loader = audit_pair.load_module
        audit_pair.load_module = lambda name, _: SimpleNamespace(audit=(lambda *args: {'imageBytes': 21168, 'memoryWidth': 128}) if name == 'actor_audit' else (lambda *args: {'records': self.argv}))
        self.addCleanup(setattr, audit_pair, 'load_module', self.old_loader)

    @staticmethod
    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value))

    def test_complete_pair_and_initial_image_limitation(self):
        result = audit_pair.audit(self.root)
        self.assertIsNone(result['parity']); self.assertTrue(result['comparedSignalsMatch']); self.assertFalse(result['firstActorImageCompared'])

    def test_action_feedback_and_image_differences_are_reported(self):
        game = self.root / 'instrumented/run/7'
        rows = [json.loads(x) for x in (game / 'decisions.jsonl').read_text().splitlines()]
        rows[0]['action'][1] = .5; rows[1]['proprio'][2] = .5
        (game / 'decisions.jsonl').write_text(''.join(json.dumps(x) + '\n' for x in rows))
        (game / 'actor-20.rgb').write_bytes(b'z' * 21168)
        result = audit_pair.audit(self.root)
        self.assertFalse(result['parity']); self.assertGreaterEqual(len(result['differences']), 3)

    def test_changed_placement_is_reported(self):
        path = self.root / 'instrumented/run/7/chase.jsonl'
        placement = json.loads(path.read_text()); placement['brick'][0] = 3
        path.write_text(json.dumps(placement) + '\n')
        result = audit_pair.audit(self.root)
        self.assertFalse(result['comparedSignalsMatch']); self.assertIn('target placement events differ', result['differences'])

    def test_missing_observation_rejected(self):
        (self.root / 'original/run/7/actor-20.rgb').unlink()
        with self.assertRaises(OSError): audit_pair.audit(self.root)

    def test_changed_pin_and_unclean_supervisor_rejected(self):
        self.original.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'pinned file'): audit_pair.audit(self.root)
        self.original.write_bytes(b'data')
        p = self.root / 'instrumented/monitor/supervisor-result.json'; status = json.loads(p.read_text()); status['timedOut'] = True; self.write(p, status)
        with self.assertRaisesRegex(ValueError, 'supervisor'): audit_pair.audit(self.root)

    def test_child_intent_rejected_when_changed(self):
        self.argv[-1]['argvBase64'][-1] = base64.b64encode(b'wrong').decode()
        with self.assertRaisesRegex(ValueError, 'argv'): audit_pair.audit(self.root)


if __name__ == '__main__':
    unittest.main()
