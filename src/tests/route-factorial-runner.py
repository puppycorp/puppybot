#!/usr/bin/env python3
"""CPU controls for the paired factorial result checks."""
import importlib.util
import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

path = Path(__file__).resolve().parents[2] / 'datasets/visual-control/chase-v1/levels/run-route-factorial.py'
spec = importlib.util.spec_from_file_location('runner', path)
runner = importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)


class PairedTest(unittest.TestCase):
    def setUp(self):
        self.game = {'condition': 'scene', 'seed': 7800001, 'startPose': [-.04, -.04, .42],
                     'initialBrick': [2.5, .2], 'environmentSHA256': 'same'}

    def test_matching_pair(self):
        runner.paired_check(self.game, dict(self.game))

    def test_mismatched_pairs_rejected(self):
        for key, value in [('condition', 'other'), ('seed', 2), ('startPose', [0, 0, 0]),
                           ('initialBrick', [2.5, .3]), ('environmentSHA256', 'other')]:
            changed = dict(self.game); changed[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): runner.paired_check(self.game, changed)


class LifecycleTest(unittest.TestCase):
    def test_lock_contention_and_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'lock'
            with runner.acquire_lock(path):
                with self.assertRaises(BlockingIOError): runner.acquire_lock(path)
            with runner.acquire_lock(path): pass

    def test_existing_or_symlink_output_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); p = root / 'out'; runner.require_new_output(p)
            p.mkdir()
            with self.assertRaises(ValueError): runner.require_new_output(p)
            p.rmdir(); p.symlink_to(root / 'missing')
            with self.assertRaises(ValueError): runner.require_new_output(p)

    def test_capacity_and_supervision_fail_closed(self):
        usage = type('Usage', (), {'free': 1024})()
        with mock.patch.object(runner.shutil, 'disk_usage', return_value=usage):
            runner.require_capacity(Path('/tmp'), 1024)
            with self.assertRaises(RuntimeError): runner.require_capacity(Path('/tmp'), 1025)
        good = {'signal': None, 'timedOut': False, 'clientExit': 0, 'remainingWorkersTerminated': False}
        runner.require_success(good, Path('/tmp'))
        for key, value in [('signal', 15), ('timedOut', True), ('clientExit', 1), ('remainingWorkersTerminated', True)]:
            bad = dict(good); bad[key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError): runner.require_success(bad, Path('/tmp'))


class GameTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name); self.out = root / 'out'; self.out.mkdir(); (self.out / 'policy').mkdir()
        package = root / 'package'; model = package / 'control'; model.mkdir(parents=True)
        (model / 'weights.bin').write_bytes(b'weights'); self.package = mock.patch.object(runner, 'PACKAGE', package)
        self.package.start(); self.addCleanup(self.package.stop)
        self.snapshot = mock.patch.object(runner.selection, 'snapshot', return_value=runner.sha(model / 'weights.bin'))
        self.snapshot.start(); self.addCleanup(self.snapshot.stop)
        self.coverage = mock.patch.object(runner.coverage, 'game', return_value={'startPose': [-.04, -.04, .42]})
        self.coverage.start(); self.addCleanup(self.coverage.stop)
        self.game = self.out / '7800001'; self.game.mkdir(); scene = self.game / 'scene'; scene.mkdir()
        (scene / 'case.json').write_bytes(b'case'); (scene / 'environment.bin').write_bytes(b'environment')
        (self.game / 'native.log').write_text('normal'); (self.out / 'policy.log').write_text('normal')
        self.condition = {'name': 'condition', 'layout': 15, 'seed': 7800001, 'startPose': [-.04, -.04, .42],
                          'caseSHA256': runner.sha(scene / 'case.json'), 'environmentSHA256': runner.sha(scene / 'environment.bin')}
        self.result = {'seed': 7800001, 'game': 'fetch', 'controller': 'native neural policy', 'level': 5,
                       'levelPlacement': 'other room', 'steps': 300, 'actionSeconds': 60, 'blackout': False,
                       'farBricks': False, 'exploreTeacher': False, 'sweepTeacher': False, 'suppliedMap': False,
                       'taskEventHint': False, 'carryCue': True, 'policyWeightsSHA256': runner.sha(model / 'weights.bin')}

    def save(self):
        (self.game / 'result.json').write_text(json.dumps(self.result))

    def test_valid_and_bad_declarations(self):
        self.save(); runner.validate_game(self.condition, 'control', self.out)
        for key, value in [('seed', 2), ('policyWeightsSHA256', 'wrong'), ('sweepTeacher', True),
                           ('doorPass', True), ('carryCue', False)]:
            old = dict(self.result); self.result[key] = value; self.save()
            with self.subTest(key=key), self.assertRaises(ValueError): runner.validate_game(self.condition, 'control', self.out)
            self.result = old

    def test_bad_scene_start_and_timeout(self):
        self.save(); scene = self.game / 'scene/case.json'; scene.write_bytes(b'other')
        with self.assertRaises(ValueError): runner.validate_game(self.condition, 'control', self.out)
        scene.write_bytes(b'case'); self.condition['startPose'] = [0, 0, 0]
        with self.assertRaises(ValueError): runner.validate_game(self.condition, 'control', self.out)
        self.condition['startPose'] = [-.04, -.04, .42]; (self.game / 'native.log').write_text('timed out')
        with self.assertRaises(ValueError): runner.validate_game(self.condition, 'control', self.out)


if __name__ == '__main__':
    unittest.main()
