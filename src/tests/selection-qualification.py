#!/usr/bin/env python3
"""Focused negative checks for the selection-only qualification verifier."""
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / 'datasets/visual-control/chase-v1/levels/qualify-selection.py'
spec = importlib.util.spec_from_file_location('qualify', TOOL)
qualify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qualify)


def sha(data):
    return hashlib.sha256(data).hexdigest()


class SelectionQualificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.candidate = self.root / 'candidate'
        self.candidate.mkdir()
        (self.candidate / 'weights.bin').write_bytes(b'weights')
        (self.candidate / 'receipt.json').write_bytes(b'receipt')
        self.training = self.root / 'training.sha256'
        self.training.write_bytes(b'training')
        self.audits = {}
        for label in ('standard', 'L1', 'L2', 'L3', 'L4', 'L5'):
            path = self.root / label
            path.write_bytes(label.encode())
            self.audits[label] = path
        self.choice = {'schema': 'puppybot.selection-choice.v1', 'rationale': 'chosen from these selection results',
                       'selectedWeightsSHA256': sha(b'weights'), 'candidateReceiptSHA256': sha(b'receipt'),
                       'trainingManifestSHA256': sha(b'training'),
                       'selectionAuditSHA256': {k: sha(k.encode()) for k in self.audits}}

    def tearDown(self):
        self.temp.cleanup()

    def validate(self):
        qualify.validate_choice(self.choice, self.candidate, self.training, self.audits)

    def test_choice_binds_all_artifacts(self):
        self.validate()

    def test_missing_level_two_rejected(self):
        del self.choice['selectionAuditSHA256']['L2']
        with self.assertRaises(ValueError):
            self.validate()

    def test_missing_standard_rejected(self):
        del self.choice['selectionAuditSHA256']['standard']
        with self.assertRaises(ValueError):
            self.validate()

    def test_changed_paired_audit_rejected(self):
        self.audits['L4'].write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.validate()

    def test_changed_candidate_rejected(self):
        (self.candidate / 'weights.bin').write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.validate()

    def test_changed_training_manifest_rejected(self):
        self.training.write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.validate()

    def test_changed_model_receipt_rejected(self):
        (self.candidate / 'receipt.json').write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.validate()

    def test_self_asserted_flags_without_bound_artifacts_rejected(self):
        forged = {'selectionOnly': True, 'allLevelsAudited': True, 'standardFetchAudited': True, 'heldoutUsed': False}
        with self.assertRaises(ValueError):
            qualify.validate_choice(forged, self.candidate, self.training, self.audits)

    def test_missing_pinned_input_rejected(self):
        manifest = self.root / 'inputs.sha256'
        manifest.write_text(f'{sha(b"weights")}  {self.candidate / "weights.bin"}\n')
        pins = qualify.checksums(manifest)
        qualify.require_pinned(pins, self.candidate / 'weights.bin')
        with self.assertRaises(ValueError):
            qualify.require_pinned(pins, self.candidate / 'receipt.json')

    def test_conflicting_input_hashes_rejected(self):
        manifest = self.root / 'inputs.sha256'
        name = self.candidate / 'weights.bin'
        manifest.write_text(f'{sha(b"weights")}  {name}\n{sha(b"other")}  {name}\n')
        with self.assertRaises(ValueError):
            qualify.checksums(manifest)

    def test_missing_rationale_rejected(self):
        self.choice['rationale'] = ' '
        with self.assertRaises(ValueError):
            self.validate()

    def test_metrics_are_reported_not_used_to_hide_regressions(self):
        baseline = {'games': 32, 'gamesWithDelivery': 32, 'deliveriesPerMinute': 5.0, 'backForthShare': 0.0}
        candidate = {'games': 32, 'gamesWithDelivery': 1, 'firstReturnGames': 1, 'deliveriesPerMinute': 0.5, 'backForthShare': 0.5}
        values = qualify.metric_observations(3, baseline, candidate)
        self.assertFalse(values['deliveryReliabilityAtLeast90Percent'])
        self.assertFalse(values['firstPickupAtLeast90Percent'])
        self.assertFalse(values['backForthBelow2Percent'])
        self.assertFalse(values['deliveryRateNoLowerThanBaseline'])

    def test_impossible_backforth_rejected(self):
        invalid = {'games': 32, 'gamesWithDelivery': 32, 'firstReturnGames': 32, 'deliveriesPerMinute': 5.0, 'backForthShare': -1}
        with self.assertRaises(ValueError):
            qualify.metric_observations(3, invalid, invalid)

    def test_incomplete_evidence_does_not_write_receipt(self):
        output = self.root / 'out.json'
        with mock.patch.object(qualify, 'TRAIN', self.root / 'missing'), \
                mock.patch.object(sys, 'argv', [str(TOOL), '0', str(self.root / 'no-choice'), str(output)]):
            with self.assertRaisesRegex(ValueError, 'missing complete paired selection evidence'):
                qualify.main()
        self.assertFalse(output.exists())

    def test_level_two_missing_after_standard_and_level_one_fails(self):
        train = self.root / 'train'
        for label in ('standard', 'L1'):
            directory = train / f'selection-{label}'
            directory.mkdir(parents=True)
            (directory / 'pair-s0.inputs.sha256').write_text('placeholder')
            (directory / 'pair-s0.audit.json').write_text('placeholder')
        output = self.root / 'out.json'
        with mock.patch.object(qualify, 'TRAIN', train), \
                mock.patch.object(sys, 'argv', [str(TOOL), '0', str(self.root / 'no-choice'), str(output)]):
            with self.assertRaisesRegex(ValueError, 'missing complete paired selection evidence: L2'):
                qualify.main()
        self.assertFalse(output.exists())

    def test_all_pair_placeholders_cannot_bypass_attestation_gate(self):
        train = self.root / 'train'
        for label in ('standard', 'L1', 'L2', 'L3', 'L4', 'L5'):
            directory = train / f'selection-{label}'
            directory.mkdir(parents=True)
            (directory / 'pair-s0.inputs.sha256').write_text('placeholder')
            (directory / 'pair-s0.audit.json').write_text('placeholder')
        output = self.root / 'out.json'
        with mock.patch.object(qualify, 'TRAIN', train), \
                mock.patch.object(sys, 'argv', [str(TOOL), '0', str(self.root / 'no-choice'), str(output)]):
            with self.assertRaisesRegex(ValueError, 'exact argv and actor-input attestation'):
                qualify.main()
        self.assertFalse(output.exists())

    def test_recorded_nondefault_actor_interventions_rejected(self):
        clean = {'farBricks': False, 'sweepTeacher': False}
        qualify.reject_interventions(clean, 'fixture')
        for field in ('straightBiasHundredths', 'straightAfterSteps', 'sampledActions', 'ensembleMembers',
                      'ensembleUntilSteps', 'actionNoisePercent', 'noisySteps', 'selfImitationKeepSteps',
                      'selfImitationRows', 'doorPass', 'doorEarly'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                qualify.reject_interventions({**clean, field: 1}, 'fixture')
        for field in ('farBricks', 'sweepTeacher'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                qualify.reject_interventions({**clean, field: True}, 'fixture')


if __name__ == '__main__':
    unittest.main()
