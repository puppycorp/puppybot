#!/usr/bin/env python3
"""Prepare a frozen multi-scene simulator visual-stop validation matrix.

Usage: prepare-sim-visual-validation.py PILOT_DIRECTORY NEW_INPUT_DIRECTORY
No simulator, policy, GPU or source build is run. This mutates only copies of
an existing PBENV001 scene. Synthetic colored stripes are visual geometry,
not colliders; actual visual texture and robot motion must be measured later.
"""
import hashlib
import json
import math
import struct
import sys
from pathlib import Path

# Predeclared independently of validation outcomes. The original motivating
# case used yaw 0, so no validation condition repeats it exactly.
HEADINGS = (-0.65, -0.25, 0.35)
FAMILIES = ('natural', 'uniform', 'periodic')
ROOT = Path(__file__).resolve().parents[2]
ROOM_LAYOUTS = (13, 15, 17)
ROOMS = ROOT / 'build/flex/sim/expanded-rooms-v1/scenes'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def split_environment(raw):
    if len(raw) < 256 or raw[:8] != b'PBENV001': raise ValueError('invalid environment magic')
    count, vertices, overview = struct.unpack_from('<3q', raw, 8)
    if not 1 <= count <= 160 or not 3 <= vertices <= 1000000 or vertices % 3 or overview != vertices or len(raw) != 256 + count*128 + vertices*72:
        raise ValueError('invalid environment dimensions')
    coords = struct.unpack_from('<7d', raw, 64)
    if not all(math.isfinite(x) and abs(x) <= 100 for x in coords) or not coords[0] < coords[4] < coords[2] or not coords[1] < coords[5] < coords[3]:
        raise ValueError('invalid environment bounds/spawn')
    start = 256 + count*128; split = start + vertices*36
    return bytearray(raw[:start]), bytearray(raw[start:split]), bytearray(raw[split:])


def with_heading(header, heading):
    if not math.isfinite(heading): raise ValueError('invalid heading')
    struct.pack_into('<d', header, 112, heading)


def uniform_colors(mesh):
    for offset in range(0, len(mesh), 36):
        struct.pack_into('<3f', mesh, offset+24, 0.50, 0.50, 0.50)


def stripe_vertices():
    # An artificial noncolliding view panel, in world coordinates x=1.8.
    # Perspective, shading and robot appearance can destroy exact periodicity.
    result = bytearray(); width = .18
    for stripe in range(20):
        y0 = -1.8 + stripe*width; y1 = y0 + width
        shade = .16 if stripe % 2 == 0 else .78
        vertices = [(1.8,y0,0), (1.8,y1,1.8), (1.8,y1,0),
                    (1.8,y0,0), (1.8,y0,1.8), (1.8,y1,1.8)]
        for vertex in vertices:
            result.extend(struct.pack('<9f', *vertex, -1,0,0, shade,shade,shade))
    return result


def variant(raw, heading, family):
    if family not in FAMILIES: raise ValueError('unknown appearance family')
    header, full, overview = split_environment(raw); with_heading(header, heading)
    if family == 'uniform':
        uniform_colors(full); uniform_colors(overview)
    if family == 'periodic':
        stripe = stripe_vertices(); full.extend(stripe); overview.extend(stripe)
        vertices = len(full)//36
        if vertices > 1000000: raise ValueError('periodic mesh exceeds simulator limit')
        struct.pack_into('<2q', header, 16, vertices, vertices)
    output = bytes(header + full + overview)
    split_environment(output)
    return output


def prepare(pilot, output):
    pilot = Path(pilot).absolute(); output = Path(output).absolute()
    original = pilot/'inputs/environment.bin'; case = pilot/'inputs/case.json'
    receipt = json.loads((pilot/'inputs.json').read_text()); files = receipt.get('files', {})
    if receipt.get('schema') != 'puppybot.sim-visual-stop-pair.v1' or receipt.get('paths', {}).get('environment') != str(original) or receipt.get('paths', {}).get('case') != str(case):
        raise ValueError('pilot manifest does not name the expected inputs')
    raw = original.read_bytes(); case_bytes = case.read_bytes(); split_environment(raw)
    if files.get(str(original)) != digest(raw) or files.get(str(case)) != digest(case_bytes):
        raise ValueError('original pilot scene changed')
    original_case = json.loads(case_bytes)
    if len(original_case.get('objects', [])) != 1: raise ValueError('expected single-target pilot case')
    output.mkdir(parents=False, exist_ok=False)
    conditions = []
    for family in FAMILIES:
        for heading in HEADINGS:
            name = f'{family}-yaw-{heading:+.2f}'
            directory = output/name; directory.mkdir()
            env = variant(raw, heading, family)
            (directory/'environment.bin').write_bytes(env); (directory/'case.json').write_bytes(case_bytes)
            conditions.append({'name':name,'family':family,'spawnHeading':heading,
                               'environmentSHA256':digest(env),'caseSHA256':digest(case_bytes),
                               'intendedVisualStress': family,
                               'classification': 'unverified until independent rendered post-run audit'})
    room_sources = []
    for layout in ROOM_LAYOUTS:
        source = ROOMS / str(layout) / '1'
        env_raw = (source/'environment.bin').read_bytes(); case_raw = (source/'case.json').read_bytes()
        split_environment(env_raw)
        if len(json.loads(case_raw).get('objects', [])) != 1: raise ValueError('room case is not single-target')
        directory = output / f'room-{layout}'; directory.mkdir()
        (directory/'environment.bin').write_bytes(env_raw); (directory/'case.json').write_bytes(case_raw)
        room_sources.append({'layout':layout,'environmentPath':str((source/'environment.bin').absolute()),
                             'environmentSHA256':digest(env_raw),'casePath':str((source/'case.json').absolute()),'caseSHA256':digest(case_raw)})
        conditions.append({'name':f'room-{layout}','family':'natural-room','layout':layout,
                           'environmentSHA256':digest(env_raw),'caseSHA256':digest(case_raw),
                           'intendedVisualStress':'natural-room',
                           'classification':'unverified until independent rendered post-run audit'})
    report = {'schema':'puppybot.visual-stop-validation-inputs.v1','sourceEnvironmentSHA256':digest(raw),
              'sourceCaseSHA256':digest(case_bytes),'generatorSHA256':digest(Path(__file__).read_bytes()),'roomSources':room_sources,
              'conditions':conditions,
              'scope':'nine predeclared variants of one training apartment and three existing training rooms; noncolliding periodic visual panel; actual image coverage and motion require measurement; no held-out or hardware claim'}
    (output/'conditions.json').write_text(json.dumps(report, sort_keys=True, indent=2)+'\n')
    return report


if __name__ == '__main__':
    if len(sys.argv) != 3: raise SystemExit(__doc__)
    report = prepare(*sys.argv[1:]); print(json.dumps({'status':'inputs_prepared','conditions':len(report['conditions']),'scope':report['scope']}))
