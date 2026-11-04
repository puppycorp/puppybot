#!/usr/bin/env python3
"""Exercise selection-metric boundaries using synthetic virtual games."""
import copy
import importlib.util
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('selection_metrics', HERE / 'metrics.py')
metrics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metrics)


def make_game(seed, *, final_pickup=False, reversals=False):
    rows = []
    for index in range(300):
        final = final_pickup and index == 299
        speed = -1.0 if reversals and index >= 280 and index % 2 else 1.0
        rows.append({'step': 100 + 10 * index, 'action': [0.0, speed],
                     'state': {'pose': [0.0, 0.0, 0.0],
                               'localization': {'mode': 'wheel-drift', 'pose': [0.0, 0.0, 0.0]},
                               'findReturn': {'phase': 'delivered' if final else 'search',
                                              'consumedIndex': 0 if final else -1,
                                              'deliveries': 1 if final else 0}}})
    events = [{'event': 'start', 'step': 0, 'robot': [0.0, 0.0, 0.0], 'brick': [1.0, 0.0]}]
    if final_pickup:
        events.append({'event': 'delivery', 'step': 300, 'robot': [0.0, 0.0, 0.0], 'brick': [1.0, 0.0]})
    result = {'seed': seed, 'steps': 300, 'reaches': int(final_pickup), 'deliveries': int(final_pickup),
              'backForthSteps': len(metrics.windows.marks(rows, events[0]['robot'], False))}
    return {'result': result, 'rows': rows, 'events': events, 'environmentPath': None}


def games(**kwargs):
    return [make_game(metrics.BASE + i, **kwargs) for i in range(metrics.GAMES)]


class SelectionMetricsTest(unittest.TestCase):
    def test_exact_consumption_even_if_no_return_phase_is_saved(self):
        result = metrics.summarize(games(final_pickup=True), 3)
        self.assertEqual(result['firstVirtualConsumptionGames'], 32)
        self.assertTrue(result['firstVirtualConsumptionAtLeast90Percent'])
        self.assertEqual(result['gamesWithDelivery'], 32)
        self.assertTrue(result['deliveryReliabilityAtLeast90Percent'])
        self.assertEqual(result['perGame'][0]['firstVirtualConsumptionAction'], 300)

    def test_inclusive_terminal_window_is_counted_once(self):
        result = metrics.summarize(games(reversals=True), 5)
        self.assertEqual(result['inclusiveBackForthActions'] - result['legacyBackForthActions'], 32)
        self.assertEqual(result['perGame'][0]['finalWindowAdditionalActions'], 1)

    def test_incomplete_duplicate_and_wrong_legacy_are_rejected(self):
        examples = games()
        with self.assertRaises(ValueError): metrics.summarize(examples[:-1], 1)
        duplicate = copy.deepcopy(examples); duplicate[-1]['result']['seed'] = metrics.BASE
        with self.assertRaises(ValueError): metrics.summarize(duplicate, 1)
        altered = copy.deepcopy(examples); altered[0]['result']['backForthSteps'] = 1
        with self.assertRaises(ValueError): metrics.summarize(altered, 1)

    def test_long_loop_is_a_separate_odometry_measure(self):
        examples = games()
        # Every five actions move around a one-metre loop; 50-action windows
        # end near their start with ample travel, while speeds never reverse.
        path = [[0.0, 0.0], [.25, 0.0], [.25, .25], [0.0, .25], [0.0, 0.0]]
        for game in examples:
            for i, row in enumerate(game['rows']):
                point = path[i % 5]
                row['state']['pose'] = [*point, 0.0]
                row['state']['localization']['pose'] = [*point, 0.0]
        result = metrics.summarize(examples, 1)
        self.assertGreater(result['longSearchLoopActions'], 0)
        self.assertEqual(result['inclusiveBackForthActions'], 0)

    def test_doorway_denominator_includes_new_placement_at_horizon(self):
        examples = games(final_pickup=True)
        environment = (metrics.ROOT / 'build/flex/sim/expanded-rooms-v1/scenes/13/0/environment.bin')
        wall = metrics.metrics.partition(environment.read_bytes())
        for game in examples:
            game['environmentPath'] = environment
            for event in game['events']:
                event['robot'] = [wall - 1, 0.0, 0.0]
                event['brick'] = [wall + 1, 0.0]
        result = metrics.summarize(examples, 4)['doorway']
        self.assertEqual((result['placements'], result['delivered'], result['rightCensoredAtHorizon'],
                          result['zeroTimePlacements']), (64, 32, 32, 32))
        self.assertFalse(result['atLeast80PercentDeliveredByHorizon'])

    def test_teacher_rate_and_reliability_comparisons_are_separate(self):
        control = metrics.summarize(games(final_pickup=True), 1)
        teacher = copy.deepcopy(control); teacher['deliveries'] = 31
        candidate = copy.deepcopy(control); candidate['gamesWithDelivery'] = 28
        result = metrics.compare({'control': control, 'treatment': candidate, 'teacher': teacher})
        self.assertTrue(result['candidateDeliveryRateAtLeastTeacher'])
        self.assertFalse(result['candidateDeliveredGamesAtLeastControl'])
        self.assertFalse(result['candidateDeliveredGamesAtLeastTeacher'])
        with self.assertRaises(ValueError): metrics.compare({'control': control, 'teacher': teacher})


if __name__ == '__main__':
    unittest.main()
