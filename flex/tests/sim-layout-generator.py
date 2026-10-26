#!/usr/bin/env python3
"""Check reproducibility, physical doorway connectivity and task placement."""
import importlib.util
import json
import math
from pathlib import Path
import struct
import sys

sys.path = [p for p in sys.path if Path(p).resolve() != Path(__file__).resolve().parent]
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('layout_generator', ROOT/'flex/scripts/generate-layout.py')
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


def check(seed, count):
    layout = generator.generate(seed, count)
    again = generator.generate(seed, count)
    assert json.dumps(layout, sort_keys=True) == json.dumps(again, sort_keys=True)
    assert generator.environment_bytes(layout) == generator.environment_bytes(again)
    assert len(layout['rooms']) == count
    assert len(layout['case']['objects']) == 6
    assert layout['case']['controller'] == 'rgb-discovery' and 'navigation' not in layout['case']
    free = generator.free_grid(layout['bounds'], layout['objects'])
    reached = generator.flood(free, layout['bounds'], layout['spawn'])
    def connected(point):
        row = int((point[1]-layout['bounds'][1])/.1)
        col = int((point[0]-layout['bounds'][0])/.1)
        return bool(reached[row, col])
    assert all(connected([(room[0]+room[2])/2, (room[1]+room[3])/2]) for room in layout['rooms'])
    points = [obj['position'][:2] for obj in layout['case']['objects']]
    assert all(connected(point) for point in points)
    assert all(math.dist(a, b) > .5 for i, a in enumerate(points) for b in points[i+1:])
    assert connected(layout['spawn']) and connected(layout['case']['container']['position'])
    for edge in layout['edges']:
        if edge['door']:
            assert .8 <= edge['door']['width'] <= 1.3
            point = [edge['fixed'], edge['door']['centre']]
            if edge['axis']:
                point.reverse()
            assert connected(point), 'logical graph contains a physically blocked doorway'
    raw = generator.environment_bytes(layout)
    magic, boxes, vertices, overview = struct.unpack_from('<8s3Q', raw)
    assert magic == b'PBENV001' and 1 <= boxes <= 160
    assert 3 <= vertices == overview <= 1000000 and vertices % 3 == 0
    assert len(raw) == 256+boxes*128+vertices*72
    payload = np.frombuffer(raw, '<f4', offset=256+boxes*128)
    assert np.isfinite(payload).all()
    assert layout['case']['gripper'] == generator.generate(seed+1, count)['case']['gripper']
    return bytes(raw)


def main():
    payloads = []
    for count in range(2, 7):
        for seed in (0, 101, 202, 303):
            payloads.append(check(seed, count))
    assert len(set(payloads)) == len(payloads), 'different seeds/counts did not change scenes'
    print('Layout generator passed: 20 seeded worlds, 2-6 rooms, deterministic binary/JSON, connected real doorways, safe spawn/box and six reachable separated bricks')


if __name__ == '__main__':
    main()
