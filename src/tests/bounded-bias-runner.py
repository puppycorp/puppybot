#!/usr/bin/env python3
"""CPU fixtures for matched bounded-bias result and pairing gates."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

root = Path(__file__).resolve().parents[2]
p = root / 'datasets/visual-control/chase-v1/levels/run-bounded-bias.py'
s = importlib.util.spec_from_file_location('bias_runner', p)
runner = importlib.util.module_from_spec(s); s.loader.exec_module(runner)


class BiasRunnerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name); model = d / 'model'; model.mkdir(); (model / 'weights.bin').write_bytes(b'w')
        self.model = mock.patch.object(runner, 'MODEL', model); self.model.start(); self.addCleanup(self.model.stop)
        self.snapshot = mock.patch.object(runner.base.selection, 'snapshot', return_value=runner.base.sha(model / 'weights.bin'))
        self.snapshot.start(); self.addCleanup(self.snapshot.stop)
        self.out = d / 'run'; self.out.mkdir(); (self.out / 'policy').mkdir(); (self.out / 'policy.log').write_text('ok')
        self.game = self.out / '7800001'; self.game.mkdir(); scene = self.game / 'scene'; scene.mkdir()
        (scene / 'case.json').write_text('{}')
        env = root / 'build/flex/sim/expanded-rooms-v1/scenes/15/1/environment.bin'
        (scene / 'environment.bin').write_bytes(env.read_bytes()); (self.game / 'native.log').write_text('ok')
        self.condition = {'seed': 7800001, 'name': 'test', 'layout': 15, 'startPose': [-.04, -.04, .42],
                          'caseSHA256': runner.base.sha(scene / 'case.json'), 'environmentSHA256': runner.base.sha(scene / 'environment.bin')}
        self.result = {'seed': 7800001, 'game': 'fetch', 'controller': 'native neural policy', 'level': 5,
                       'levelPlacement': 'other room', 'maximumBrickDistanceM': .35,
                       'steps': 300, 'actionSeconds': 60, 'blackout': False, 'farBricks': False,
                       'exploreTeacher': False, 'sweepTeacher': False, 'suppliedMap': False, 'taskEventHint': False,
                       'carryCue': True, 'policyWeightsSHA256': runner.base.sha(model / 'weights.bin'),
                       'straightBiasHundredths': 50, 'straightAfterSteps': 70, 'straightWindowSteps': 30,
                       'straightEligibleSteps': 30, 'straightChangedSteps': 1, 'deliveries': 0, 'backForthSteps': 0}
        self.rows = [{'step': 100 + i * 10, 'action': [0, 1], 'state': {'pose': [-.04, -.04, .42],
                      'trainingOracle': {'enabled': False, 'queries': 0}, 'findReturn': {'phase': 'search', 'consumedIndex': -1, 'deliveries': 0}}} for i in range(300)]
        (self.game / 'chase.jsonl').write_text(json.dumps({'event':'start', 'step': 0, 'robot':[-.04, -.04, .42], 'brick':[2.5, 0]}) + '\n')

    def save(self):
        (self.game / 'result.json').write_text(json.dumps(self.result))
        (self.game / 'decisions.jsonl').write_text(''.join(json.dumps(x) + '\n' for x in self.rows))

    def test_valid_and_invalid_counts(self):
        self.save(); data, actions = runner.validate_game(self.condition, 'treatment', self.out, 5)
        self.assertEqual(data['biasChangedSteps'], 1); self.assertEqual(len(actions), 300)
        for name, value in [('straightEligibleSteps', -1), ('straightChangedSteps', 31), ('straightWindowSteps', 31),
                            ('straightAfterSteps', 1000), ('carryCue', False), ('doorPass', True), ('backForthSteps', 1)]:
            old = dict(self.result); self.result[name] = value; self.save()
            with self.subTest(name=name), self.assertRaises(ValueError): runner.validate_game(self.condition, 'treatment', self.out, 5)
            self.result = old

    def test_oracle_bad_pose_and_timeout(self):
        self.rows[0]['state']['trainingOracle']['queries'] = 1; self.save()
        with self.assertRaises(ValueError): runner.validate_game(self.condition, 'treatment', self.out, 5)
        self.rows[0]['state']['trainingOracle']['queries'] = 0; self.rows[0]['state']['pose'][0] = float('nan'); self.save()
        with self.assertRaises(ValueError): runner.validate_game(self.condition, 'treatment', self.out, 5)
        self.rows[0]['state']['pose'][0] = -.04; self.rows[0]['action'] = [.13, 1]; self.save()
        with self.assertRaises(ValueError): runner.validate_game(self.condition, 'treatment', self.out, 5)
        self.rows[0]['action'] = [0, 1]; self.save(); (self.game / 'native.log').write_text('timed out')
        with self.assertRaises(ValueError): runner.validate_game(self.condition, 'treatment', self.out, 5)

    def test_pair_must_match_inputs_and_first_70_actions(self):
        self.save(); data, actions = runner.validate_game(self.condition, 'treatment', self.out, 5)
        no_change = dict(data); no_change['biasChangedSteps'] = 0
        self.assertIsNone(runner.pair_check(data, no_change, actions, list(actions)))
        with self.assertRaises(ValueError): runner.pair_check(data, dict(data), actions, list(actions))
        changed = list(actions); changed[69] = [1, 1]
        with self.assertRaises(ValueError): runner.pair_check(data, dict(data), actions, changed)
        changed[69] = actions[69]; changed[70] = [1, 1]
        self.assertEqual(runner.pair_check(data, dict(data), actions, changed), 71)
        wrong = dict(data); wrong['initialBrick'] = [2.6, 0]
        with self.assertRaises(ValueError): runner.pair_check(data, wrong, actions, actions)

    def test_eligibility_tracks_pickup_and_placement(self):
        for i in range(74, 100):
            self.rows[i]['state']['findReturn']['consumedIndex'] = 0
        for i in range(99, 300):
            self.rows[i]['state']['findReturn']['deliveries'] = 1
        events = [{'event': 'start', 'step': 0}, {'event': 'delivery', 'step': 100}]
        self.assertEqual(runner.eligible_steps(self.rows, events, 70), 35)
        self.assertEqual(runner.eligible_steps(self.rows, events, 1000), 0)
        events[1]['step'] = 99
        with self.assertRaises(ValueError): runner.eligible_steps(self.rows, events, 70)

    def test_incorrect_eligible_count_rejected(self):
        self.result['straightEligibleSteps'] = 29; self.save()
        with self.assertRaises(ValueError): runner.validate_game(self.condition, 'treatment', self.out, 5)


if __name__ == '__main__': unittest.main()
