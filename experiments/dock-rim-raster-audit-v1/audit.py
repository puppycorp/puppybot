#!/usr/bin/env python3
"""Report rim-colour components in saved, unmodified 640x480 RGB frames.

This reproduces the detector's colour mask and four-connected components;
it does not perform its ray, size, template, temporal or release checks.
"""
import argparse
import hashlib
import json
from pathlib import Path


WIDTH, HEIGHT = 640, 480


def audit(path):
    raw = path.read_bytes()
    if len(raw) != WIDTH * HEIGHT * 3:
        raise ValueError(f'{path}: expected 640x480 RGB bytes')
    mask = bytearray(WIDTH * HEIGHT)
    for i in range(WIDTH * HEIGHT):
        r, g, b = raw[i * 3:i * 3 + 3]
        mask[i] = r > 70 and b > 60 and r > g * 4 and b > g * 4 and b * 10 > r * 7
    components = []
    for i in range(len(mask)):
        if not mask[i]:
            continue
        queue = [i]; mask[i] = 0; head = 0; xs = []; ys = []
        while head < len(queue):
            n = queue[head]; head += 1; x, y = n % WIDTH, n // WIDTH
            xs.append(x); ys.append(y)
            for q in ((n - 1 if x else -1), (n + 1 if x < WIDTH - 1 else -1),
                      (n - WIDTH if y else -1), (n + WIDTH if y < HEIGHT - 1 else -1)):
                if q >= 0 and mask[q]:
                    mask[q] = 0; queue.append(q)
        size = len(queue)
        bbox = [min(xs), min(ys), max(xs), max(ys)]
        components.append({'pixels': size, 'bboxInclusive': bbox,
                           'centroidPixel': [sum(xs) / size + .5, sum(ys) / size + .5],
                           'edgeClipped': bbox[0] == 0 or bbox[1] == 0 or bbox[2] == WIDTH - 1 or bbox[3] == HEIGHT - 1})
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(),
            'components': components}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('rgb', nargs='+', type=Path)
    args = parser.parse_args()
    print(json.dumps([audit(path) for path in args.rgb], indent=2))


if __name__ == '__main__':
    main()
