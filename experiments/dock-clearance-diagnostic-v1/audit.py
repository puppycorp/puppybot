#!/usr/bin/env python3
"""Separate release-stage and circular-viewpoint evidence in a saved trial."""
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location('clearance_elevation_audit', ROOT / 'experiments/dock-survey-elevation-trial-v1/audit.py')
elevation = importlib.util.module_from_spec(spec); spec.loader.exec_module(elevation)
base = elevation.base
base.__file__ = str(HERE / 'audit.py')
original_rows = elevation.rows


def rows(path):
    result = original_rows(path)
    if Path(path).name == 'trace.jsonl':
        for row in result:
            row.get('case', {}).get('dockVision', {}).pop('clearanceDiagnostic', None)
    return result


base.rows = rows
KEYS = ('stageRuns', 'stageCandidates', 'stageNear', 'stageClear', 'stageFloorObstacle',
        'stageObservedFloor', 'stageBoxMargin', 'stageTargetExclusion', 'stageOther',
        'dropClearancePass', 'dropClearanceFail', 'routePass', 'routeFail')


def clearance(trace, directory):
    previous = None
    with Path(trace).open() as stream:
        for line in stream:
            state = json.loads(line).get('case', {}).get('dockVision', {}).get('clearanceDiagnostic')
            if not isinstance(state, dict) or set(state) != set(KEYS): raise ValueError('missing clearance counts')
            if any(type(state[k]) is not int or state[k] < 0 for k in KEYS): raise ValueError('invalid clearance counts')
            if previous is not None and any(state[k] < previous[k] for k in KEYS): raise ValueError('clearance count decreased')
            if state['stageCandidates'] != state['stageRuns'] * 2304: raise ValueError('incomplete stage enumeration')
            if sum(state[k] for k in KEYS[2:9]) != state['stageCandidates']: raise ValueError('stage accounting differs')
            if state['dropClearancePass'] + state['dropClearanceFail'] > state['stageClear']: raise ValueError('too many drop checks')
            if state['routePass'] + state['routeFail'] != state['dropClearancePass']: raise ValueError('route accounting differs')
            previous = state
    if previous is None: raise ValueError('empty clearance trace')
    circular = {str(i): 0 for i in range(7)}
    for path in Path(directory).glob('search-*-candidate-*.json'):
        row = json.loads(path.read_text()); detail = row.get('clearanceDetail'); reason = row.get('reason')
        if type(detail) is not int or detail not in range(7): raise ValueError('invalid viewpoint clearance detail')
        if (reason == 3) != (detail != 0): raise ValueError('viewpoint reason and detail disagree')
        circular[str(detail)] += 1
    return {'stage': previous, 'circularViewpointClearanceDetailCounts': circular,
            'scope': 'first failed check only; observed floor combines out-of-map, unknown and occupied; drop clearance combines IK and neighborhood'}


def audit(root):
    root = Path(root).absolute(); result = elevation.audit(root)
    if all(arm.get('status') == 'complete' for arm in result['arms']):
        result['clearanceDiagnostic'] = {name: clearance(root / name / 'run/trace.jsonl', root / name / 'diagnostic')
                                         for name in base.ARMS}
    else:
        result['clearanceDiagnostic'] = {'status': 'censored_incomplete_arm'}
    return result


if __name__ == '__main__':
    if len(sys.argv) != 2: raise SystemExit(__doc__)
    try: print(json.dumps(audit(sys.argv[1]), sort_keys=True))
    except (OSError, ValueError, KeyError, TypeError) as error: raise SystemExit('Invalid trial: ' + str(error))
