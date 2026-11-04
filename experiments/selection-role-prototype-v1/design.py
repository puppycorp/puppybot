#!/usr/bin/env python3
"""Prospective selection identities and exact-geometry comparison only."""
import hashlib
import json
import math


def rows():
    return [{'level': level, 'index': index,
             'layoutId': 290 + index if level <= 3 else 291 + 2 * index,
             'variant': index % 16, 'seed': 1800000000 + 100 * level + index}
            for level in range(1, 6) for index in range(32)]


def vector(value, size):
    if not isinstance(value, list) or len(value) != size:
        raise ValueError('invalid geometry vector')
    result = []
    for number in value:
        if type(number) not in (int, float) or not math.isfinite(number):
            raise ValueError('nonfinite geometry')
        number = float(number)
        result.append(0.0 if number == 0 else number)
    return tuple(result)


def geometry(layout):
    """Hash exact room/door/obstacle coordinates independent of layout name.

    This does not identify near-matches, alternate representations or all
    semantic overlap; start pose and appearance are not geometry here.
    """
    if not isinstance(layout, dict):
        raise ValueError('layout must be an object')
    rooms, obstacles = layout.get('rooms'), layout.get('obstacles')
    if not isinstance(rooms, list) or not 1 <= len(rooms) <= 2 or not isinstance(obstacles, list):
        raise ValueError('invalid room or obstacle list')
    door = layout.get('door')
    canonical = {'rooms': sorted(vector(item, 4) for item in rooms),
                 'door': None if door is None else vector(door, 3),
                 'obstacles': sorted(vector(item, 4) for item in obstacles)}
    if (door is None) != (len(rooms) == 1):
        raise ValueError('door and room count differ')
    encoded = json.dumps(canonical, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def compare_history(prior_seeds, prior_layouts, candidate_layouts):
    """Check supplied prior seeds and exact geometries; no ancestry claim."""
    if not prior_seeds or not prior_layouts or not candidate_layouts:
        raise ValueError('explicit nonempty prior and candidate evidence required')
    if any(type(seed) is not int or seed < 0 for seed in prior_seeds):
        raise ValueError('invalid prior seed')
    proposed = {row['seed'] for row in rows()}
    overlap = proposed.intersection(prior_seeds)
    if overlap:
        raise ValueError('candidate seeds overlap supplied history')
    previous = {geometry(item) for item in prior_layouts}
    current = {geometry(item) for item in candidate_layouts}
    if previous & current:
        raise ValueError('candidate exact geometry overlaps supplied history')
    return {'status': 'supplied_history_no_exact_overlap', 'priorSeeds': len(prior_seeds),
            'priorGeometry': len(previous), 'candidateGeometry': len(current),
            'priorSeedInventorySHA256': hashlib.sha256(json.dumps(sorted(set(prior_seeds)), separators=(',', ':')).encode()).hexdigest(),
            'priorGeometryInventorySHA256': hashlib.sha256(json.dumps(sorted(previous), separators=(',', ':')).encode()).hexdigest(),
            'scope': 'supplied records only; unknown ancestry and near-geometry overlap remain'}
