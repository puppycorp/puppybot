#!/usr/bin/env python3
"""Read-only analysis of the saved short-waypoint staging attempts."""
import hashlib
import json
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
TRACE = ROOT / 'build/flex/sim/levels-v2/pitch82/dock-short-waypoint-monitored-v1/trial/candidate-search/run/trace.jsonl'
MAP = ROOT / 'build/flex/sim/discovery-2701217/episode-1/dock-1'


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for data in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(data)
    return digest.hexdigest()


def audit():
    files = [TRACE]; rows = []; previous = 0
    with TRACE.open() as source:
        for line in source:
            row = json.loads(line); vision = row['case']['dockVision']
            diag = vision['clearanceDiagnostic']; runs = diag['stageRuns']
            if runs == previous:
                continue
            assert runs == previous + 1 and diag['stageCandidates'] == runs * 2304
            assert diag['stageObservedFloor'] == runs * 2304
            for key in ('stageNear', 'stageClear', 'stageFloorObstacle', 'stageBoxMargin',
                        'stageTargetExclusion', 'stageOther', 'dropClearancePass',
                        'dropClearanceFail', 'routePass', 'routeFail'):
                assert diag[key] == 0, (key, diag[key])
            discovery = row['discovery']; frame = discovery['mapFrameId']
            assert discovery['output'] == str(MAP.relative_to(ROOT))
            paths = [MAP / f'observation-{frame}.json', MAP / f'observed-{frame}.bin',
                     MAP / f'observed-detail-{frame}.bin']
            files.extend(paths); observation = json.loads(paths[0].read_text())
            assert observation['frameId'] == frame
            assert observation['occupiedCells'] == discovery['occupiedCells'] == 0
            assert observation['freeCells'] == discovery['freeCells']
            coarse = np.fromfile(paths[1], dtype=np.uint8)
            detail = np.fromfile(paths[2], dtype=np.uint8)
            assert coarse.size == 200 * 200 and detail.size == 1000 * 1000
            assert np.all(coarse <= 1) and np.all(detail <= 1)
            assert np.count_nonzero(coarse == 0) == observation['freeCells']
            position = vision['positionM']
            # Stage ring radius <= 0.40m and rotated 0.15m by 0.12m
            # rectangular footprint, plus the implementation's epsilon.
            extent = .4 + math.hypot(.15, .12) + 1e-9
            assert max(abs(position[0]), abs(position[1])) + extent < 10
            rows.append({'tick': row['step'], 'frame': frame, 'valid': vision['valid'],
                         'stableObservations': vision['stableObservations'],
                         'freeCells': observation['freeCells'], 'occupiedCells': 0,
                         'boxPositionM': position, 'detailFreeCells': int(np.count_nonzero(detail == 0))})
            previous = runs
    assert len(rows) == 15 and sum(bool(row['valid']) for row in rows) == 1
    evidence = MAP / 'evidence.npz'; files.append(evidence)
    snapshot = {str(p.relative_to(ROOT)): sha(p) for p in files}
    assert rows[-1]['frame'] == 31037
    with np.load(evidence) as data:
        occupied = np.where(data['heightConfirmed'] != 0, data['detail'], 0).reshape(200, 5, 200, 5).max(axis=(1, 3))
        assert np.array_equal(occupied, data['occupied']) and np.count_nonzero(occupied >= 2) == 0
        coarse = np.fromfile(MAP / 'observed-31037.bin', dtype=np.uint8).reshape(200, 200)
        detail = np.fromfile(MAP / 'observed-detail-31037.bin', dtype=np.uint8).reshape(1000, 1000)
        assert np.array_equal(coarse, ~((data['free'] >= 3) & (occupied < 2)))
        assert np.array_equal(detail, (data['floorDetail'] < 3) | ((data['heightConfirmed'] != 0) & (data['detail'] >= 2)))
    assert snapshot == {str(p.relative_to(ROOT)): sha(p) for p in files}
    return {'schema': 'puppybot.dock-stage-cause-audit.v1', 'rows': rows,
            'inputSHA256': snapshot,
            'limits': ['Saved maps lie outside the trial inventory.',
                       'Historical occupied counts are worker metadata, not independently reconstructed raw evidence.',
                       'Unknown is a mapper evidence classification, not proof of empty or occupied physical floor.',
                       'Box margin, drop clearance and route planning were not reached.']}


if __name__ == '__main__':
    print(json.dumps(audit(), indent=2, sort_keys=True))
