#!/usr/bin/env python3
"""Synthetic fail-closed checks for the virtual-fetch held-out game reader."""
import hashlib
import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LEVELS = ROOT / 'datasets/visual-control/chase-v1/levels'
spec = importlib.util.spec_from_file_location('heldout', LEVELS / 'audit-heldout.py')
heldout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(heldout)


def sha(data):
    return hashlib.sha256(data).hexdigest()


class HeldoutAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.model = self.base / 'model'
        (self.model / 'kernels').mkdir(parents=True)
        receipt = {'weightsSHA256': sha(b'weights'), 'binarySHA256': sha(b'policy'), 'kernels': {'a': sha(b'kernel')}}
        self.receipt = json.dumps(receipt).encode()
        for name, content in [('receipt.json', self.receipt), ('weights.bin', b'weights'), ('policy', b'policy'), ('kernels/a', b'kernel')]:
            (self.model / name).write_bytes(content)
        self.root = self.base / 'candidate'
        self.root.mkdir()
        self.expected = {}
        for part in range(4):
            directory = self.root / str(part)
            (directory / 'policy' / 'kernels').mkdir(parents=True)
            for name, content in [('receipt.json', self.receipt), ('weights.bin', b'weights'), ('policy', b'policy'), ('kernels/a', b'kernel')]:
                (directory / 'policy' / name).write_bytes(content)
            (self.root / f'{part}.log').write_text('ok')
            (directory / 'policy.log').write_text('ok')
            for index in range(8):
                seed = 1700000100 + part * 8 + index
                game = directory / str(seed)
                (game / 'scene').mkdir(parents=True)
                (game / 'scene' / 'case.json').write_bytes(b'case')
                (game / 'scene' / 'environment.bin').write_bytes(b'env')
                result = {'seed': seed, 'game': 'fetch', 'controller': 'native neural policy', 'steps': 300, 'actionSeconds': 60, 'level': 1, 'blackout': False,
                          'suppliedMap': False, 'taskEventHint': False, 'carryCue': True, 'maximumBrickDistanceM': 0.35,
                          'levelPlacement': 'in view', 'policyWeightsSHA256': receipt['weightsSHA256'],
                          'exploreTeacher': False, 'deliveries': 0, 'backForthSteps': 0}
                (game / 'result.json').write_text(json.dumps(result))
                (game / 'decisions.jsonl').write_text((json.dumps({'action': [0, 0], 'state': {'pose': [0, 0, 0], 'findReturn': {'phase': 'search'}}}) + '\n') * 300)
                (game / 'chase.jsonl').write_text(json.dumps({'event': 'start', 'robot': [0, 0, 0]}) + '\n')
                (game / 'native.log').write_text('ok')
                self.expected[seed] = {'index': part * 8 + index, 'caseSHA256': sha(b'case'), 'environmentSHA256': sha(b'env'), 'startPose': [0, 0, 0]}

    def tearDown(self):
        self.temp.cleanup()

    def load(self):
        return heldout.load_games(self.root, self.expected, self.model, 1, heldout.load_helpers())

    def test_complete_games_accepted(self):
        self.assertEqual(len(self.load()), 32)

    def test_wrong_scene_rejected(self):
        (self.root / '0' / '1700000100' / 'scene' / 'environment.bin').write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.load()

    def test_incomplete_decisions_rejected(self):
        (self.root / '0' / '1700000100' / 'decisions.jsonl').write_text('{}\n')
        with self.assertRaises(ValueError):
            self.load()

    def test_timeout_rejected(self):
        (self.root / '0.log').write_text('policy stream timed out')
        with self.assertRaises(ValueError):
            self.load()

    def test_changed_policy_snapshot_rejected(self):
        (self.root / '0' / 'policy' / 'kernels' / 'a').write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.load()

    def test_wrong_start_rejected(self):
        (self.root / '0' / '1700000100' / 'chase.jsonl').write_text(json.dumps({'event': 'start', 'robot': [1, 0, 0]}) + '\n')
        with self.assertRaises(ValueError):
            self.load()

    def test_impossible_backforth_rejected(self):
        path = self.root / '0' / '1700000100' / 'result.json'
        result = json.loads(path.read_text())
        result['backForthSteps'] = -9999
        path.write_text(json.dumps(result))
        with self.assertRaises(ValueError):
            self.load()

    def test_reported_backforth_must_match_decisions(self):
        path = self.root / '0' / '1700000100' / 'result.json'
        result = json.loads(path.read_text())
        result['backForthSteps'] = 20
        path.write_text(json.dumps(result))
        with self.assertRaises(ValueError):
            self.load()

    def test_missing_required_input_manifest_entry_rejected(self):
        manifest = self.base / 'inputs.sha256'
        manifest.write_text(f'{sha(b"weights")}  {self.model / "weights.bin"}\n')
        hashes = heldout.input_hashes(manifest)
        heldout.require_pinned(hashes, self.model / 'weights.bin')
        with self.assertRaises(ValueError):
            heldout.require_pinned(hashes, self.model / 'policy')

    def test_changed_required_input_rejected(self):
        manifest = self.base / 'inputs.sha256'
        manifest.write_text(f'{sha(b"weights")}  {self.model / "weights.bin"}\n')
        hashes = heldout.input_hashes(manifest)
        (self.model / 'weights.bin').write_bytes(b'changed')
        with self.assertRaises(ValueError):
            heldout.require_pinned(hashes, self.model / 'weights.bin')

    def test_teacher_requires_correct_shard_provenance(self):
        teacher = self.base / 'teacher'
        teacher.mkdir()
        for part in range(4):
            target = teacher / str(part)
            target.mkdir()
            (teacher / f'{part}.log').write_text('ok')
            report = {'complete': True, 'studentDriven': False, 'teacher': 'exploring fetch teacher',
                      'episodes': 8, 'sequenceLength': 300, 'seed': 1700000100 + part * 8,
                      'teacherUsesCameraDetections': True, 'teacherUsesTargetCoordinates': False}
            (target / 'report.json').write_text(json.dumps(report))
            for index in range(8):
                seed = 1700000100 + part * 8 + index
                game = target / f'expert-{index}'
                shutil.copytree(self.root / str(part) / str(seed), game)
                result = json.loads((game / 'result.json').read_text())
                result.update({'controller': 'exploring fetch teacher', 'exploreTeacher': True})
                (game / 'result.json').write_text(json.dumps(result))
        self.assertEqual(len(heldout.load_games(teacher, self.expected, None, 1, heldout.load_helpers())), 32)
        report_path = teacher / '0' / 'report.json'
        report = json.loads(report_path.read_text())
        report['teacherUsesTargetCoordinates'] = True
        report_path.write_text(json.dumps(report))
        with self.assertRaises(ValueError):
            heldout.load_games(teacher, self.expected, None, 1, heldout.load_helpers())

    def test_changed_seed_mapping_rejected_before_results(self):
        catalog = self.base / 'catalog'
        output = self.base / 'output'
        catalog.mkdir()
        output.mkdir()
        rows = []
        for level in range(1, 6):
            for index in range(32):
                layout = 226 + index if level < 4 else 227 + 2 * index
                rows.append({'level': level, 'index': index, 'seed': 1700000000 + level * 100 + index,
                             'layoutId': layout, 'scene': f'generated/{layout}/{index % 16}'})
        rows[0]['seed'] += 1
        (catalog / 'manifest.json').write_text(json.dumps({'status': 'reserved_not_evaluated', 'task': 'virtual-fetch', 'rows': rows}))
        (output / 'registration.json').write_text('{}')
        result = subprocess.run(['python3', '-I', str(LEVELS / 'audit-heldout.py'), str(catalog), str(self.model), str(output)], text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unexpected held-out mapping', result.stderr)


if __name__ == '__main__':
    unittest.main()
