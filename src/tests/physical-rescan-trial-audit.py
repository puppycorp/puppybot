#!/usr/bin/env python3
# Focused checks for the rendered rescan trial's fail-closed observation audit.
import importlib.util
import unittest
from pathlib import Path

path = Path(__file__).with_name('run-physical-rescan-trial.py')
spec = importlib.util.spec_from_file_location('rescan_trial', path)
trial = importlib.util.module_from_spec(spec); spec.loader.exec_module(trial)


def fixture():
    result = {'policyActions': 1, 'stoppedRescanEnabled': True, 'stoppedRescanAttempts': 2,
              'stoppedRescanHandoff': False, 'stoppedRescanStopReason': 2,
              'stopCommandAcknowledged': True, 'handoff': False, 'outcome': 'unverified'}
    rows = []
    for i, (ack, tick) in enumerate(zip((0, 1, 2, 1, 2, 7), (100, 110, 112, 113, 115, 115))):
        valid = i != 5
        rows.append({'ack': ack, 'sequence': i + 1, 'totalSteps': tick,
                     'owner': 0 if valid else 2, 'imageValid': valid, 'rgbDetections': 0 if valid else None,
                     'cameraFrame': tick if valid else -1, 'cameraDriving': valid, 'cameraStill': valid,
                     'jointTicks': [1, 2, 3, 4], 'driveCommand': [0, 0, 90]})
    return result, rows


class RescanAuditTest(unittest.TestCase):
    def test_valid(self):
        trial.verify_observations(*fixture())

    def test_rejects_changed_results_and_observations(self):
        mutations = [
            lambda r, j: r.update(stoppedRescanAttempts=1),
            lambda r, j: r.update(stopCommandAcknowledged=False),
            lambda r, j: j[2].update(rgbDetections=1),
            lambda r, j: j[2].update(totalSteps=110),
            lambda r, j: j[3].update(driveCommand=[1, 0, 90]),
            lambda r, j: j[4].update(cameraFrame=113),
            lambda r, j: j[4].update(jointTicks=[1, 2, 4, 4]),
            lambda r, j: j[5].update(owner=0),
            lambda r, j: j[5].update(sequence=5),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                result, journal = fixture(); mutation(result, journal)
                with self.assertRaises(ValueError):
                    trial.verify_observations(result, journal)


if __name__ == '__main__':
    unittest.main()
