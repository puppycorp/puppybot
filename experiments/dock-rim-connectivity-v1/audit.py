#!/usr/bin/env python3
"""Offline native box-fit plus associated-corner connected-colour diagnostic."""
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prior = load('blue_support_fixture', ROOT / 'experiments/dock-marker-blue-support-v1/test.py')


def connected_support(path, result):
    """Inspect blue labels near observed markers associated with fitted corners."""
    if not result['found']:
        return {'accept': False, 'bestCorners': 0, 'componentPixels': 0}
    raw = path.read_bytes()
    if len(raw) != 640 * 480 * 3:
        raise ValueError('invalid RGB input length')
    rgb = np.frombuffer(raw, np.uint8).reshape(480, 640, 3).astype(np.int16)
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    blue = ((b > 35) & (b > g + 10) & (g > r + 10)).astype(np.uint8)
    _, labels, stats, _ = cv2.connectedComponentsWithStats(blue, connectivity=4)
    markers = result['markers']; indices = sorted(set(i for i in result['corners'] if i >= 0))
    if any(i >= len(markers) for i in indices):
        raise ValueError('invalid native fitted marker index')
    matched = {}
    for index in indices:
        u, v = markers[index]; x, y = int(u), int(v)
        if not 0 <= x < 640 or not 0 <= y < 480:
            raise ValueError('invalid native marker position')
        patch = labels[max(0, y - 5):min(480, y + 6), max(0, x - 5):min(640, x + 6)]
        for label in np.unique(patch):
            if label:
                matched.setdefault(int(label), set()).add(index)
    groups = [(len(indices), int(stats[label, cv2.CC_STAT_AREA])) for label, indices in matched.items()]
    best = max(groups, default=(0, 0))
    return {'accept': any(count >= 2 and area >= 200 for count, area in groups),
            'bestCorners': best[0], 'componentPixels': best[1]}


def instrumented_probe(cls):
    source = cls.root / 'source'; arc = prior.prior.ARCHIVE
    dock = source / 'sim/dock-vision.flex'; main = source / 'sim/main.flex'
    candidate_dock, candidate_main = prior.transform.transform(
        (arc / 'source/sim/dock-vision.flex').read_text(), (arc / 'source/sim/main.flex').read_text())
    dock.write_text(candidate_dock)
    probe = (prior.prior.HERE / 'probe.flex').read_text()
    old = '    pl_text(b, "]}\\n"); pl_write(1, out, load64(b + 8)); return 0;'
    new = '''    pl_text(b, "],\\\"markers\\\":["); let j = 0;
    while j < ps_dock_count { if j { pl_char(b, 44); } let p = ps_dock_markers + j * 96; pl_char(b, 91); pl_float(b, load64(p + 56)); pl_char(b, 44); pl_float(b, load64(p + 64)); pl_char(b, 93); j = j + 1; }
    pl_text(b, "],\\\"corners\\\":["); j = 0; while j < 4 { if j { pl_char(b, 44); } pl_int(b, load64(ps_dock_corners + j * 8)); j = j + 1; }
    pl_text(b, "]}\\n"); pl_write(1, out, load64(b + 8)); return 0;'''
    if probe.count(old) != 1 or probe.count('while i < 3 { ps_total = 10 * i;') != 1:
        raise ValueError('native probe shape changed')
    probe = probe.replace(old, new, 1).replace('while i < 3 { ps_total = 10 * i;',
                                               'while i < 1 { ps_total = 10 * i;', 1)
    main.write_text(prior.transform.BASE.once(candidate_main, 'fn main(argc, argv) {',
                                              'fn rim_original_main(argc, argv) {') + '\n' + probe)
    result = subprocess.run([str(prior.prior.COMPILER), str(main), '-o', str(cls.probe)], cwd=ROOT,
                            capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)


def synthetic(mode):
    rgb = np.zeros((480, 640, 3), np.uint8)
    positions = ((140, 369), (227, 369), (156, 385), (235, 385), (205, 398), (242, 398))
    if mode in ('patches', 'connected'):
        for x, y in positions:
            rgb[y - 5:y + 1, x - 5:x + 6] = (50, 81, 102)
    if mode == 'connected':
        for a, b in zip(positions, positions[1:]):
            cv2.line(rgb, a, b, (50, 81, 102), 2, lineType=cv2.LINE_8)
    for x, y in positions:
        rgb[y, x:x + 3] = (220, 0, 220)
    return rgb.tobytes()


def main():
    source_paths = [HERE / 'audit.py', Path(prior.__file__), Path(prior.transform.__file__),
                    Path(prior.prior.__file__), prior.prior.HERE / 'probe.flex', prior.prior.COMPILER,
                    prior.prior.HERE / 'input-receipt.json',
                    ROOT / 'experiments/dock-marker-blue-support-v1/barrier-inputs.json']
    sources = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths}
    cls = prior.BlueSupportTests
    cls.setUpClass()
    try:
        instrumented_probe(cls)
        test = cls('test_barrier_survey_views')
        receipt = json.loads((ROOT / 'experiments/dock-marker-blue-support-v1/barrier-inputs.json').read_text())
        rows = []
        for name in sorted(k for k in receipt['files'] if k.endswith('.rgb')):
            image = Path(name); camera = image.with_suffix('.sensor.camera.json')
            for path in (image, camera):
                if hashlib.sha256(path.read_bytes()).hexdigest() != receipt['files'][str(path)]:
                    raise ValueError(f'changed saved file: {path}')
            fit = test.run_probe(image, camera, True)
            rows.append({'path': str(image.resolve().relative_to(ROOT)), 'found': bool(fit['found']),
                         'corners': fit['corners'], 'support': connected_support(image, fit)})
        positives = []
        for run, frame in (('dock-clearance', 49), ('dock-clearance', 59), ('dock-survey-elevation', 49)):
            image, camera = test.frame(run, frame)
            fit = test.run_probe(image, camera, True)
            positives.append({'path': str(image.relative_to(ROOT)), 'sha256': hashlib.sha256(image.read_bytes()).hexdigest(),
                              'found': bool(fit['found']), 'corners': fit['corners'],
                              'support': connected_support(image, fit)})
        _, camera = test.frame('dock-clearance', 59)
        negative = []
        for mode in ('blank', 'patches', 'connected'):
            image = cls.root / (mode + '.rgb'); data = synthetic(mode); image.write_bytes(data)
            fit = test.run_probe(image, camera, True)
            negative.append({'name': mode, 'sha256': hashlib.sha256(data).hexdigest(),
                             'found': bool(fit['found']), 'corners': fit['corners'],
                             'support': connected_support(image, fit)})
        if sources != {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths}:
            raise ValueError('a pinned local source changed during the audit')
        for name, digest in receipt['files'].items():
            if hashlib.sha256(Path(name).read_bytes()).hexdigest() != digest:
                raise ValueError(f'saved input changed during audit: {name}')
        result = {'schema': 'puppybot.rim-connectivity-offline.v1', 'barrier': rows,
                  'knownPositiveViews': positives, 'synthetic': negative, 'sourceHashes': sources,
                  'opencvVersion': cv2.__version__, 'numpyVersion': np.__version__}
        print(json.dumps(result, indent=2))
    finally:
        cls.tearDownClass()


if __name__ == '__main__':
    main()
