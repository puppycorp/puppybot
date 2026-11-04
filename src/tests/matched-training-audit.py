#!/usr/bin/env python3
"""CPU tests for matched-training recorded-artifact audit."""
import importlib.util
import json
import struct
import tempfile
import unittest
from pathlib import Path

root = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('audit', root / 'datasets/visual-control/chase-v1/levels/audit-matched-training.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class TrainingAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.parent, self.control, self.treatment = [Path(self.tmp.name) / n for n in ('parent', 'control', 'treatment')]
        for d in (self.parent, self.control, self.treatment):
            d.mkdir()
        (self.parent / 'weights.bin').write_bytes(b'initial')
        for d in (self.control, self.treatment):
            (d / 'initial.bin').write_bytes(b'initial')
            for name in ('first-order.bin', 'final-order.bin'):
                (d / name).write_bytes(struct.pack('<1024Q', *range(1024)))
            (d / 'first-mirror-mask.bin').write_bytes(struct.pack('<Q', 3))
            rows = [{'epoch': n, 'optimizerSteps': 464*n, 'mirroredTrainingSequences': n} for n in range(9)]
            (d / 'curves.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))

    def test_matching(self):
        self.assertEqual(audit.audit(self.parent, self.control, self.treatment)['optimizerSteps'], 3712)

    def test_artifact_mismatch_rejected(self):
        (self.treatment / 'first-order.bin').write_bytes(b'other')
        with self.assertRaises(ValueError):
            audit.audit(self.parent, self.control, self.treatment)

    def test_optimizer_mismatch_rejected(self):
        p = self.treatment / 'curves.jsonl'
        rows = [json.loads(line) for line in p.read_text().splitlines()]
        rows[-1]['optimizerSteps'] -= 1
        p.write_text(''.join(json.dumps(r) + '\n' for r in rows))
        with self.assertRaises(ValueError):
            audit.audit(self.parent, self.control, self.treatment)

    def test_mirror_count_mismatch_rejected(self):
        p = self.treatment / 'curves.jsonl'
        rows = [json.loads(line) for line in p.read_text().splitlines()]
        rows[1]['mirroredTrainingSequences'] += 1
        p.write_text(''.join(json.dumps(r) + '\n' for r in rows))
        with self.assertRaises(ValueError):
            audit.audit(self.parent, self.control, self.treatment)

    def test_impossible_matching_mirror_counts_rejected(self):
        for value in (True, 1000):
            for d in (self.control, self.treatment):
                p = d / 'curves.jsonl'
                rows = [json.loads(line) for line in p.read_text().splitlines()]
                rows[1]['mirroredTrainingSequences'] = value
                p.write_text(''.join(json.dumps(r) + '\n' for r in rows))
            with self.assertRaises(ValueError):
                audit.audit(self.parent, self.control, self.treatment)

    def test_identical_malformed_artifacts_rejected(self):
        cases = [('first-order.bin', b'short'), ('final-order.bin', bytes(8192)),
                 ('first-mirror-mask.bin', b''), ('first-mirror-mask.bin', struct.pack('<Q', 4))]
        for name, content in cases:
            old = (self.control / name).read_bytes()
            for d in (self.control, self.treatment):
                (d / name).write_bytes(content)
            with self.assertRaises(ValueError):
                audit.audit(self.parent, self.control, self.treatment)
            for d in (self.control, self.treatment):
                (d / name).write_bytes(old)


if __name__ == '__main__':
    unittest.main()
