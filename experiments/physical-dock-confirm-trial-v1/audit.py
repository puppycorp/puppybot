#!/usr/bin/env python3
"""Audit same-binary search arms using the existing protocol checker."""
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location('dock_search_audit', ROOT / 'experiments/physical-search-fallback-trial-v1/audit.py')
base = importlib.util.module_from_spec(spec); spec.loader.exec_module(base)
base.__file__ = str(HERE / 'audit.py')
original_protocol = base.protocol


def protocol(run, _enabled):
    # All three arms enable search; only the third enables dock confirmation.
    return original_protocol(run, True)


base.protocol = protocol


def trace_rows(path):
    with Path(path).open() as stream:
        for line in stream: yield json.loads(line)


def dock_trace(path, enabled):
    """Summarize recorded confirmation; frame IDs and commands are simulator state."""
    runs = []; preactivation = []; previous_run = 0; previous_state = None; first_box = None; last_box = False; rows = 0
    for row in trace_rows(path):
        rows += 1; step = row.get('step'); discovery = row.get('discovery')
        if type(step) is not int or not isinstance(discovery, dict): raise ValueError('missing discovery trace')
        pickup = discovery.get('pickup'); dock = row.get('case', {}).get('dockVision')
        if (not isinstance(pickup, dict) or type(pickup.get('boxLearned')) is not bool or
                not isinstance(dock, dict) or type(dock.get('valid')) is not bool or type(dock.get('frameId')) is not int):
            raise ValueError('missing dock or box trace')
        last_box = pickup['boxLearned']
        if last_box and first_box is None: first_box = step
        state = discovery.get('dockConfirm')
        if not enabled:
            if state is not None: raise ValueError('disabled arm exposed confirmation state')
            continue
        if not isinstance(state, dict) or set(state) != {'active', 'runs', 'attempts', 'reason'}:
            raise ValueError('missing confirmation state')
        active = state['active']; count = state['runs']; attempts = state['attempts']; reason = state['reason']
        if (type(active) is not bool or type(count) is not int or not previous_run <= count <= 3 or
                count > previous_run + 1 or type(attempts) is not int or not 0 <= attempts <= 4 or
                type(reason) is not int or not 0 <= reason <= 6 or (active and count == 0)):
            raise ValueError('invalid confirmation state')
        if count > previous_run:
            runs.append({'number': count, 'firstStep': step, 'activeSteps': 0, 'maxAttempts': 0,
                         'observedFreshValidFrames': [], 'lastReason': 0, 'lastStep': step})
        previous_run = count
        changed = state != previous_state; previous_state = state.copy()
        if not count:
            if changed and reason: preactivation.append({'step': step, 'reason': reason})
            continue
        record = runs[-1]
        if active or changed: record['lastStep'] = step; record['lastReason'] = reason
        record['maxAttempts'] = max(record['maxAttempts'], attempts)
        if active:
            drive = row.get('controller', {}).get('drive', {})
            if drive.get('leftSpeed') != 0 or drive.get('rightSpeed') != 0:
                raise ValueError('nonzero commanded drive while confirming')
            record['activeSteps'] += 1
        frame = dock.get('frameId')
        if (type(frame) is int and frame == step and dock.get('valid') is True and
                frame not in record['observedFreshValidFrames'] and (active or changed)):
            record['observedFreshValidFrames'].append(frame)
    if not rows: raise ValueError('empty dock trace')
    return {'enabled': enabled, 'runs': runs, 'preactivationFailures': preactivation,
            'firstBoxLearnedStep': first_box, 'boxLearnedAtEnd': last_box,
            'scope': 'saved simulator state; zero commands are not physical stop or independent camera evidence'}


def audit(root):
    result = base.audit(root)
    if all(arm.get('status') == 'complete' for arm in result['arms']):
        traces = {name: dock_trace(Path(root) / name / 'run/trace.jsonl', name == 'candidate-search')
                  for name in base.ARMS}
        candidate = traces['candidate-search']; runs = candidate['runs']
        exercised = bool(runs and any(run['activeSteps'] for run in runs))
        result['dockTrace'] = traces
        result['mechanismEligible'] = bool(result['comparisonEligible'] and exercised)
        result['mechanismCensorReason'] = (None if result['mechanismEligible'] else
            result['censorReason'] if not result['comparisonEligible'] else 'confirmation_not_observed_active')
    else:
        result['mechanismEligible'] = False
        result['mechanismCensorReason'] = 'incomplete_arm'
    result['scope'] = ('same simulator binary, same previously used selection case; '
                       'first two arms repeat search with confirmation disabled, third enables it; '
                       'saved records are not execution attestation or physical robot evidence')
    return result


if __name__ == '__main__':
    if len(sys.argv) != 2: raise SystemExit(__doc__)
    try: print(json.dumps(audit(sys.argv[1]), sort_keys=True))
    except (OSError, ValueError, KeyError, TypeError) as error: raise SystemExit('Invalid trial: ' + str(error))
