#!/usr/bin/env python3
"""Synthetic fresh-selection contract and goal-metric fixtures."""
import copy
import importlib.util
import math
import struct
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


contract = load('fresh_contract_test', HERE / 'protocol.py')
metrics = load('fresh_metrics_test', HERE / 'metrics.py')
prior = load('fresh_prior_fixture', ROOT / 'experiments/outbound-five-selection-metrics-v1/test.py')
MODELS = {'parent': 'c' * 64, 'control': 'a' * 64, 'treatment': 'b' * 64, 'teacher': None}


def summarize(level, values, *, arm, score_version):
    return metrics.summarize(level, values, arm=arm, score_version=score_version, expected_weights=MODELS[arm])


def compare(parent, control, treatment, teacher, *, score_version):
    return metrics.compare(parent, control, treatment, teacher, score_version=score_version, expected_models=MODELS)


def games(level, successes=0, reversals=False, arm='control'):
    base = 1800000000 + level * 100
    result = [prior.make_game(base + index, final_pickup=index < successes, reversals=reversals)
              for index in range(32)]
    for index, game in enumerate(result):
        teacher = arm == 'teacher'
        game['result'].update({'game': 'fetch', 'level': level, 'actionSeconds': 60.0,
            'levelPlacement': {1: 'in view', 2: 'just off view', 3: 'same room out of view',
                               4: 'doorway drill', 5: 'other room'}[level],
            'controller': 'exploring fetch teacher' if teacher else 'native neural policy',
            'policyWeightsSHA256': MODELS[arm], 'blackout': False,
            'farBricks': False, 'suppliedMap': False, 'taskEventHint': False, 'carryCue': True,
            'exploreTeacher': teacher, 'sweepTeacher': False})
        game['initial'] = {'pose': list(game['events'][0]['robot']),
                           'findReturn': {'phase': 'search', 'consumedIndex': -1, 'deliveries': 0}}
        game['scene'] = {'case.json': f'case-{level}-{index}'.encode(),
                         'environment.bin': f'world-{level}-{index}'.encode(),
                         'layout.json': f'layout-{level}-{index}'.encode()}
    return result


def doorway_environment():
    data = bytearray(256 + 128)
    data[:8] = b'PBENV001'
    struct.pack_into('<q', data, 8, 1)
    data[256:272] = b'Wall.partition-a'
    struct.pack_into('<d', data, 256 + 48, 1.0)
    return bytes(data)


