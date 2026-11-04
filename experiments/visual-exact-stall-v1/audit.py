#!/usr/bin/env python3
"""Retrospective exact actor-image runs in four saved training diagnostics."""
import json
import math
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'build/flex/sim/levels-v2/pitch82'
GROUPS = ('l5-steering-kick-diagnostic-v1', 'l5-steering-hysteresis-diagnostic-v1',
          'l5-steering-hysteresis-debug-v1', 'contact-stop-trial-v2')


def expected_streams(name):
    if name == GROUPS[0]:
        return {Path('games') / str(i) / arm / str(6800100 + i) / 'steer-probe.jsonl'
                for i in range(12) for arm in ('control', 'intervention')}
    if name == GROUPS[1]:
        return {Path('games') / str(i) / arm / str(6800200 + i) / 'steer-probe.jsonl'
                for i in range(12) for arm in ('control', 'kick', 'kick-hysteresis')}
    if name == GROUPS[2]:
        return {Path('games') / str(i) / arm / str(seed) / 'steer-probe.jsonl'
                for i, seed in enumerate((6800102, 6800107))
                for arm in ('control', 'kick', 'kick-hysteresis')}
    if name == GROUPS[3]:
        return {Path('games') / str(i) / arm / str(seed) / 'steer-probe.jsonl'
                for i, seed in enumerate((6800102, 6800107))
                for arm in ('disabled', 'enabled')}
    raise ValueError('unknown saved diagnostic')


def inventory(root, name):
    root = Path(root)
    expected = expected_streams(name)
    actual = {path.relative_to(root) for path in root.rglob('steer-probe.jsonl')}
    if actual != expected:
        raise ValueError('saved actor stream inventory differs: ' + name)
    return sorted(root / path for path in expected)


def read_rows(path):
    with path.open() as stream:
        return [json.loads(line) for line in stream]


def runs(probe, decisions, initial, threshold=5):
    if not probe or len(decisions) < len(probe) or threshold < 2:
        raise ValueError('missing actor or decision rows')
    states = [initial] + [row['state'] for row in decisions[:len(probe) - 1]]
    for index, (actor, state) in enumerate(zip(probe, states)):
        frame = state['totalSteps']; camera = state['camera']; perception = state['case']['perception']
        if (actor['step'] != index + 1 or not isinstance(actor['imageSHA256'], str) or
                len(actor['imageSHA256']) != 64 or perception['frameId'] != frame or
                camera['pose'] != 'driving' or camera['armSettled'] is not True or
                len(state['pose']) != 3 or not all(math.isfinite(v) for v in state['pose'])):
            raise ValueError('invalid actor frame, pose or camera')
        if index:
            drive = state['controller']['drive']; echo = probe[index - 1]['echo']
            if [drive['leftSpeed'], drive['rightSpeed'], drive['steeringAngleDeg']] != echo:
                raise ValueError('recorded wheel echo differs')
    result = []; start = 0
    for index in range(1, len(probe) + 1):
        if index < len(probe):
            previous = probe[index - 1]; prior_state = states[index - 1]; state = states[index]
            consecutive = (state['totalSteps'] == prior_state['totalSteps'] + 10 and
                           (index <= 1 or decisions[index - 1]['sequence'] == decisions[index - 2]['sequence'] + 1))
            if (consecutive and previous['echo'][:2] != [0, 0] and
                    probe[index]['imageSHA256'] == previous['imageSHA256']):
                continue
        count = index - start
        if count >= threshold:
            origin = states[start]['pose']; displacement = 0.0; rotation = 0.0
            for state in states[start:index]:
                pose = state['pose']; displacement = max(displacement, math.hypot(pose[0] - origin[0], pose[1] - origin[1]))
                difference = pose[2] - origin[2]
                rotation = max(rotation, abs(math.atan2(math.sin(difference), math.cos(difference))))
            if displacement <= 0.01 and rotation <= math.radians(2): truth = 'stationary'
            elif displacement >= 0.05 or rotation >= math.radians(10): truth = 'moving'
            else: truth = 'ambiguous'
            result.append({'firstDecision': start + 1, 'lastDecision': index, 'identicalFrames': count,
                           'firstFiveFrameTriggerBeforeDecision': start + 5, 'truthClass': truth,
                           'truthMaximumDisplacementM': displacement, 'truthMaximumTurnRad': rotation})
        start = index
    return result


def audit(base=BASE):
    groups = {}; examples = []
    for name in GROUPS:
        count = Counter(); root = base / name
        for path in inventory(root, name):
            directory = path.parent
            found = runs(read_rows(path), read_rows(directory / 'decisions.jsonl'),
                         json.loads((directory / 'initial.json').read_text()))
            count['games'] += 1
            for threshold in (5, 10, 20):
                selected = [item for item in found if item['identicalFrames'] >= threshold]
                if selected:
                    count[f'gamesAtLeast{threshold}'] += 1
                    for kind in set(item['truthClass'] for item in selected): count[f'gamesAtLeast{threshold}_{kind}'] += 1
            for item in found:
                examples.append({'group': name, 'game': str(directory.relative_to(root)), **item})
        groups[name] = dict(count)
    return {'scope': 'post-hoc correlated training games; simulator truth only for after-run classification',
            'thresholdFrames': [5, 10, 20], 'groups': groups, 'examples': examples}


if __name__ == '__main__':
    print(json.dumps(audit(), indent=2, sort_keys=True))
