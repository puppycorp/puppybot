#!/usr/bin/env python3
"""Quantify saved coarse/fine floor coverage around the observed box."""
import hashlib
import json
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
MAP = ROOT / 'build/flex/sim/discovery-2701217/episode-1/dock-1'
STAGE_REPORT = ROOT / 'experiments/dock-stage-cause-v1/report.json'
REPLAY_REPORT = ROOT / 'experiments/dock-stage-cause-v1/waypoint-report.json'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as source:
        for data in iter(lambda: source.read(1024 * 1024), b''):
            h.update(data)
    return h.hexdigest()


def audit():
    stage = json.loads(STAGE_REPORT.read_text()); replay = json.loads(REPLAY_REPORT.read_text())
    rows = stage['rows']; files = [STAGE_REPORT, REPLAY_REPORT]
    for row in rows:
        frame = row['frame']
        files.extend((MAP / f'observed-{frame}.bin', MAP / f'observed-detail-{frame}.bin'))
    snapshot = {str(path.relative_to(ROOT)): sha(path) for path in files}
    for path in files[2:]:
        assert snapshot[str(path.relative_to(ROOT))] == stage['inputSHA256'][str(path.relative_to(ROOT))]
    box = rows[0]['boxPositionM'][:2]
    assert all(row['boxPositionM'][:2] == box for row in rows)
    # Conservative radial coverage around all candidate body footprints:
    # centres are 0.28--0.40m from the box and corners are < 0.193m away.
    yy, xx = np.indices((1000, 1000)); x = -10 + (xx + .5) * .02; y = -10 + (yy + .5) * .02
    distance = np.hypot(x - box[0], y - box[1]); ring = (distance >= .08) & (distance <= .60)
    quadrants = {'eastNorth': (x >= box[0]) & (y >= box[1]),
                 'westNorth': (x < box[0]) & (y >= box[1]),
                 'westSouth': (x < box[0]) & (y < box[1]),
                 'eastSouth': (x >= box[0]) & (y < box[1])}
    report = []
    for row in rows:
        frame = row['frame']
        coarse = np.fromfile(MAP / f'observed-{frame}.bin', np.uint8).reshape(200, 200)
        detail = np.fromfile(MAP / f'observed-detail-{frame}.bin', np.uint8).reshape(1000, 1000)
        # ps_nav_observed_clear accepts a coarse-clear region without fine
        # detail; a blocked coarse cell requires clear fine detail.
        effective = (np.repeat(np.repeat(coarse, 5, axis=0), 5, axis=1) == 0) | (detail == 0)
        clear = effective & ring
        report.append({'frame': frame, 'tick': row['tick'], 'effectiveClearCells': int(clear.sum()),
                       'ringCells': int(ring.sum()), 'clearByQuadrant': {
                           key: int((clear & value).sum()) for key, value in quadrants.items()}})
    candidate = replay['rows'][-1]
    assert candidate['candidate'] and candidate['result'] == 1 and candidate['pathCount'] == 2
    before = replay['pose'][:2]; end = candidate['goal']
    assert snapshot == {str(path.relative_to(ROOT)): sha(path) for path in files}
    return {'schema': 'puppybot.dock-floor-coverage.v1', 'boxM': box,
            'resolutionM': .02, 'innerRadiusM': .08, 'outerRadiusM': .60,
            'rows': report, 'secondWaypoint': {'startM': before, 'plannedEndpointM': end,
                'pathPrimitives': candidate['pathCount'], 'displacementM': math.dist(before, end),
                'boxDistanceBeforeM': math.dist(box, before), 'boxDistanceAfterM': math.dist(box, end)},
            'inputSHA256': snapshot,
            'limits': ['Radial coverage is an area summary, not a per-candidate collision test.',
                       'Masks describe local map evidence, not verified physical floor.',
                       'Stored maps are outside the original supervised trial inventory.',
                       'The planned endpoint was not driven and does not guarantee a useful camera view.']}


if __name__ == '__main__':
    print(json.dumps(audit(), indent=2, sort_keys=True))
