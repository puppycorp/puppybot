#!/usr/bin/env python3
"""Exercise the isolated native actor journal and independent byte verifier."""
import importlib.util
import json
import os
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / 'datasets/visual-control/chase-v1/levels/audit-actor-attestation.py'
spec = importlib.util.spec_from_file_location('actor_audit', AUDIT)
actor_audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(actor_audit)
IMAGE = 21168
WIDTH = 128
RECORD = 24 + IMAGE + (IMAGE + 7 + WIDTH) * 4 + (2 + WIDTH) * 4 + 8


class ActorAttestationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory()
        cls.binary = Path(cls.build.name) / 'actor-attestation-test'
        compiler = os.environ.get('FLEXSCRIPT_COMPILER', str(ROOT / 'build/flex/control/compiler'))
        subprocess.run([compiler, str(ROOT / 'flex/tests/actor-attestation.flex'), '-o', str(cls.binary)], cwd=ROOT, check=True)

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.journal = self.root / 'actor.bin'
        subprocess.run([str(self.binary), str(self.journal)], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
        self.game = self.root / 'game'
        self.game.mkdir()
        result = {'seed': 1700000100, 'steps': 2, 'game': 'fetch', 'controller': 'native neural policy',
                  'blackout': False, 'carryCue': True, 'farBricks': False, 'exploreTeacher': False, 'sweepTeacher': False,
                  'suppliedMap': False, 'taskEventHint': False, 'maximumBrickDistanceM': 0.35}
        (self.game / 'result.json').write_text(json.dumps(result))
        (self.game / 'initial.json').write_text(json.dumps({'totalSteps': 500, 'controller': {'drive': {'leftSpeed': 0, 'rightSpeed': 0, 'steeringAngleDeg': 90}}}))
        rows = [{'sequence': i + 3, 'action': [0.0, 0.0], 'proprio': [0.0] * 7,
                 'state': {'totalSteps': 510 + 10 * i, 'findReturn': {'phase': 'search'},
                           'controller': {'drive': {'leftSpeed': 0, 'rightSpeed': 0, 'steeringAngleDeg': 90}}}} for i in range(2)]
        (self.game / 'decisions.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))

    def tearDown(self):
        self.temp.cleanup()

    def mutate(self, offset, data):
        with self.journal.open('r+b') as stream:
            stream.seek(offset)
            stream.write(data)

    def test_native_journal_matches_game(self):
        report = actor_audit.audit(self.journal, self.game)
        self.assertEqual(report['status'], 'actor_journal_internally_consistent')
        self.assertEqual(report['steps'], 2)

    def test_truncated_journal_rejected(self):
        self.journal.write_bytes(self.journal.read_bytes()[:-1])
        with self.assertRaises(ValueError):
            actor_audit.audit(self.journal, self.game)

    def test_image_normalization_mismatch_rejected(self):
        self.mutate(56 + 24, b'\x01')
        with self.assertRaisesRegex(ValueError, 'normalization'):
            actor_audit.audit(self.journal, self.game)

    def test_nonzero_image_normalization_matches_float32(self):
        self.mutate(56 + 24, b'\x80')
        self.mutate(56 + 24 + IMAGE, struct.pack('<f', 128 / 255.0))
        self.assertEqual(actor_audit.audit(self.journal, self.game)['steps'], 2)

    def test_hidden_search_cue_rejected(self):
        second_feedback = 56 + RECORD + 24 + IMAGE + IMAGE * 4
        self.mutate(second_feedback + 24, struct.pack('<f', -0.005))
        with self.assertRaisesRegex(ValueError, 'carry cue'):
            actor_audit.audit(self.journal, self.game)

    def test_modified_action_rejected(self):
        action = 56 + 24 + IMAGE + (IMAGE + 7 + WIDTH) * 4 + (2 + WIDTH) * 4
        self.mutate(action, struct.pack('<f', 0.5))
        with self.assertRaisesRegex(ValueError, 'policy action'):
            actor_audit.audit(self.journal, self.game)

    def test_recurrent_memory_mismatch_rejected(self):
        second_memory = 56 + RECORD + 24 + IMAGE + (IMAGE + 7) * 4
        self.mutate(second_memory, struct.pack('<f', 1.0))
        with self.assertRaisesRegex(ValueError, 'recurrent memory'):
            actor_audit.audit(self.journal, self.game)

    def test_unobserved_contact_feedback_rejected(self):
        second_feedback = 56 + RECORD + 24 + IMAGE + IMAGE * 4
        self.mutate(second_feedback + 20, struct.pack('<f', 1.0))
        with self.assertRaisesRegex(ValueError, 'preceding observed state'):
            actor_audit.audit(self.journal, self.game)

    def test_recorded_drive_and_proprio_disagreement_rejected(self):
        path = self.game / 'decisions.jsonl'
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[0]['state']['controller']['drive']['leftSpeed'] = 60
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        with self.assertRaisesRegex(ValueError, 'prior proprioception differs'):
            actor_audit.audit(self.journal, self.game)

    def test_result_intervention_rejected(self):
        path = self.game / 'result.json'
        result = json.loads(path.read_text())
        result['straightBiasHundredths'] = 50
        path.write_text(json.dumps(result))
        with self.assertRaisesRegex(ValueError, 'non-default'):
            actor_audit.audit(self.journal, self.game)

    def test_bad_native_order_keeps_incomplete_file(self):
        path = self.root / 'bad.bin'
        run = subprocess.run([str(self.binary), str(path), 'bad-order'], cwd=ROOT, capture_output=True)
        self.assertNotEqual(run.returncode, 0)
        with self.assertRaises(ValueError):
            actor_audit.audit(path, self.game)

    def test_writer_refuses_overwrite(self):
        before = self.journal.read_bytes()
        run = subprocess.run([str(self.binary), str(self.journal)], cwd=ROOT, capture_output=True)
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual(self.journal.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
