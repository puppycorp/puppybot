#!/usr/bin/env python3
"""Compare two derived datasets with all baseline and collected source bytes.

This verifier checks construction and same-process recorded collector buffers.
Provenance, input identity, resource supervision and actor/camera/map truth
must be established separately before any dataset is used.
"""
import json
import math
import mmap
import struct
from pathlib import Path


ZERO = b'\0' * 4
ONE = struct.pack('<f', 1.0)
CODEC = {struct.pack('<2f', *values) for values in
         ((-.6, 1), (0, 1), (.6, 1), (-.6, -1), (0, -1), (.6, -1), (0, 0))}


def dimensions(data, magic, count, fitting, length, stride):
    if (len(data) != 32 + count * length * stride or data[:8] != magic or
            struct.unpack_from('<3q', data, 8) != (count, fitting, length)):
        raise ValueError('dataset header, split or size differs')


def same_range(left, lo, right, ro, length):
    for start in range(0, length, 4 * 1024 * 1024):
        size = min(4 * 1024 * 1024, length - start)
        if left[lo + start:lo + start + size] != right[ro + start:ro + start + size]:
            raise ValueError('preserved episode bytes differ')


def open_regular(path, handles):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('input must be a regular non-symlink file')
    handle = path.open('rb'); handles.append(handle)
    return mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ)


