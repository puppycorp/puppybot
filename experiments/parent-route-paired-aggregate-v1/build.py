#!/usr/bin/env python3
"""Prepare paired teacher/parent-label data; direct launch is disabled."""
import fcntl
import json
import math
import os
import shutil
import struct
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = ROOT / 'build/flex/sim/levels-v2/pitch82'
SOURCE = BASE / 'outbound-five-aggregate-v1'
COLLECTION = BASE / 'parent-route-instrumented-collector-v1'
OUTPUT = BASE / 'parent-route-paired-aggregate-v1'
GIB = 1024 ** 3
FICLONE = 0x40049409
ONE = struct.pack('<f', 1.0)
ZERO = bytes(4)
ZERO_ACTION = bytes(8)


def floor(paths, threshold):
    if any(shutil.disk_usage(path).free < threshold for path in paths):
        raise ValueError('insufficient free space; retain existing outputs')


def reservation(output, n, length, image, row, map_row):
    """Reserve a fully unshared single output before its creation."""
    full = 64 + n * length * (image + row + map_row)
    threshold = max(38 * GIB, 34 * GIB + full)
    floor((Path(output).parent, ROOT, Path.home()), threshold)
    return {'fullLogicalBytes': full, 'minimumFreeBytes': threshold,
            'observedFreeBytes': shutil.disk_usage(Path(output).parent).free}


def clone(source, destination):
    source, destination = Path(source), Path(destination)
    if source.is_symlink() or not source.is_file() or destination.exists() or destination.is_symlink():
        raise ValueError('source invalid or destination already exists')
    with source.open('rb') as src, destination.open('xb') as dst:
        before = os.fstat(src.fileno()); after = os.fstat(dst.fileno())
        if before.st_dev != after.st_dev or before.st_ino == after.st_ino or before.st_nlink != 1 or after.st_nlink != 1:
            raise ValueError('clone must use separate single-link inodes on one filesystem')
        fcntl.ioctl(dst.fileno(), FICLONE, src.fileno())
        dst.flush(); os.fsync(dst.fileno())


def dimensions(path, magic, n, fit, length, width):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('source must be a regular non-symlink file')
    with path.open('rb') as source:
        header = source.read(32)
    if (header != struct.pack('<8s3q', magic, n, fit, length) or
            path.stat().st_size != 32 + n * length * width):
        raise ValueError('source dimensions or split differ')


def move_validation(stream, old_count, old_fit, added, stride, minimum):
    stream.truncate(32 + (old_count + added) * stride)
    for index in range(old_count - 1, old_fit - 1, -1):
        floor((Path(stream.name).parent,), minimum)
        stream.seek(32 + index * stride); data = stream.read(stride)
        if len(data) != stride:
            raise ValueError('short baseline validation episode')
        stream.seek(32 + (index + added) * stride)
        if stream.write(data) != len(data):
            raise ValueError('short validation write')
        floor((Path(stream.name).parent,), minimum)


def actions(path, length):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('missing executed action journal')
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if len(rows) != length:
        raise ValueError('incomplete executed action journal')
    out = []
    for row in rows:
        value = row.get('action')
        if not isinstance(value, list) or len(value) != 2 or any(type(x) not in (int, float) or not math.isfinite(x) or abs(x) > 1 for x in value):
            raise ValueError('invalid executed action')
        out.append(struct.pack('<2f', *value))
    return out


def selected_inputs(shards, selected, length, image, raw_row, map_row):
    if (len(shards) != len(selected) or not selected or
            len({Path(path).resolve() for path in shards}) != len(shards) or
            len({entry[2] for entry in selected}) != len(selected)):
        raise ValueError('wrong selected fitting episode count')
    result = []
    for source, (episode, cutoff, seed) in zip(shards, selected):
        if (type(episode) is not int or episode != 0 or type(cutoff) is not int or not 1 <= cutoff <= length or
                type(seed) is not int):
            raise ValueError('companion or invalid fitting selection')
        source = Path(source)
        dimensions(source / 'data.bin', b'PVDATA01', 2, 1, length, image + raw_row)
        dimensions(source / 'map.bin', b'PVMAP001', 2, 1, length, map_row)
        game = source / f'expert-{episode}'
        journal = game / 'decisions.jsonl'; result_path = game / 'result.json'; events_path = game / 'chase.jsonl'
        if any(path.is_symlink() or not path.is_file() for path in (result_path, events_path)):
            raise ValueError('missing fitting game evidence')
        game_result = json.loads(result_path.read_text())
        events = [json.loads(line) for line in events_path.read_text().splitlines()]
        deliveries = [event.get('step') for event in events if event.get('event') == 'delivery']
        if (game_result.get('seed') != seed or game_result.get('steps') != length or
                not deliveries or deliveries[0] != cutoff):
            raise ValueError('fitting seed, horizon or first-delivery cutoff differs')
        result.append({'data': source / 'data.bin', 'map': source / 'map.bin', 'episode': episode,
                       'cutoff': cutoff, 'seed': seed, 'actions': actions(journal, length)})
    return result


def protect_sources(output, base_data, base_map, shards):
    output = Path(output).absolute()
    paths = [Path(base_data), Path(base_map)] + [Path(shard) / name for shard in shards for name in ('data.bin', 'map.bin')]
    identities = set()
    for path in paths:
        if path.is_symlink() or not path.is_file() or output.resolve().is_relative_to(path.parent.resolve()):
            raise ValueError('invalid source or output inside source tree')
        stat = path.stat(); identity = (stat.st_dev, stat.st_ino)
        if stat.st_nlink != 1 or identity in identities:
            raise ValueError('hard-linked or aliased input')
        identities.add(identity)


