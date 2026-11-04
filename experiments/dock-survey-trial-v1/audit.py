#!/usr/bin/env python3
"""Audit a simulated survey recording without claiming a causal improvement."""
import importlib.util
import json
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location('survey_search_audit', ROOT / 'experiments/physical-search-fallback-trial-v1/audit.py')
base = importlib.util.module_from_spec(spec); spec.loader.exec_module(base)
base.__file__ = str(HERE / 'audit.py')
original_protocol = base.protocol
original_rows = base.rows


def protocol(run, _enabled):
    return original_protocol(run, True)


base.protocol = protocol


def rows(path):
    result = original_rows(path)
    if Path(path).name == 'trace.jsonl':
        # The opt-in counter is instrumentation, not a scene or start-state
        # difference. Its original values are checked separately below.
        for row in result:
            row.get('case', {}).get('dockVision', {}).pop('surveyDiagnostic', None)
    return result


base.rows = rows


def diagnostic(path, trace):
    path = Path(path); images = {}; cameras = {}; plans = []; plan_ids = set(); unexpected = []
    for item in sorted(path.iterdir()):
        if item.is_symlink() or not item.is_file(): raise ValueError('unsafe diagnostic entry')
        image = re.fullmatch(r'survey-(\d+)\.rgb', item.name)
        camera = re.fullmatch(r'survey-(\d+)\.sensor\.camera\.json', item.name)
        plan = re.fullmatch(r'search-(\d+)-candidate-(\d+)\.json', item.name)
        if image:
            if item.stat().st_size != 640 * 480 * 3: raise ValueError('invalid RGB length')
            number = int(image.group(1))
            if number in images: raise ValueError('duplicate survey image identity')
            images[number] = item
        elif camera:
            row = json.loads(item.read_text())
            calibration = row.get('intrinsics'); vectors = [row.get(key) for key in ('eyeM', 'forward', 'right', 'down')]
            if (row.get('schema') != 'puppybot.camera.v1' or row.get('view') != 'tcp' or
                    type(row.get('frameId')) is not int or type(row.get('capturedMs')) is not int or
                    row.get('width') != 640 or row.get('height') != 480 or not isinstance(calibration, dict) or
                    any(type(calibration.get(key)) not in (int, float) or not math.isfinite(calibration[key])
                        for key in ('fx', 'fy', 'cx', 'cy')) or calibration['fx'] <= 0 or calibration['fy'] <= 0 or
                    any(not isinstance(v, list) or len(v) != 3 or
                        any(type(x) not in (int, float) or not math.isfinite(x) for x in v) for v in vectors)):
                raise ValueError('invalid camera metadata')
            number = int(camera.group(1))
            if number in cameras: raise ValueError('duplicate camera identity')
            cameras[number] = row
        elif plan:
            row = json.loads(item.read_text()); goal = row.get('goal')
            identity = (int(plan.group(1)), int(plan.group(2)))
            if (row.get('schema') != 'puppybot.dock-viewpoint-diagnostic.v1' or
                    row.get('search') != identity[0] or row.get('index') != identity[1] or
                    identity[0] < 1 or identity[1] not in range(36) or identity in plan_ids or
                    type(row.get('step')) is not int or type(row.get('expanded')) is not int or
                    type(row.get('planned')) is not bool or type(row.get('reason')) is not int or
                    row['reason'] not in range(7) or row['planned'] != (row['reason'] == 0) or
                    not isinstance(goal, list) or len(goal) != 3 or
                    any(type(x) not in (int, float) or not math.isfinite(x) for x in goal)):
                raise ValueError('invalid viewpoint record')
            plans.append(row); plan_ids.add(identity)
        else: unexpected.append(item.name)
    if unexpected or set(images) != set(cameras): raise ValueError('unexpected or incomplete image files')
    count = plan_count = errors = None; steps = set()
    with Path(trace).open() as stream:
        for line in stream:
            row = json.loads(line); step = row.get('step'); steps.add(step)
            state = row.get('case', {}).get('dockVision', {}).get('surveyDiagnostic')
            if not isinstance(state, dict) or set(state) != {'count', 'planCount', 'writeErrors'}:
                raise ValueError('missing survey diagnostic trace')
            if (type(state['count']) is not int or type(state['planCount']) is not int or type(state['writeErrors']) is not int or
                    state['count'] < (count or 0) or state['planCount'] < (plan_count or 0) or state['writeErrors'] < (errors or 0)):
                raise ValueError('invalid survey counters')
            count, plan_count, errors = state['count'], state['planCount'], state['writeErrors']
    if count is None or count != len(images) or plan_count != len(plans) or errors:
        raise ValueError('missing diagnostic files or recorded write failure')
    if any(row['frameId'] not in steps for row in cameras.values()) or any(row['step'] not in steps for row in plans):
        raise ValueError('diagnostic frame or plan step missing from trace')
    reasons = {str(code): sum(1 for row in plans if row['reason'] == code) for code in range(7)}
    return {'observationEligible': bool(images), 'surveyImages': len(images), 'frameIds': [cameras[i]['frameId'] for i in sorted(cameras)],
            'viewpointPlans': len(plans), 'reasonCounts': reasons, 'writeErrors': errors,
            'scope': 'local simulated RGB, estimated camera calibration and planner state; no physical or causal claim'}


def audit(root):
    root = Path(root).absolute(); result = base.audit(root)
    if all(arm.get('status') == 'complete' for arm in result['arms']):
        for name in ('baseline', 'candidate-disabled'):
            if (root / name / 'diagnostic').exists(): raise ValueError('disabled arm emitted diagnostic files')
        result['surveyDiagnostic'] = diagnostic(root / 'candidate-search/diagnostic',
                                                root / 'candidate-search/run/trace.jsonl')
    else:
        result['surveyDiagnostic'] = {'status': 'censored_incomplete_arm'}
    result['scope'] = ('same simulator binary and selection case; dock confirmation enabled in every arm; '
                       'recording enabled only in third arm; local evidence, no hardware or causal claim')
    return result


if __name__ == '__main__':
    if len(sys.argv) != 2: raise SystemExit(__doc__)
    try: print(json.dumps(audit(sys.argv[1]), sort_keys=True))
    except (OSError, ValueError, KeyError, TypeError) as error: raise SystemExit('Invalid trial: ' + str(error))