class ContractTest(unittest.TestCase):
    def test_fixed_identity_and_isolation(self):
        plan = contract.contract()
        self.assertEqual(plan['status'], 'design_only_not_registered')
        self.assertEqual(len(plan['rows']), 160)
        self.assertEqual([arm['name'] for arm in plan['arms']], ['parent', 'control', 'treatment', 'teacher'])
        self.assertEqual(len({row['seed'] for row in plan['rows']}), 160)
        self.assertTrue(all(290 <= row['layoutId'] <= 353 for row in plan['rows']))
        for row in plan['rows']:
            self.assertEqual(row['seed'], 1800000000 + 100 * row['level'] + row['index'])
            self.assertEqual(row['variant'], row['index'] % 16)
            if row['level'] >= 4: self.assertEqual(row['layoutId'] % 2, 1)

    def test_failed_games_cannot_be_dropped_to_fake_success(self):
        values = games(3, successes=28)
        result = summarize(3, values, arm='control', score_version='legacy-v1')
        self.assertFalse(result['deliveryReliabilityAtLeast90Percent'])
        self.assertFalse(result['level3FirstPickupAtLeast90Percent'])
        with self.assertRaises(ValueError): summarize(3, values[:-1], arm='control', score_version='legacy-v1')
        duplicate = copy.deepcopy(values); duplicate[-1]['result']['seed'] = duplicate[0]['result']['seed']
        with self.assertRaises(ValueError): summarize(3, duplicate, arm='control', score_version='legacy-v1')
        wrong_seed = copy.deepcopy(values); wrong_seed[0]['result']['seed'] = 1700000300
        with self.assertRaises(ValueError): summarize(3, wrong_seed, arm='control', score_version='legacy-v1')
        incomplete = copy.deepcopy(values); incomplete[-1]['rows'].pop()
        with self.assertRaises(ValueError): summarize(3, incomplete, arm='control', score_version='legacy-v1')
        wrong_mode = copy.deepcopy(values); wrong_mode[0]['result']['blackout'] = True
        with self.assertRaises(ValueError): summarize(3, wrong_mode, arm='control', score_version='legacy-v1')
        wrong_initial = copy.deepcopy(values); wrong_initial[0]['initial']['pose'][0] = 1
        with self.assertRaises(ValueError): summarize(3, wrong_initial, arm='control', score_version='legacy-v1')
        wrong_model = copy.deepcopy(values); wrong_model[0]['result']['policyWeightsSHA256'] = 'c' * 64
        with self.assertRaises(ValueError): summarize(3, wrong_model, arm='control', score_version='legacy-v1')

    def test_29_games_passes_game_threshold_but_not_loop_threshold(self):
        result = summarize(3, games(3, successes=29, reversals=True), arm='control', score_version='legacy-v1')
        self.assertTrue(result['deliveryReliabilityAtLeast90Percent'])
        self.assertTrue(result['level3FirstPickupAtLeast90Percent'])
        self.assertGreater(result['inclusiveBackForthActions'], 0)
        self.assertGreater(result['longSearch100TruthActions'], 0)
        self.assertFalse(result['inclusiveBackForthBelow2Percent'])

    def test_long_window_includes_terminal_state_and_stationary_time(self):
        game = games(1)[0]; rows = game['rows']
        result = metrics.long_search_100(rows, game['initial'])
        self.assertEqual(result['windows'], 201)
        self.assertEqual(result['actions'], 300)
        # Only the final window's last saved state enters return phase.
        rows[-1]['state']['findReturn']['phase'] = 'return'
        result = metrics.long_search_100(rows, game['initial'])
        self.assertEqual(result['windows'], 200)
        self.assertEqual(result['actions'], 299)
        game = games(1)[0]; rows = game['rows']
        rows[-1]['state']['pose'][2] = math.pi
        self.assertEqual(metrics.long_search_100(rows, game['initial'])['windows'], 200)
        game = games(1)[0]; rows = game['rows']
        for index in range(100, 300): rows[index]['state']['pose'][0] = 10 + index
        self.assertEqual(metrics.long_search_100(rows, game['initial']),
                         {'actions': 100, 'windows': 1,
                          'scope': '100-transition truth-pose search return; includes stationary periods and misses other loops'})

    def test_saved_metric_version_is_explicitly_checked(self):
        values = games(5, reversals=True)
        for game in values:
            legacy = game['result']['backForthSteps']
            full = len(metrics.previous.windows.marks(game['rows'], game['events'][0]['robot'], True))
            self.assertEqual(full - legacy, 1)
            game['result']['backForthMetric'] = 'pose20-final-inclusive-v2'
            game['result']['backForthSteps'] = full
        self.assertEqual(summarize(5, values, arm='control', score_version='pose20-final-inclusive-v2')['inclusiveBackForthActions'], 32 * full)
        values[0]['result']['backForthMetric'] = 'unrecognized'
        with self.assertRaisesRegex(ValueError, 'version differs'):
            summarize(5, values, arm='control', score_version='pose20-final-inclusive-v2')

    def test_censored_final_door_placement_stays_in_denominator(self):
        values = games(4, successes=32)
        for game in values:
            game['scene']['environment.bin'] = doorway_environment()
            for event in game['events']:
                event['robot'] = [0.0, 0.0, 0.0]
                event['brick'] = [2.0, 0.0]
        result = summarize(4, values, arm='control', score_version='legacy-v1')['doorway']
        self.assertEqual((result['placements'], result['delivered'], result['rightCensoredAtHorizon'],
                          result['zeroTimePlacements']), (64, 32, 32, 32))
        self.assertFalse(result['atLeast80PercentDeliveredByHorizon'])

    def test_teacher_rate_does_not_replace_reliability(self):
        parent = summarize(1, games(1, successes=30, arm='parent'), arm='parent', score_version='legacy-v1')
        control = summarize(1, games(1, successes=32), arm='control', score_version='legacy-v1')
        treatment = summarize(1, games(1, successes=28, arm='treatment'), arm='treatment', score_version='legacy-v1')
        teacher = summarize(1, games(1, successes=27, arm='teacher'), arm='teacher', score_version='legacy-v1')
        result = compare(parent, control, treatment, teacher, score_version='legacy-v1')
        self.assertTrue(result['parentRateAtLeastTeacher'])
        self.assertTrue(result['treatmentRateAtLeastTeacher'])
        self.assertEqual(result['treatmentDeliveredGamesMinusControl'], -4)
        self.assertEqual((result['matchedTreatmentWins'], result['matchedTreatmentLosses']), (0, 4))
        self.assertFalse(result['treatmentDeliveredGamesAtLeastControl'])
        self.assertFalse(result['treatmentDeliveredGamesAtLeastParent'])
        self.assertEqual((result['matchedTreatmentWinsVersusParent'], result['matchedTreatmentLossesVersusParent']), (0, 2))
        self.assertFalse(treatment['deliveryReliabilityAtLeast90Percent'])
        changed = copy.deepcopy(teacher); changed['perGame'][0]['startBrick'][0] = 999
        with self.assertRaisesRegex(ValueError, 'initial placement'):
            compare(parent, control, treatment, changed, score_version='legacy-v1')
        changed = copy.deepcopy(treatment); changed['perGame'][0]['sceneSHA256']['case.json'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'scene or initial placement'):
            compare(parent, control, changed, teacher, score_version='legacy-v1')
        changed = copy.deepcopy(teacher); changed['scoreVersion'] = 'pose20-final-inclusive-v2'
        with self.assertRaisesRegex(ValueError, 'incomparable'):
            compare(parent, control, treatment, changed, score_version='legacy-v1')
        changed = copy.deepcopy(treatment); changed['weightsSHA256'] = 'c' * 64
        with self.assertRaisesRegex(ValueError, 'incomparable'):
            compare(parent, control, changed, teacher, score_version='legacy-v1')
        changed = copy.deepcopy(parent); changed['perGame'][0]['startRobot'][0] = 99
        with self.assertRaisesRegex(ValueError, 'scene or initial placement'):
            compare(changed, control, treatment, teacher, score_version='legacy-v1')

    def test_parent_rate_reports_less_and_equal_to_teacher(self):
        control = summarize(1, games(1, successes=32), arm='control', score_version='legacy-v1')
        treatment = summarize(1, games(1, successes=28, arm='treatment'), arm='treatment', score_version='legacy-v1')
        teacher = summarize(1, games(1, successes=27, arm='teacher'), arm='teacher', score_version='legacy-v1')
        for successes, expected in ((26, False), (27, True), (28, True)):
            parent = summarize(1, games(1, successes=successes, arm='parent'), arm='parent', score_version='legacy-v1')
            result = compare(parent, control, treatment, teacher, score_version='legacy-v1')
            self.assertIs(result['parentRateAtLeastTeacher'], expected)


if __name__ == '__main__':
    unittest.main()