def finite(data):
    if any(not math.isfinite(value) for value in struct.unpack('<' + 'f' * (len(data) // 4), data)):
        raise ValueError('non-finite actor buffer')


def source_actions(spec, data, maps, *, length, image, raw_row, map_row, memory):
    """Check a source fitting episode's aligned native boundary records."""
    seed, episode, cutoff = spec['seed'], spec['episode'], spec['cutoff']
    if (type(seed) is not int or type(episode) is not int or episode != 0 or
            type(cutoff) is not int or not 1 <= cutoff <= length):
        raise ValueError('source must be fitting episode zero with a valid cutoff')
    dimensions(data, b'PVDATA01', 2, 1, length, image + raw_row)
    dimensions(maps, b'PVMAP001', 2, 1, length, map_row)
    actor_path, boundary_path, decision_path, event_path = map(Path,
        (spec['actor'], spec['boundary'], spec['decisions'], spec['events']))
    for path in (actor_path, boundary_path, decision_path, event_path):
        if path.is_symlink() or not path.is_file():
            raise ValueError('source journal must be a regular non-symlink file')
    rows = [json.loads(line) for line in decision_path.read_text().splitlines()]
    events = [json.loads(line) for line in event_path.read_text().splitlines()]
    deliveries = [event.get('step') for event in events if event.get('event') == 'delivery']
    if (len(rows) != length or not events or events[0].get('event') != 'start' or not deliveries or
            any(event.get('event') != 'delivery' for event in events[1:]) or
            any(type(value) is not int or not 1 <= value <= length for value in deliveries) or
            deliveries != sorted(set(deliveries)) or deliveries[0] != cutoff):
        raise ValueError('source saved delivery events or horizon differ')
    for index, row in enumerate(rows):
        task = row['state']['findReturn']
        if (type(task.get('deliveries')) is not int or
                task['deliveries'] != sum(step <= index + 1 for step in deliveries) or
                (task.get('phase') == 'delivered') != (index + 1 in deliveries)):
            raise ValueError('source task states and delivery events disagree')
    record = 24 + image + (image + 7 + memory) * 4 + (2 + memory) * 4 + 8
    map_record = 24 + map_row + 8
    expected_actor_size = 56 + length * record + 16
    expected_boundary_size = 40 + length * map_record + 16
    if actor_path.stat().st_size != expected_actor_size or boundary_path.stat().st_size != expected_boundary_size:
        raise ValueError('source boundary journal size differs')
    actions = []; differences = 0
    with actor_path.open('rb') as actor, boundary_path.open('rb') as boundary:
        if struct.unpack('<8s6q', actor.read(56)) != (b'PBATST01', 1, seed, length, image, memory, record):
            raise ValueError('source actor header differs')
        if struct.unpack('<8s4q', boundary.read(40)) != (b'PBMAPB01', 1, seed, length, map_record):
            raise ValueError('source map header differs')
        previous_hidden = bytes(memory * 4); last_seq = last_frame = -1
        base = 32 + episode * length * (image + raw_row)
        for index, row in enumerate(rows):
            identity = struct.unpack('<3q', actor.read(24))
            frame = actor.read(image); inputs = actor.read((image + 7 + memory) * 4)
            output = actor.read((2 + memory) * 4); action = actor.read(8)
            map_identity = struct.unpack('<3q', boundary.read(24)); recorded_map = boundary.read(map_row)
            teacher = boundary.read(8)
            if (identity != map_identity or identity[0] != index or identity[1] <= last_seq or
                    identity[2] <= last_frame or row.get('sequence') != identity[1] + 1 or
                    row.get('step') != identity[2] + 10 or row['state']['totalSteps'] != row['step']):
                raise ValueError('source boundary order differs')
            last_seq, last_frame = identity[1:]
            x = base + length * image + index * raw_row
            raw = data[x:x + raw_row]
            if raw_row != 44 or len(raw) != 44 or data[base + index * image:base + (index + 1) * image] != frame:
                raise ValueError('source actor image differs from data row')
            normalized = b''.join(struct.pack('<f', value / 255.0) for value in frame)
            if (inputs[:image * 4] != normalized or raw[:28] != inputs[image * 4:(image + 7) * 4] or
                    inputs[(image + 7) * 4:] != previous_hidden or output[:8] != action):
                raise ValueError('source normalized input, feedback, recurrent state or output differs')
            finite(inputs); finite(output); previous_hidden = output[8:]
            if (teacher not in CODEC or action not in CODEC or raw[28:36] != teacher or
                    action != struct.pack('<2f', *row['action']) or raw[36:44] != ZERO + ONE):
                raise ValueError('source teacher label, executed action or mask differs')
            pre_state = rows[index - 1]['state']['findReturn'] if index else None
            expected_cue = float(bool(pre_state and pre_state['consumedIndex'] >= 0 and pre_state['phase'] != 'delivered'))
            if struct.unpack_from('<f', raw, 24)[0] != expected_cue:
                raise ValueError('source carry cue differs')
            mo = 32 + (episode * length + index) * map_row
            if maps[mo:mo + map_row] != recorded_map or any(value > 2 for value in recorded_map):
                raise ValueError('source map row differs from boundary')
            if index < cutoff and teacher != action:
                differences += 1
            actions.append(action)
        if actor.read(16) != struct.pack('<8sq', b'PBDONE01', length) or actor.read(1):
            raise ValueError('source actor footer differs')
        if boundary.read(16) != struct.pack('<8sq', b'PBDONE01', length) or boundary.read(1):
            raise ValueError('source boundary footer differs')
    if not differences:
        raise ValueError('source has no supervised-prefix label difference')
    return actions, differences


def verify(base_path, base_map_path, source_specs, control_path, control_map_path,
           treatment_path, treatment_map_path, *, old_count=1029, old_fit=933,
           length=300, image=21168, raw_row=44, row=56, map_row=144, memory=128,
           expected_sources=((7820010, 0, 163), (7820025, 0, 189)), aux_mask_begin=928):
    """Reject any byte other than registered prefix action-label differences."""
    if (len(source_specs) != 2 or len({spec['seed'] for spec in source_specs}) != 2 or
            tuple((item['seed'], item['episode'], item['cutoff']) for item in source_specs) != tuple(expected_sources) or
            not 0 < old_fit < old_count or not 0 <= aux_mask_begin <= old_fit or row != 56 or raw_row != 44):
        raise ValueError('invalid source identities, baseline split or row width')
    paths = [Path(path) for path in (base_path, base_map_path, control_path, control_map_path,
                                     treatment_path, treatment_map_path)]
    paths += [Path(spec[key]) for spec in source_specs for key in ('data', 'map')]
    identities = []
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise ValueError('dataset must be regular and not symlinked')
        stat = path.stat(); identities.append((stat.st_dev, stat.st_ino))
    if len(identities) != len(set(identities)):
        raise ValueError('dataset input or output aliases another inode')
    handles = []; views = []
    try:
        for path in paths:
            views.append(open_regular(path, handles))
        base, base_map, control, control_map, treatment, treatment_map, source0, map0, source1, map1 = views
        n, fit = old_count + 2, old_fit + 2
        dimensions(base, b'PVDATA04', old_count, old_fit, length, image + row)
        dimensions(base_map, b'PVMAP001', old_count, old_fit, length, map_row)
        for out, out_map in ((control, control_map), (treatment, treatment_map)):
            dimensions(out, b'PVDATA04', n, fit, length, image + row)
            dimensions(out_map, b'PVMAP001', n, fit, length, map_row)
        stride = length * (image + row); raw_stride = length * (image + raw_row); map_stride = length * map_row
        for out, out_map in ((control, control_map), (treatment, treatment_map)):
            same_range(base, 32, out, 32, old_fit * stride)
            same_range(base, 32 + old_fit * stride, out, 32 + fit * stride, (old_count - old_fit) * stride)
            same_range(base_map, 32, out_map, 32, old_fit * map_stride)
            same_range(base_map, 32 + old_fit * map_stride, out_map, 32 + fit * map_stride,
                       (old_count - old_fit) * map_stride)
        differences = []
        for offset, (spec, raw, raw_map) in enumerate(zip(source_specs, (source0, source1), (map0, map1))):
            actions, count = source_actions(spec, raw, raw_map, length=length, image=image, raw_row=raw_row,
                                            map_row=map_row, memory=memory)
            differences.append(count)
            source_base = 32 + spec['episode'] * raw_stride
            destination = 32 + (old_fit + offset) * stride
            same_range(raw, source_base, control, destination, length * image)
            same_range(raw, source_base, treatment, destination, length * image)
            for out_map in (control_map, treatment_map):
                same_range(raw_map, 32 + spec['episode'] * map_stride, out_map,
                           32 + (old_fit + offset) * map_stride, map_stride)
            for index, action in enumerate(actions):
                x = source_base + length * image + index * raw_row
                y = destination + length * image + index * row
                source = raw[x:x + raw_row]
                supervised = index < spec['cutoff']
                label = source[28:36] if supervised else bytes(8)
                parent_label = action if supervised else bytes(8)
                expected_control = source[:28] + label + source[36:40] + (ONE if supervised else ZERO) + ONE + action
                expected_treatment = source[:28] + parent_label + source[36:40] + (ONE if supervised else ZERO) + ONE + action
                if control[y:y + row] != expected_control or treatment[y:y + row] != expected_treatment:
                    raise ValueError('paired label, feedback, mask, validity or executed action differs')
        return {'status': 'paired_aggregate_bytes_verified', 'episodes': n, 'fitting': fit,
                'baselineEpisodesPreserved': old_count, 'addedFittingEpisodes': 2,
                'excludedCompanionEpisodes': 2, 'prefixLabelDifferences': differences,
                'suffixActionTargets': 'zero', 'suffixWeight': 0, 'suffixValid': 1,
                'auxiliaryMaskRequirement': {'episodeStartInclusive': aux_mask_begin,
                                             'episodeEndExclusive': fit,
                                             'condition': 'mask auxiliary losses where supervision weight is zero',
                                             'status': 'not_verified_by_dataset_verifier'},
                'trainingAuthorized': False,
                'scope': 'local bytes and same-process recorded buffers only; no independent actor, camera, map truth or training proof'}
    finally:
        for view in views:
            view.close()
        for handle in handles:
            handle.close()
