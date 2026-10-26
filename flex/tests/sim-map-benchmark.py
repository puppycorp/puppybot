#!/usr/bin/env python3
"""Check map scores against independent small floorplans and rotated origins."""
import importlib.util
import math
from pathlib import Path
import sys

sys.path = [p for p in sys.path if Path(p).resolve() != Path(__file__).resolve().parent]
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('map_benchmark', ROOT/'flex/scripts/benchmark-map.py')
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def scores():
    occupied = np.zeros((4, 4), bool)
    occupied[:, 2] = True
    free = ~occupied
    result = benchmark.score(free, occupied, free, occupied, .5)
    for name in ('freeFloorCoverage', 'freeSpacePrecision', 'freeSpaceIoU',
                 'obstaclePrecision', 'obstacleRecall', 'obstacleIoU', 'knownLabelAgreement'):
        assert result[name] == 1, name
    assert result['referenceFreeFloorM2'] == 3 and result['falselyFreeM2'] == 0
    unknown = np.zeros_like(free)
    result = benchmark.score(unknown, unknown, free, occupied, .5)
    assert result['freeFloorCoverage'] == result['obstacleRecall'] == 0
    assert result['freeSpacePrecision'] is None and result['knownLabelAgreement'] is None
    result = benchmark.score(np.ones_like(free), unknown, free, occupied, .5)
    assert result['freeFloorCoverage'] == 1 and result['freeSpacePrecision'] == .75
    assert result['falselyFreeM2'] == 1, 'all-free output must be penalized'
    shifted = np.roll(occupied, 1, axis=1)
    result = benchmark.score(~shifted, shifted, free, occupied, .5)
    assert result['freeSpacePrecision'] < 1 and result['obstacleIoU'] == 0
    assert result['falselyFreeM2'] == result['falselyOccupiedM2'] == 1
    result = benchmark.score(np.ones_like(free), unknown, free, occupied, .5, occupied)
    assert result['freeSpacePrecision'] == 1 and result['referenceFreeFloorM2'] == 3


def outside_and_partial():
    free = np.zeros((3, 3), bool)
    free[1, :] = True
    occupied = np.zeros_like(free)
    predicted = np.zeros_like(free)
    predicted[1, 0] = True
    result = benchmark.score(predicted, occupied, free, occupied, 1)
    assert result['freeFloorCoverage'] == 1/3 and result['freeSpacePrecision'] == 1
    predicted[0, 0] = True
    result = benchmark.score(predicted, occupied, free, occupied, 1)
    assert result['freeFloorCoverage'] == 1/3 and result['freeSpacePrecision'] == .5
    assert result['falselyFreeM2'] == 1, 'free labels outside the real floor must count'


def geometry():
    origin = [10, 20, math.pi/2]
    x, y = benchmark.world_points(2, 1, [0, 0], origin)
    assert np.allclose(x, [[9.5, 9.5], [8.5, 8.5]])
    assert np.allclose(y, [[20.5, 21.5], [20.5, 21.5]])
    box = dict(centre=[9.5, 20.5, .2], half=[.4, .4, .2], yaw=math.pi/4)
    free, occupied, inside = benchmark.ground_truth(x, y, [9, 20, 10, 22], [box])
    assert np.array_equal(free, [[False, True], [False, False]])
    assert np.array_equal(occupied, [[True, False], [False, False]])
    assert int(inside.sum()) == 2
    for centre, half in (([9.5, 20.5, 1], [.4, .4, .2]), ([9.5, 20.5, 0], [.4, .4, .01])):
        _, mask, _ = benchmark.ground_truth(x, y, [9, 20, 10, 22], [dict(centre=centre, half=half, yaw=0)])
        assert not mask.any(), 'lintels and floor slabs must not block the mapping height band'
    poses = [(1, [10, 20, math.pi/2], [0, 0, 0]),
             (50, [9.5, 20.5, math.pi/2+.1], [.5, .5, .1])]
    errors = benchmark.pose_metrics(poses, origin)
    assert errors['positionRMSEM'] < 1e-12 and errors['headingRMSEDeg'] < 1e-12
    poses[-1] = (50, poses[-1][1], [.6, .5, .1])
    assert abs(benchmark.pose_metrics(poses, origin)['endpointPositionErrorM']-.1) < 1e-12


def main():
    scores()
    outside_and_partial()
    geometry()
    print('Map benchmark passed: exact/unknown/all-free/shifted/partial maps, out-of-floor penalties, explicit exclusions, height band and fixed rotated origin')


if __name__ == '__main__':
    main()
