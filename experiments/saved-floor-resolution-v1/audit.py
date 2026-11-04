#!/usr/bin/env python3
"""Compare saved coarse/fine floor snapshots at their recorded robot poses."""
import hashlib
import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / 'build/flex/sim/levels-v2/pitch82/dock-clearance-build-v1'
MAP = ROOT / 'build/flex/sim/held-map-replay-v4/map/episode-0'
COMPILER = ROOT / 'build/flex/control/compiler'
NAV = ROOT / 'flex/sim/navigation.flex'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def function(text, name):
    start = text.index('fn ' + name + '(')
    return text[start:text.index('\nfn ', start + 1)]


def footprint_cells(x, y, angle):
    c, s = math.cos(angle), math.sin(angle)
    ac, a_s = abs(c), abs(s)
    hx, hy = .15 * ac + .12 * a_s + 1e-9, .15 * a_s + .12 * ac + 1e-9
    margin = .01 * (ac + a_s) + 1e-9
    for row in range(math.floor((y - hy + 10) * 50), math.floor((y + hy + 10) * 50) + 1):
        for column in range(math.floor((x - hx + 10) * 50), math.floor((x + hx + 10) * 50) + 1):
            if not (0 <= row < 1000 and 0 <= column < 1000):
                raise ValueError('footprint outside the map')
            dx, dy = (column + .5) / 50 - 10 - x, (row + .5) / 50 - 10 - y
            if abs(c * dx + s * dy) <= .15 + margin and abs(c * dy - s * dx) <= .12 + margin:
                yield row, column


