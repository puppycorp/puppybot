#!/usr/bin/env python3
"""Read-only point-level replay of four retained docking stereo pairs.

The original trial worker is instrumented in memory, not edited. A projected
point is an estimated ground location, not a depth or visibility oracle.
"""
import hashlib
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / 'build/flex/sim/levels-v2/pitch82/dock-short-waypoint-monitored-v1'
TRIAL = RUN / 'trial'
TRACE = TRIAL / 'candidate-search/run/trace.jsonl'
MAP = ROOT / 'build/flex/sim/discovery-2701217/episode-1/dock-1'
WORKER = ROOT / 'flex/vision/discovery.py'
FRAMES = (23385, 23791, 25461, 25865)


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def snapshot(paths):
    return {str(path): sha(path) for path in sorted(set(paths))}


def original_projection(frame, point):
    calibration = np.asarray(frame['calibration'], dtype=np.float64).reshape(4, 3)
    rotation = np.column_stack((calibration[2], calibration[3], calibration[1]))
    vector = (point - calibration[0]) @ rotation
    if vector[2] <= 0:
        return {'inFrame': False, 'pixel': None}
    x, y = (vector[:2] / vector[2]) * 415.6921938 + [320, 240]
    return {'inFrame': bool(0 <= x < 640 and 0 <= y < 480), 'pixel': [float(x), float(y)]}


def main():
    completion_path = RUN / 'completion.json'; inputs_path = TRIAL / 'inputs.json'
    worker_result = RUN / 'worker-result.json'; worker_inputs = TRIAL / 'worker-inputs.json'
    completion = json.loads(completion_path.read_text()); inputs = json.loads(inputs_path.read_text())
    result = json.loads(worker_result.read_text()); pin = json.loads(worker_inputs.read_text())
    assert sha(inputs_path) == completion['inputsSHA256'] == result['inputsSHA256']
    assert sha(worker_result) == completion['finalWorkerSHA256']
    assert sha(worker_inputs) == inputs['files'][str(worker_inputs)]
    assert sha(WORKER) == pin['files'][str(WORKER)]
    assert sha(TRACE) == result['inventory']['candidate-search/run/trace.jsonl']
    assert cv2.__version__ == pin['cv2'] and np.__version__ == pin['numpy']
    assert Path(sys.executable).resolve() == Path(pin['executable']).resolve()
    box = None
    with TRACE.open() as stream:
        for line in stream:
            row = json.loads(line)
            if row['step'] == 22865:
                box = row['case']['dockVision']['positionM']; break
    assert box is not None and len(box) == 3
    point = np.array([box[0], box[1] + .4, 0.], dtype=np.float64)
    requests = []
    paths = [completion_path, inputs_path, worker_result, worker_inputs, WORKER, TRACE,
             MAP / 'evidence.npz', MAP / 'observed-detail-31037.bin']
    for frame in FRAMES:
        path = MAP / f'input-{frame}.json'; request = json.loads(path.read_text())
        assert request['frameId'] == frame and len(request['frames']) == 2
        paths.append(path)
        for f in request['frames']:
            rgb = ROOT / f['rgb']; assert rgb.parent == MAP and rgb.stat().st_size == 640 * 480 * 3
            paths.append(rgb)
        requests.append(request)
    hashes = snapshot(paths)
    cv2.setNumThreads(1)
    # The worker's camera geometry, masks, stereo and gates remain unchanged.
    # Record the nearest rectified pixel before its real return statement.
    source = WORKER.read_text()
    needle = '    return np.vstack((ground[floor], points[obstacles])), dict(baselineM=baseline,'
    insertion = '''    qpt = (audit_point-eyes[0]) @ rotations[0] @ first.T
    if qpt[2] <= 0: raise ValueError("point behind rectified camera")
    px = int(round(p1[0,0]*qpt[0]/qpt[2]+p1[0,2])); py = int(round(p1[1,1]*qpt[1]/qpt[2]+p1[1,2]))
    if not (0 <= px < 320 and 0 <= py < 240): raise ValueError("point outside rectified camera")
    z = float(points[py,px,2])
    audit_records.append(dict(rectifiedPixel=[px,py], floor=bool(floor[py,px]),
        stereoValid=bool(valid[py,px]), groundMatch=bool(ground_match[py,px]),
        textured=bool(textured[py,px]), triangulatedZ=z if np.isfinite(z) else None,
        disparity=float(left[py,px]), insideHomography=bool(inside[py,px]),
        photoError=float(photo_error[py,px]), selfMasked=bool(self_masks[0][py,px]),
        otherSelfMasked=bool(other_self[py,px]), firstValid=bool(valid_masks[0][py,px]),
        otherValid=bool(other_valid[py,px])))
'''
    assert source.count(needle) == 1
    records = []; scope = {'__name__': 'instrumented_discovery', 'audit_point': point, 'audit_records': records}
    exec(compile(source.replace(needle, insertion + needle, 1), str(WORKER), 'exec'), scope)
    rows = []
    for request in requests:
        projections = [original_projection(f, point) for f in request['frames']]
        assert all(item['inFrame'] for item in projections)
        before = len(records); points, metrics = scope['cloud'](request['frames'])
        assert len(records) == before + 1
        frame = request['frames'][0]; calibration = np.asarray(frame['calibration']).reshape(4, 3)
        forward = calibration[1]
        rows.append({'frameId': request['frameId'], 'rgb': [f['rgb'] for f in request['frames']],
                     'originalImageProjections': projections,
                     'cameraYawDeg': math.degrees(math.atan2(forward[1], forward[0])),
                     'cameraDownAngleDeg': -math.degrees(math.asin(float(forward[2]))),
                     'workerMetrics': metrics, 'returnedPoints': len(points), **records[-1]})
    ix, iy = np.floor((point[:2] + 10) / .02).astype(int)
    with np.load(MAP / 'evidence.npz') as evidence:
        detail_count = int(evidence['floorDetail'][iy, ix]); coarse_count = int(evidence['free'][iy // 5, ix // 5])
    observed = np.fromfile(MAP / 'observed-detail-31037.bin', np.uint8).reshape(1000, 1000)
    assert detail_count < 3 and observed[iy, ix] == 1
    assert snapshot(paths) == hashes
    print(json.dumps({'schema': 'puppybot.dock-camera-point-audit.v1', 'pointM': point.tolist(),
                      'detailFloorVotes': detail_count, 'coarseFloorVotes': coarse_count,
                      'rows': rows, 'inputSHA256': hashes,
                      'limits': ['Retained map inputs and RGB are outside the original supervised inventory.',
                                 'Point-level rectified-pixel checks do not classify every staging candidate.',
                                 'Projection inside the image does not prove unoccluded or safe physical floor.',
                                 'Matching worker file and runtime versions do not attest original runtime execution.']},
                     indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
