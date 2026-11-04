#!/usr/bin/env python3
"""Prepare training-layout selection scenes with independently varied start yaw.

Usage: prepare-route-factorial.py NEW_OUTPUT
Produces a 3-layout x 3-heading x 3-seed diagnostic matrix. Only the PBENV001
spawn pose is changed; collider and rendered geometry remain byte-identical to
their source environment. This creates scene inputs, not evaluation results.
"""
import hashlib
import json
import math
import struct
import sys
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[4]
SCENES = PROJECT / 'build/flex/sim/expanded-rooms-v1/scenes'
LAYOUTS = (13, 15, 17)
HEADINGS = (.35, .42, .49)
SEEDS = (7800001, 7800004, 7800007)
XY = (-.04, -.04)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def environment(source, heading):
    data = bytearray(source)
    if len(data) < 256 or data[:8] != b'PBENV001' or not math.isfinite(heading):
        raise ValueError('invalid PBENV001 source or heading')
    count, vertices, other = struct.unpack_from('<qqq', data, 8)
    if count < 1 or count > 160 or vertices < 3 or vertices % 3 or vertices != other or len(data) != 256 + count * 128 + vertices * 72:
        raise ValueError('invalid PBENV001 dimensions')
    xmin, ymin, xmax, ymax = struct.unpack_from('<4d', data, 64)
    if not all(math.isfinite(v) for v in (xmin, ymin, xmax, ymax)) or not xmin < XY[0] < xmax or not ymin < XY[1] < ymax:
        raise ValueError('common start is outside environment bounds')
    partition = [struct.unpack_from('<d', data, 256 + i * 128 + 48)[0] for i in range(count)
                 if data[256 + i * 128:256 + i * 128 + 48].startswith(b'Wall.partition')]
    if len(partition) != 2 or not all(math.isfinite(v) and v > XY[0] for v in partition) or partition[0] != partition[1]:
        raise ValueError('expected one partition to the east of the common start')
    struct.pack_into('<3d', data, 96, *XY, heading)
    return bytes(data)


def verify(source, output, manifest):
    entries = manifest['conditions']
    expected = {(layout, heading, seed) for layout in LAYOUTS for heading in HEADINGS for seed in SEEDS}
    seen = set()
    for row in entries:
        layout, seed = row['layout'], row['seed']
        heading = row['startPose'][2]
        key = (layout, heading, seed)
        if key not in expected or key in seen or row['startPose'] != [*XY, heading]:
            raise ValueError('duplicate or invalid factorial condition')
        seen.add(key)
        variant = (seed - 7800000) % 16
        name = f'L{layout}-yaw{round(heading*100):02d}-seed{seed}'
        if row['name'] != name or row['variant'] != variant or row['catalog'] != f'{name}/catalog':
            raise ValueError('factorial path mapping differs')
        original = source / str(layout) / str(variant); scene = output / name / 'catalog' / '0'
        if {p.name for p in scene.parent.iterdir()} != {'0'} or {p.name for p in scene.iterdir()} != {'environment.bin', 'case.json', 'layout.json'}:
            raise ValueError('unexpected catalog or scene entries')
        old = (original / 'environment.bin').read_bytes(); new = (scene / 'environment.bin').read_bytes()
        if row['sourceEnvironmentSHA256'] != sha(old) or row['environmentSHA256'] != sha(new) or new != environment(old, heading):
            raise ValueError('source or derived environment changed')
        for file, keyname in (('case.json', 'caseSHA256'), ('layout.json', 'layoutSHA256')):
            original_bytes = (original / file).read_bytes(); copied = (scene / file).read_bytes()
            if sha(original_bytes) != row[keyname] or copied != original_bytes:
                raise ValueError(f'source or copied {file} changed')
    if seen != expected:
        raise ValueError('incomplete factorial')


def prepare(source, output):
    if output.exists() or output.is_symlink():
        raise ValueError('output exists; retain and inspect')
    output.mkdir(parents=False)
    conditions = []
    for layout in LAYOUTS:
        for heading in HEADINGS:
            for seed in SEEDS:
                variant = (seed - 7800000) % 16
                original = source / str(layout) / str(variant)
                source_env = (original / 'environment.bin').read_bytes()
                case = (original / 'case.json').read_bytes()
                metadata = (original / 'layout.json').read_bytes()
                info = json.loads(metadata)
                if info.get('layoutId') != layout or info.get('fit') is not True or info.get('startRoom') != 0:
                    raise ValueError(f'not an intended training layout: {original}')
                name = f'L{layout}-yaw{round(heading*100):02d}-seed{seed}'
                scene = output / name / 'catalog' / '0'; scene.mkdir(parents=True)
                modified = environment(source_env, heading)
                (scene / 'environment.bin').write_bytes(modified)
                (scene / 'case.json').write_bytes(case)
                (scene / 'layout.json').write_bytes(metadata)
                conditions.append({'name': name, 'layout': layout, 'seed': seed, 'variant': variant,
                                   'startPose': [*XY, heading], 'catalog': f'{name}/catalog',
                                   'sourceEnvironmentSHA256': sha(source_env), 'environmentSHA256': sha(modified),
                                   'caseSHA256': sha(case), 'layoutSHA256': sha(metadata)})
    manifest = {'status': 'diagnostic_inputs_only', 'conditions': conditions,
                'scope': 'training layouts only; across-layout geometry, wall location, doorway dimensions and appearance all vary; no held-out scenes'}
    (output / 'conditions.json').write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n')
    verify(source, output, manifest)
    return manifest


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    out = Path(sys.argv[1]).absolute()
    print(json.dumps(prepare(SCENES, out), sort_keys=True))


if __name__ == '__main__':
    main()