def create_control(base_data, base_map, shards, output, selected, *, old_count=1029, old_fit=933,
                   length=300, image=21168, raw_row=44, row=56, map_row=144, minimum=34 * GIB):
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError('control output exists; preserve it')
    if raw_row != 44 or row != 56:
        raise ValueError('unsupported PVDATA01/PVDATA04 row layout')
    protect_sources(output, base_data, base_map, shards)
    dimensions(base_data, b'PVDATA04', old_count, old_fit, length, image + row)
    dimensions(base_map, b'PVMAP001', old_count, old_fit, length, map_row)
    sources = selected_inputs(shards, selected, length, image, raw_row, map_row)
    reserve = reservation(output, old_count + len(sources), length, image, row, map_row)
    output.mkdir(); clone(base_data, output / 'data.bin'); clone(base_map, output / 'map.bin')
    stride = length * (image + row); raw_stride = length * (image + raw_row); map_stride = length * map_row
    with (output / 'data.bin').open('r+b') as data, (output / 'map.bin').open('r+b') as maps:
        move_validation(data, old_count, old_fit, len(sources), stride, minimum)
        move_validation(maps, old_count, old_fit, len(sources), map_stride, minimum)
        for destination, source in enumerate(sources, old_fit):
            floor((output,), minimum)
            with source['data'].open('rb') as src, source['map'].open('rb') as srcmap:
                src.seek(32 + source['episode'] * raw_stride)
                images = src.read(length * image); raw = src.read(length * raw_row)
                srcmap.seek(32 + source['episode'] * map_stride); mapbytes = srcmap.read(map_stride)
            if len(images) != length * image or len(raw) != length * raw_row or len(mapbytes) != map_stride:
                raise ValueError('short fitting history')
            converted = bytearray()
            for index in range(length):
                original = raw[index * raw_row:(index + 1) * raw_row]
                if original[36:40] != ZERO or original[40:44] != ONE:
                    raise ValueError('unexpected source phase or supervision mask')
                label = original[28:36] if index < source['cutoff'] else ZERO_ACTION
                converted.extend(original[:28] + label + original[36:40] +
                                 (ONE if index < source['cutoff'] else ZERO) + ONE + source['actions'][index])
            data.seek(32 + destination * stride)
            if data.write(images) != len(images) or data.write(converted) != len(converted):
                raise ValueError('short control data write')
            maps.seek(32 + destination * map_stride)
            if maps.write(mapbytes) != len(mapbytes):
                raise ValueError('short control map write')
            floor((output,), minimum)
        for stream in (data, maps):
            stream.seek(8); stream.write(struct.pack('<3q', old_count + len(sources), old_fit + len(sources), length))
            stream.flush(); os.fsync(stream.fileno())
    return {'reservation': reserve, 'episodes': old_count + len(sources), 'fitting': old_fit + len(sources),
            'added': len(sources)}


def create_treatment(control, shards, output, selected, *, old_count=1029, old_fit=933,
                     length=300, image=21168, raw_row=44, row=56, map_row=144, minimum=34 * GIB):
    output, control = Path(output).absolute(), Path(control).absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError('treatment output exists; preserve it')
    sources = selected_inputs(shards, selected, length, image, raw_row, map_row)
    dimensions(control / 'data.bin', b'PVDATA04', old_count + len(sources), old_fit + len(sources), length, image + row)
    dimensions(control / 'map.bin', b'PVMAP001', old_count + len(sources), old_fit + len(sources), length, map_row)
    reserve = reservation(output, old_count + len(sources), length, image, row, map_row)
    output.mkdir(); clone(control / 'data.bin', output / 'data.bin'); clone(control / 'map.bin', output / 'map.bin')
    stride = length * (image + row); changes = 0
    with (output / 'data.bin').open('r+b') as data:
        for destination, source in enumerate(sources, old_fit):
            for index in range(source['cutoff']):
                floor((output,), minimum)
                offset = 32 + destination * stride + length * image + index * row + 28
                data.seek(offset); before = data.read(8)
                if len(before) != 8:
                    raise ValueError('short treatment label')
                action = source['actions'][index]; changes += before != action
                data.seek(offset)
                if data.write(action) != 8:
                    raise ValueError('short treatment label write')
            floor((output,), minimum)
        data.flush(); os.fsync(data.fileno())
    if not changes:
        raise ValueError('no parent/teacher differences in supervised prefixes')
    return {'reservation': reserve, 'labelChanges': changes}


def create_pair(base_data, base_map, shards, output, selected, **kwargs):
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError('paired output exists; preserve it')
    protect_sources(output, base_data, base_map, shards)
    output.mkdir()
    first = create_control(base_data, base_map, shards, output / 'control', selected, **kwargs)
    # Recheck the full one-output reservation after control has been completed.
    # If it fails, retain the first arm and never create the second arm.
    second = create_treatment(output / 'control', shards, output / 'treatment', selected, **kwargs)
    return {'control': first, 'treatment': second,
            'scope': 'unverified data candidates only; no training or promotion authorization'}


if __name__ == '__main__':
    raise SystemExit('Disabled pending provenance checks, supervision and independent review.')
