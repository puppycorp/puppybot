#!/usr/bin/env python3
"""Compare sealed pre-action inputs and chosen actions in four saved replays.

This is a read-only analysis of reused training-family scenes. Actor RGB here
is the saved, resized policy input, not an independently attested raw frame.
"""
import hashlib
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CAPTURE = ROOT / 'build/flex/sim/levels-v2/pitch82/l5-actor-frame-capture-v4'
SEEDS = (7820010, 7820025)
ARMS = ('control', 'treatment')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    completion_bytes = (CAPTURE / 'completion.json').read_bytes()
    completion = json.loads(completion_bytes)
    receipts = {'planSHA256': 'plan.json', 'workerResultSHA256': 'worker-result.json',
                'inventorySHA256': 'inventory.json', 'telemetrySHA256': 'telemetry.jsonl',
                'supervisorSHA256': 'outer-monitor/supervisor-result.json',
                'outerClientLogSHA256': 'outer-monitor/client.log',
                'finalSupervisorSHA256': 'outer-monitor/final-supervisor-result.json',
                'finalClientLogSHA256': 'outer-monitor/final-client.log'}
    if completion.get('status') != 'captured_diagnostic_only':
        raise ValueError('capture completion missing')
    for key, relative in receipts.items():
        if digest((CAPTURE / relative).read_bytes()) != completion.get(key):
            raise ValueError(f'capture receipt mismatch: {relative}')
    final = json.loads((CAPTURE / 'outer-monitor/final-client.log').read_bytes())
    if (final.get('status') != 'final_inventory_verified' or
            final.get('inventorySHA256') != completion['inventorySHA256'] or
            final.get('planSHA256') != completion['planSHA256']):
        raise ValueError('final inventory receipt mismatch')
    plan = json.loads((CAPTURE / 'plan.json').read_bytes())
    commands = plan.get('commands')
    if (not isinstance(commands, list) or len(commands) != 4 or
            any('--fetch' not in command or '--search-cue' in command for command in commands)):
        raise ValueError('expected ordinary fetch carry cue for every run')
    files = json.loads((CAPTURE / 'inventory.json').read_bytes())['files']

    def sealed(path):
        relative = str(path.relative_to(CAPTURE))
        data = path.read_bytes()
        if digest(data) != files.get(relative):
            raise ValueError(f'sealed artifact mismatch: {relative}')
        return data

    worker = json.loads((CAPTURE / 'worker-result.json').read_bytes())
    if worker.get('status') != 'captured_diagnostic_only':
        raise ValueError('capture worker did not complete')
    captures = worker['captures']
    expected = {(seed, arm) for seed in SEEDS for arm in ARMS}
    if {(item['seed'], item['arm']) for item in captures} != expected or len(captures) != 4:
        raise ValueError('incomplete capture results')

    results = {}
    for seed in SEEDS:
        rows, inputs, events = {}, {}, {}
        for arm in ARMS:
            run = CAPTURE / 'runs' / str(seed) / arm / str(seed)
            initial = json.loads(sealed(run / 'initial.json'))
            rows[arm] = [json.loads(line) for line in sealed(run / 'decisions.jsonl').splitlines()]
            events[arm] = [json.loads(line) for line in sealed(run / 'chase.jsonl').splitlines()]
            if len(rows[arm]) != 300:
                raise ValueError('incomplete game')
            ticks = [initial['totalSteps']] + [row['state']['totalSteps'] for row in rows[arm]]
            if len(set(ticks)) != 301 or any(b - a != 10 for a, b in zip(ticks, ticks[1:])):
                raise ValueError('unexpected input-frame tick sequence')
            observations = []
            for tick in ticks:
                rgb = sealed(run / f'actor-{tick}.rgb')
                feedback = sealed(run / f'actor-{tick}.feedback')
                if len(rgb) != 21168 or len(feedback) != 28:
                    raise ValueError('incorrect input size')
                observations.append((rgb, feedback))
            inputs[arm] = observations

        first_action = next((i for i, (a, b) in enumerate(zip(rows['control'], rows['treatment']))
                             if a['action'] != b['action']), None)
        consumed = {arm: next((i for i, row in enumerate(rows[arm])
                               if row['state']['findReturn']['consumedIndex'] >= 0), None)
                    for arm in ARMS}
        # Search-only prefix: no virtual pickup has yet changed the carry cue,
        # and no delivery has caused a same-tick unsaved camera replacement.
        # Action 0 also follows an unsaved replacement after initial capture.
        search_end = min([300] + [i + 1 for i in consumed.values() if i is not None] +
                         [event['step'] for arm in ARMS for event in events[arm]
                          if event['event'] == 'delivery'])
        comparable = range(1, search_end)
        if any(inputs[arm][i][1][24:28] != bytes(4) for arm in ARMS for i in comparable):
            raise ValueError('saved search feedback has unexpected cue')
        first_rgb = next((i for i in comparable if inputs['control'][i][0] != inputs['treatment'][i][0]), None)
        first_feedback = next((i for i in comparable if inputs['control'][i][1] != inputs['treatment'][i][1]), None)
        detections = {arm: [i for i, row in enumerate(rows[arm])
                            if row['state']['case']['perception']['detections']]
                      for arm in ARMS}
        if first_action is None:
            raise ValueError('no differing action in chosen games')
        results[str(seed)] = {
            'firstDifferentActionIndex': first_action,
            'controlAction': rows['control'][first_action]['action'],
            'treatmentAction': rows['treatment'][first_action]['action'],
            'savedInitialRGBEqual': inputs['control'][0][0] == inputs['treatment'][0][0],
            'savedInitialFeedbackEqual': inputs['control'][0][1] == inputs['treatment'][0][1],
            'comparableSearchInputIndices': [1, search_end - 1],
            'firstDifferentComparableRGBInputIndex': first_rgb,
            'firstDifferentComparableFeedbackInputIndex': first_feedback,
            'equalComparableRGBThroughFirstDifferentAction':
                1 <= first_action < search_end and (first_rgb is None or first_rgb > first_action),
            'equalComparableFeedbackThroughFirstDifferentAction':
                1 <= first_action < search_end and (first_feedback is None or first_feedback > first_action),
            'firstPostActionCaseDetectionIndex': {arm: values[0] if values else None
                                                  for arm, values in detections.items()},
            'postActionCaseDetectionRows': {arm: len(values) for arm, values in detections.items()},
            'nextDifferentActionIndex': next((i for i in range(first_action + 1, 300)
                                              if rows['control'][i]['action'] != rows['treatment'][i]['action']), None),
            'firstVirtualConsumptionIndex': consumed,
            'virtualDeliveryEventSteps': {arm: [event['step'] for event in events[arm]
                                               if event['event'] == 'delivery'] for arm in ARMS},
            'truthPoseSeparationMetersAfterAction': {
                str(i): math.dist(rows['control'][i]['state']['pose'][:2],
                                  rows['treatment'][i]['state']['pose'][:2])
                for i in (68, 75, 90, 120, 180, 299)},
        }
    if (CAPTURE / 'completion.json').read_bytes() != completion_bytes:
        raise ValueError('completion changed during analysis')
    return {'completionSHA256': digest(completion_bytes),
            'results': results,
            'scope': ('reused selection scenes; the saved initial observation precedes '
                      'brick placement and is not the observed action-0 input. For the '
                      'search-only prefix after action 0 and before virtual consumption '
                      'or delivery, action i uses the saved post-action i-1 observation. '
                      'Same-tick placement after delivery is not captured. Different '
                      'models have distinct recurrent hidden states. Matched resized RGB '
                      'and feedback are not raw-camera, original-lean-pixel, actor-execution '
                      'or physical-robot attestation.')}


if __name__ == '__main__':
    print(json.dumps(main(), indent=2, sort_keys=True))
