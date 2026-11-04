#!/usr/bin/env python3
"""Compare saved collector rows to private same-boundary observations.

This is local self-consistency, not proof of camera provenance, independent
map correctness, model execution, or a successful robot task.
"""
import math
import struct
from pathlib import Path


IMAGE = 21168
WIDTH = 128
ROW = 44
MAP = 144
ACTOR_RECORD = 24 + IMAGE + (IMAGE + 7 + WIDTH) * 4 + (2 + WIDTH) * 4 + 8
MAP_RECORD = 24 + MAP + 8
CODEC = {struct.pack('<2f', *action) for action in
         ((-.6, 1), (0, 1), (.6, 1), (-.6, -1), (0, -1), (.6, -1), (0, 0))}


def exact(stream, size):
    data = stream.read(size)
    if len(data) != size:
        raise ValueError('truncated input')
    return data


def finite(data):
    values = struct.unpack('<' + 'f' * (len(data) // 4), data)
    if any(not math.isfinite(value) for value in values):
        raise ValueError('non-finite boundary value')
    return values


def audit(data_path, map_path, actor_path, boundary_path, seed, episode, rows, first_delivery):
    """Audit one fitting game after an independent saved-game audit."""
    if type(seed) is not int or type(episode) is not int or episode < 0 or not rows:
        raise ValueError('invalid game identity')
    length = len(rows)
    if type(first_delivery) is not int or not 1 <= first_delivery <= length:
        raise ValueError('first delivery missing or outside horizon')
    deliveries = [row['state']['findReturn']['deliveries'] for row in rows]
    if (any(type(value) is not int or value < 0 for value in deliveries) or
            any(later < earlier or later > earlier + 1 for earlier, later in zip([0] + deliveries, deliveries)) or
            next((index + 1 for index, value in enumerate(deliveries) if value), None) != first_delivery):
        raise ValueError('first delivery differs from saved task states')
    with Path(data_path).open('rb') as dataset, Path(map_path).open('rb') as maps, \
            Path(actor_path).open('rb') as actor, Path(boundary_path).open('rb') as boundaries:
        data_header = struct.unpack('<8s3q', exact(dataset, 32))
        map_header = struct.unpack('<8s3q', exact(maps, 32))
        if (data_header[0] != b'PVDATA01' or map_header[0] != b'PVMAP001' or
                data_header[1:] != map_header[1:] or data_header[3] != length or
                not 0 <= episode < data_header[1] or not 0 < data_header[2] < data_header[1]):
            raise ValueError('dataset dimensions or split differ')
        if (Path(data_path).stat().st_size != 32 + data_header[1] * length * (IMAGE + ROW) or
                Path(map_path).stat().st_size != 32 + data_header[1] * length * MAP):
            raise ValueError('dataset length differs')
        actor_header = struct.unpack('<8s6q', exact(actor, 56))
        boundary_header = struct.unpack('<8s4q', exact(boundaries, 40))
        if actor_header != (b'PBATST01', 1, seed, length, IMAGE, WIDTH, ACTOR_RECORD):
            raise ValueError('actor journal header differs')
        if boundary_header != (b'PBMAPB01', 1, seed, length, MAP_RECORD):
            raise ValueError('map boundary header differs')
        base = 32 + episode * length * (IMAGE + ROW)
        previous_hidden = bytes(WIDTH * 4)
        previous_sequence = previous_frame = -1
        disagreements = 0; prefix_disagreements = 0
        for index, row in enumerate(rows):
            identity = struct.unpack('<3q', exact(actor, 24))
            image = exact(actor, IMAGE)
            inputs = exact(actor, (IMAGE + 7 + WIDTH) * 4)
            output = exact(actor, (2 + WIDTH) * 4)
            action = exact(actor, 8)
            map_identity = struct.unpack('<3q', exact(boundaries, 24))
            actual_map = exact(boundaries, MAP)
            label = exact(boundaries, 8)
            if (identity != map_identity or identity[0] != index or identity[1] <= previous_sequence or
                    identity[2] <= previous_frame or row.get('sequence') != identity[1] + 1 or
                    row.get('step') != identity[2] + 10 or row['state']['totalSteps'] != row['step']):
                raise ValueError('actor, map and decision order differ')
            previous_sequence, previous_frame = identity[1:]
            dataset.seek(base + index * IMAGE)
            if exact(dataset, IMAGE) != image:
                raise ValueError('dataset RGB differs from actor boundary')
            dataset.seek(base + length * IMAGE + index * ROW)
            packed = exact(dataset, ROW)
            maps.seek(32 + (episode * length + index) * MAP)
            if exact(maps, MAP) != actual_map or any(value > 2 for value in actual_map):
                raise ValueError('dataset map differs from boundary or contains invalid values')
            if packed[:28] != inputs[IMAGE * 4:(IMAGE + 7) * 4] or packed[28:36] != label:
                raise ValueError('dataset feedback or teacher label differs from boundary')
            if packed[36:44] != struct.pack('<2f', 0, 1) or label not in CODEC:
                raise ValueError('teacher action, phase or mask differs')
            expected_pixels = b''.join(struct.pack('<f', value / 255.0) for value in image)
            if inputs[:IMAGE * 4] != expected_pixels:
                raise ValueError('actor image normalization differs')
            if inputs[(IMAGE + 7) * 4:] != previous_hidden or output[:8] != action:
                raise ValueError('actor recurrent state or returned action differs')
            previous_hidden = output[8:]
            finite(inputs); finite(output)
            if action not in CODEC or action != struct.pack('<2f', *row['action']):
                raise ValueError('actor action differs from executed decision')
            cue = struct.unpack_from('<f', packed, 24)[0]
            previous = rows[index - 1]['state']['findReturn'] if index else None
            expected_cue = float(bool(previous and previous['consumedIndex'] >= 0 and previous['phase'] != 'delivered'))
            if cue != expected_cue:
                raise ValueError('pre-action carry cue differs from saved task state')
            disagreements += label != action
            if index < first_delivery:
                prefix_disagreements += label != action
        if exact(actor, 16) != struct.pack('<8sq', b'PBDONE01', length) or actor.read(1):
            raise ValueError('actor journal footer differs')
        if exact(boundaries, 16) != struct.pack('<8sq', b'PBDONE01', length) or boundaries.read(1):
            raise ValueError('map journal footer differs')
    if not prefix_disagreements:
        raise ValueError('teacher and parent labels do not differ within the first-delivery prefix')
    return {'status': 'local_boundary_consistent', 'seed': seed, 'episode': episode,
            'rows': length, 'firstDeliveryAction': first_delivery, 'labelDifferences': disagreements,
            'prefixLabelDifferences': prefix_disagreements,
            'scope': ('same-process saved buffer consistency only; not independent camera, map truth, '
                      'actor execution or physical-task attestation')}
