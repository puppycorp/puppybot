#!/usr/bin/env python3
"""Audit simulated physical grasp and placement, independently of task labels.

Usage: manipulation_audit.py CASE_JSON TRACE_JSONL

This evaluates simulator truth after a run; none of its body IDs, contacts or
containment values may be fed into a deployed policy as physical observations.
"""
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path


def normalized_quaternion(value):
    if len(value) != 4 or any(not math.isfinite(v) for v in value):
        raise ValueError('invalid quaternion')
    length = math.sqrt(sum(v*v for v in value))
    if not 0.99 <= length <= 1.01:
        raise ValueError('invalid quaternion norm')
    return [v / length for v in value]


def rotation_delta(a, b):
    a, b = normalized_quaternion(a), normalized_quaternion(b)
    dot = min(1.0, abs(sum(x*y for x, y in zip(a, b))))
    return 2 * math.acos(dot)


def near_box(obj, box, definition, geometry, margin, extra_height):
    rotation = geometry.rotation(box['quaternion'])
    relative = [sum(rotation[k][i] * (obj['position'][k] - box['position'][k]) for k in range(3)) for i in range(3)]
    size = definition['container']['innerSize']
    floor = definition['container']['wallThickness']
    return (all(math.isfinite(x) for x in relative) and
            all(abs(relative[i]) <= size[i] / 2 + margin for i in range(2)) and
            floor - 0.03 <= relative[2] <= floor + size[2] + extra_height)