def load_snapshots():
    paths = sorted(MAP.glob('observed-detail-*.bin'), key=lambda p: int(p.stem.rsplit('-', 1)[-1]))
    if not paths:
        raise ValueError('no saved detail snapshots')
    result = []
    for detail_path in paths:
        frame = int(detail_path.stem.rsplit('-', 1)[-1])
        input_path, coarse_path = MAP / f'input-{frame}.json', MAP / f'observed-{frame}.bin'
        document = json.loads(input_path.read_text())
        pose = document.get('pose')
        if document.get('frameId') != frame or not isinstance(pose, list) or len(pose) != 3 or not all(math.isfinite(v) for v in pose):
            raise ValueError(f'invalid recorded pose at frame {frame}')
        # Use the same rounded pose in the Python geometry and compiled probe.
        pose = [round(v * 1000000000) / 1000000000 for v in pose]
        coarse, detail = coarse_path.read_bytes(), detail_path.read_bytes()
        if len(coarse) != 40000 or len(detail) != 1000000 or max(coarse) > 1 or max(detail) > 1:
            raise ValueError(f'invalid floor map at frame {frame}')
        cells = list(footprint_cells(*pose))
        fine_blocked = sum(detail[row * 1000 + col] for row, col in cells)
        coarse_blocked_fine = sum(coarse[(row // 5) * 200 + col // 5] for row, col in cells)
        result.append(dict(frame=frame, pose=pose, fineCells=len(cells), fineMarked=fine_blocked,
                           fineCellsInBlockedCoarse=coarse_blocked_fine,
                           inputs={str(p.relative_to(ROOT)): sha(p) for p in (input_path, coarse_path, detail_path)}))
    return result


def native_guard(snapshots):
    current = function(NAV.read_text(), 'ps_nav_observed_clear')
    with tempfile.TemporaryDirectory(prefix='puppy-saved-floor-') as name:
        temp = Path(name); source = temp / 'source'; build = temp / 'build'
        shutil.copytree(ARCHIVE / 'source', source); shutil.copytree(ARCHIVE / 'build', build)
        library = build / 'flex/sim/library'; adapter = library / 'lib/f64.flex'
        old = f'import "{ARCHIVE / "source/core/words.flex"}";'
        text = adapter.read_text()
        if text.count(old) != 1:
            raise ValueError('unexpected source reference in archived adapter')
        adapter.write_text(text.replace(old, f'import "{source / "core/words.flex"}";', 1))
        (library.parent / 'dependencies.flex').write_text(
            f'import "{library / "libs/render.flex"}";\nimport "{library / "libs/physics/physics.flex"}";\n')
        nav = source / 'sim/navigation.flex'; text = nav.read_text()
        original = function(text, 'ps_nav_observed_clear')
        nav.write_text(text.replace(original, current, 1))
        lines = ['fn main(argc, argv) {', 'if !pl_init() { return 1; }',
                 'ps_discovery_enabled = 1; ps_nav_columns = 200; ps_nav_rows = 200;',
                 'ps_discovery_observed = alloc(40000); ps_discovery_detail = alloc(1000000);',
                 'ps_discovery_detail_ready = 1;', 'let out = alloc(1024); let b = alloc(32); pl_builder(b, out, 1024);']
        for record in snapshots:
            frame = record['frame']
            coarse = json.dumps(str(MAP / f'observed-{frame}.bin'))
            detail = json.dumps(str(MAP / f'observed-detail-{frame}.bin'))
            lines.append(f'if pl_read_file({coarse}, ps_discovery_observed, 40000) != 40000 || pl_read_file({detail}, ps_discovery_detail, 1000000) != 1000000 {{ return 2; }}')
            args = ', '.join(f'ps_number({round(v * 1000000000)}, 1000000000)' for v in record['pose'])
            lines.append(f'pl_char(b, 48 + ps_nav_observed_clear({args}));')
        lines.extend(['pl_print(1, out); return 0;', '}'])
        main = source / 'sim/main.flex'; text = main.read_text()
        if text.count('fn main(argc, argv) {') != 1:
            raise ValueError('unexpected simulator entrypoint')
        main.write_text(text.replace('fn main(argc, argv) {', 'fn saved_floor_original_main(argc, argv) {', 1)
                        + '\n' + '\n'.join(lines) + '\n')
        binary = temp / 'probe'
        subprocess.run([str(COMPILER), str(main), '-o', str(binary)], cwd=ROOT, capture_output=True, text=True, timeout=120, check=True)
        value = subprocess.run([str(binary)], cwd=ROOT, capture_output=True, text=True, timeout=60, check=True).stdout
        if len(value) != len(snapshots) or set(value) - {'0', '1'}:
            raise ValueError('invalid native guard result')
        return [int(v) for v in value]


def last_fine_evidence(record):
    evidence = MAP / 'evidence.npz'; before = sha(evidence)
    detail_path = MAP / f'observed-detail-{record["frame"]}.bin'
    with np.load(evidence, allow_pickle=False) as data:
        floor, height, detail = data['floorDetail'], data['heightConfirmed'], data['detail']
        if any(a.shape != (1000, 1000) for a in (floor, height, detail)):
            raise ValueError('unexpected retained fine evidence dimensions')
        blocked = (height != 0) & (detail >= 2)
        unknown = floor < 3
        if (unknown | blocked).astype(np.uint8).tobytes() != detail_path.read_bytes():
            raise ValueError('final detail snapshot differs from retained evidence')
        cells = list(footprint_cells(*record['pose']))
        unknown_count = sum(bool(unknown[y, x]) for y, x in cells)
        blocked_count = sum(bool(blocked[y, x]) for y, x in cells)
    if sha(evidence) != before:
        raise ValueError('retained evidence changed during audit')
    return {'evidenceSHA256': before, 'unknownFineCells': unknown_count,
            'confirmedOccupiedFineCells': blocked_count}


def main():
    code_paths = (Path(__file__).resolve(), NAV, COMPILER, ARCHIVE / 'source/sim/navigation.flex',
                  ARCHIVE / 'source/sim/main.flex', ARCHIVE / 'build/flex/sim/library/lib/f64.flex')
    hashes = {str(p.relative_to(ROOT)): sha(p) for p in code_paths}
    snapshots = load_snapshots()
    native = native_guard(snapshots)
    final_evidence = last_fine_evidence(snapshots[-1])
    if hashes != {str(p.relative_to(ROOT)): sha(p) for p in code_paths}:
        raise ValueError('auditor, compiler or source changed during audit')
    for record, clear in zip(snapshots, native):
        if record['inputs'] != {name: sha(ROOT / name) for name in record['inputs']}:
            raise ValueError('saved snapshot changed during audit')
        record['nativeGuardClear'] = bool(clear)
    print(json.dumps({'schema': 'puppybot.saved-floor-resolution.v1', 'snapshots': len(snapshots),
                      'nativeClear': sum(native), 'nativeClearWithMarkedFine': sum(
                          r['nativeGuardClear'] and r['fineMarked'] > 0 for r in snapshots),
                      'lastSnapshotEvidence': final_evidence, 'codeInputs': hashes, 'records': snapshots}, indent=2))


if __name__ == '__main__':
    main()