def audit(states, definition, geometry):
    # The independent geometry checker currently uses assertions internally.
    # Never allow Python optimization to silently disable those checks.
    if sys.flags.optimize:
        raise ValueError('optimized Python disables the geometry checker')
    objects = definition['objects']
    names = {o['id'] for o in objects}
    if not names or len(names) != len(objects):
        raise ValueError('case needs unique objects')
    settle = definition['success']['settleSteps']
    if not isinstance(settle, int) or settle < 1:
        raise ValueError('invalid settle duration')
    first = True
    previous_step = None
    held = None
    bodies = None
    previous_objects = {}
    previous_box = None
    previous_time = None
    episode = None
    released = set()
    released_at = {}
    stable = {name: 0 for name in names}
    completed = {}
    captures, releases = [], []
    last_inside = set()
    for state in states:
        step = state['step']
        if previous_step is None and step not in (0, 1):
            raise ValueError('trace does not start at the first simulator step')
        if previous_step is not None and step != previous_step + 1:
            raise ValueError('missing, duplicate or out-of-order simulator step')
        previous_step = step
        if state['physicsFault'] or state['vehicle']['queryFault']:
            raise ValueError('simulator physics or vehicle fault')
        case, gripper = state['case'], state['gripper']
        if case['id'] != definition['id']:
            raise ValueError('case ID differs from scene definition')
        if episode is None:
            episode = state['episode']
        elif state['episode'] != episode:
            raise ValueError('episode changed within trace')
        current_objects = case['objects']
        box = case['container']
        normalized_quaternion(box['quaternion'])
        if any(not math.isfinite(v) for v in box['position'] + box['velocity'] + box['angularVelocity']):
            raise ValueError('nonfinite box state')
        ids = {o['id'] for o in current_objects}
        mapping = {o['body']: o['id'] for o in current_objects}
        if ids != names or len(mapping) != len(names) or len(current_objects) != len(names):
            raise ValueError('case object IDs or bodies changed')
        if bodies is None:
            bodies = mapping
        elif bodies != mapping:
            raise ValueError('case body identity changed')
        current = mapping.get(gripper['body']) if gripper['held'] else None
        if gripper['held'] and current is None:
            raise ValueError('unknown held body')
        if gripper['constraintActive'] != gripper['held']:
            raise ValueError('grasp constraint and held state disagree')
        inside = set()
        for obj in current_objects:
            if obj['inside']:
                if current == obj['id']:
                    raise ValueError('held object reported inside')
                geometry.contained(obj, definition, case['container'])
                inside.add(obj['id'])
        if first:
            if current is not None or inside:
                raise ValueError('initially held or contained objects cannot be credited')
            expected = {o['id']: o for o in objects}
            for obj in current_objects:
                source = expected[obj['id']]
                q = normalized_quaternion(obj['quaternion'])
                x, y, z, w = q
                yaw = math.atan2(2 * (w*z + x*y), 1 - 2 * (y*y + z*z))
                yaw_error = math.atan2(math.sin(yaw - obj['initialYawRad']), math.cos(yaw - obj['initialYawRad']))
                if (any(not math.isfinite(v) for v in obj['initialPosition'] + obj['position'] + obj['velocity']) or
                    not math.isfinite(obj['initialYawRad']) or obj['kind'] != source['kind'] or
                    math.dist(obj['initialPosition'], source['position']) > 1e-10 or
                    abs(obj['initialYawRad'] - math.radians(source.get('yawDegrees', 0))) > 1e-10 or
                    math.dist(obj['position'][:2], source['position'][:2]) > 1e-5 or
                    abs(obj['position'][2] - source['position'][2]) > 0.003 or
                    abs(yaw_error) > 0.02 or abs(x) > 0.01 or abs(y) > 0.01):
                    raise ValueError('initial object differs from scene definition')
            if (math.dist(case['container']['position'][:2], definition['container']['position'][:2]) > 1e-4 or
                abs(case['container']['position'][2] - definition['container']['position'][2]) > 0.003):
                raise ValueError('initial container differs from scene definition')
            x, y, z, w = normalized_quaternion(box['quaternion'])
            yaw = math.atan2(2 * (w*z + x*y), 1 - 2 * (y*y + z*z))
            if abs(x) > 0.01 or abs(y) > 0.01 or abs(yaw) > 0.02:
                raise ValueError('initial container orientation differs from scene definition')
            if state['environment']['sensorCameras'] != ['tcp']:
                raise ValueError('unexpected camera configuration')
            first = False
        now = state['timeMs']
        if previous_time is not None and now - previous_time != 20:
            raise ValueError('trace time is not continuous at 20 ms')
        box_slow = False
        if previous_box is not None:
            speed = max(math.sqrt(sum(v*v for v in previous_box['velocity'])), math.sqrt(sum(v*v for v in box['velocity'])))
            if math.dist(previous_box['position'], box['position']) > 0.001 + speed * 0.04:
                raise ValueError('box motion is discontinuous')
            box_slow = (rotation_delta(previous_box['quaternion'], box['quaternion']) <= 0.002 and
                        math.sqrt(sum(v*v for v in box['angularVelocity'])) <= 0.1)
        rotation_slow = {}
        for obj in current_objects:
            name = obj['id']
            normalized_quaternion(obj['quaternion'])
            if any(not math.isfinite(v) for v in obj['position'] + obj['velocity']):
                raise ValueError('nonfinite object state')
            if name in previous_objects:
                prev = previous_objects[name]
                # 0.002 rad per 20 ms is 0.1 rad/s. Simulator containment
                # alone checks linear speed and can mark a spinning body inside.
                rotation_slow[name] = rotation_delta(prev['quaternion'], obj['quaternion']) <= 0.002
                speed = max(math.sqrt(sum(v*v for v in prev['velocity'])), math.sqrt(sum(v*v for v in obj['velocity'])))
                if not math.isfinite(speed) or any(not math.isfinite(v) for v in obj['position']) or math.dist(prev['position'], obj['position']) > 0.001 + speed * 0.04:
                    raise ValueError('object motion is discontinuous')
        previous_time = now
        previous_box = box
        previous_objects = {obj['id']: obj for obj in current_objects}
        if current != held:
            if held is not None:
                if current is not None:
                    raise ValueError('held body changed without release')
                obj = next(o for o in current_objects if o['id'] == held)
                over = near_box(obj, box, definition, geometry, 0.03, 0.3)
                if over:
                    released.add(held)
                    released_at[held] = step
                else:
                    released.discard(held)
                releases.append({'object': held, 'step': step, 'overBox': over})
            if current is not None:
                if gripper['captureContactMask'] != 3:
                    raise ValueError('capture lacks bilateral contacts')
                released.discard(current)
                completed.pop(current, None)
                stable[current] = 0
                captures.append({'object': current, 'step': step})
            held = current
        for obj in current_objects:
            name = obj['id']
            if name in released and ((name not in completed and step - released_at[name] > 500) or
                                     (name in completed and name not in inside) or
                                     not near_box(obj, box, definition, geometry, 0.15, 0.4)):
                released.discard(name)
                completed.pop(name, None)
        for name in names:
            if name in released and name in inside and box_slow and rotation_slow.get(name, False):
                stable[name] += 1
                if stable[name] == settle:
                    completed.setdefault(name, step)
            else:
                stable[name] = 0
        last_inside = inside
    if first:
        raise ValueError('empty trace')
    # Completion requires each object to be contained and stationary for the
    # full window at the end, even if it had once been placed then dislodged.
    final = sorted(name for name in names if stable[name] >= settle and name in last_inside)
    return {'captures': captures, 'releases': releases, 'settledDeliveries': completed,
            'settledAtEnd': final, 'objects': len(names),
            'traceMeetsManipulationCriteria': len(final) == len(names) and held is None,
            'status': 'diagnostic_only',
            'measurement': 'simulator-truth audit, not a physical robot sensor',
            'sceneScope': 'case ID and initial object/box positions and orientations checked; robot start, scene binary and runtime provenance must be verified separately'}


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    path = Path(__file__).resolve().parents[1] / 'tests' / 'sim-cases.py'
    spec = importlib.util.spec_from_file_location('sim_cases', path)
    geometry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(geometry)
    definition_bytes = Path(sys.argv[1]).read_bytes()
    definition = json.loads(definition_bytes)
    with Path(sys.argv[2]).open() as stream:
        result = audit((json.loads(line) for line in stream), definition, geometry)
    result['caseSHA256'] = hashlib.sha256(definition_bytes).hexdigest()
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
