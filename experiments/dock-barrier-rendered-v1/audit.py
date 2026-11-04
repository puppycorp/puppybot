#!/usr/bin/env python3
"""Audit a saved rendered barrier trial without equating completion with application."""
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location('barrier_clearance_audit', ROOT / 'experiments/dock-clearance-diagnostic-v1/audit.py')
clearance = importlib.util.module_from_spec(spec); spec.loader.exec_module(clearance)
base = clearance.base
base.__file__ = str(HERE / 'audit.py')
original_rows = clearance.rows
KEYS = {'waits', 'lastFrameId', 'lastWorkerCompleteTick', 'lastWallMs', 'failures'}


def rows(path):
    result = original_rows(path)
    if Path(path).name == 'trace.jsonl':
        for row in result:
            row.get('discovery', {}).pop('workerBarrier', None)
    return result


base.rows = rows


def barrier(trace):
    events = []; prior = None; previous_step = None; seen = False; reason = None
    with Path(trace).open() as stream:
        for line in stream:
            row = json.loads(line); step = row.get('totalSteps'); discovery = row.get('discovery')
            if (type(step) is not int or step < 0 or type(row.get('step')) is not int or
                    row['step'] != step or type(row.get('timeMs')) is not int or row['timeMs'] != step * 20):
                reason = 'invalid_tick_identity'; break
            if previous_step is not None and step != previous_step + 1:
                reason = 'missing_or_duplicate_tick'; break
            previous_step = step
            if discovery is None and not seen: continue
            if not isinstance(discovery, dict): reason = 'missing_discovery'; break
            seen = True; state = discovery.get('workerBarrier'); map_frame = discovery.get('mapFrameId')
            if not isinstance(state, dict) or set(state) != KEYS or any(type(state[k]) is not int for k in KEYS):
                reason = 'missing_or_invalid_barrier'; break
            if type(map_frame) is not int or map_frame < 0:
                reason = 'missing_or_invalid_map_frame'; break
            if state['waits'] < 0 or state['failures'] < 0:
                reason = 'invalid_counters'; break
            if state['failures']:
                reason = 'worker_barrier_failure'; break
            if prior is None:
                if (map_frame != 0 or state != {'waits': 0, 'lastFrameId': -1, 'lastWorkerCompleteTick': -1,
                                                'lastWallMs': -1, 'failures': 0}):
                    reason = 'unobserved_prior_wait'; break
            else:
                delta = state['waits'] - prior['waits']
                if delta not in (0, 1): reason = 'unobserved_or_decreasing_waits'; break
                if not delta:
                    if state != prior: reason = 'changed_record_without_wait'; break
                    if map_frame != previous_map: reason = 'map_changed_without_observed_wait'; break
                else:
                    frame = state['lastFrameId']; tick = state['lastWorkerCompleteTick']; wall = state['lastWallMs']
                    if frame <= previous_map or frame > tick or tick != step or wall < 0 or wall >= 15000:
                        reason = 'invalid_or_unobserved_completion'; break
                    applied = map_frame == frame and previous_map != frame
                    events.append({'frameId': frame, 'workerCompleteTick': tick, 'wallMs': wall,
                                   'mapApplied': applied, 'mapFrameId': map_frame,
                                   'mapAppliedTick': step if applied else None})
                    if not applied: reason = 'completion_without_observed_map_application'; break
            prior = dict(state); previous_map = map_frame
    if previous_step is None: reason = 'empty_trace'
    elif not seen: reason = 'discovery_not_observed'
    elif reason is None and not events: reason = 'no_worker_wait_observed'
    return {'status': 'complete' if reason is None else 'censored', 'censorReason': reason,
            'waits': events, 'scope': 'wallMs is worker submission-to-completion wall time, separate from simulated time; map application is inferred from the validated map frame transition'}


def barrier_comparison(root, include_candidate=False):
    names = base.ARMS if include_candidate else ('baseline', 'candidate-disabled')
    reports = {}
    for name in names:
        try: reports[name] = barrier(Path(root) / name / 'run/trace.jsonl')
        except (OSError, ValueError, TypeError):
            reports[name] = {'status': 'censored', 'censorReason': 'missing_or_invalid_trace', 'waits': []}
    controls = [reports[name] for name in ('baseline', 'candidate-disabled')]
    if any(item['status'] != 'complete' for item in controls):
        matched = False; reason = 'control_barrier_trace_censored'
    else:
        def identity(item):
            return [(event['frameId'], event['workerCompleteTick'], event['mapAppliedTick']) for event in item['waits']]
        matched = identity(controls[0]) == identity(controls[1])
        reason = None if matched else 'control_map_application_sequence_mismatch'
        if reason is None and include_candidate and reports['candidate-search']['status'] != 'complete':
            reason = 'candidate_barrier_trace_censored'
    return {'status': 'complete' if reason is None else 'censored', 'censorReason': reason,
            'matchedControlMapApplications': matched, 'arms': reports,
            'scope': 'two barrier-enabled controls; worker elapsed wall latencies may differ and are not simulated time; full completion also requires the protocol and endpoint audit'}


def audit(root):
    root = Path(root).absolute(); result = clearance.audit(root)
    if all(arm.get('status') == 'complete' for arm in result['arms']):
        result['workerBarrierDiagnostic'] = barrier_comparison(root, include_candidate=True)
    else:
        result['workerBarrierDiagnostic'] = {'status': 'censored', 'censorReason': 'incomplete_arm'}
    barrier_result = result['workerBarrierDiagnostic']
    if barrier_result['status'] != 'complete':
        result['comparisonEligible'] = False
        result['mechanismEligible'] = False
        if result.get('censorReason') is None: result['censorReason'] = barrier_result['censorReason']
        if result.get('mechanismCensorReason') is None: result['mechanismCensorReason'] = barrier_result['censorReason']
    result['scope'] += '; worker elapsed wall time is separate from simulated ticks; no physical or real-time claim'
    return result


if __name__ == '__main__':
    if len(sys.argv) != 2: raise SystemExit(__doc__)
    try: print(json.dumps(audit(sys.argv[1]), sort_keys=True))
    except (OSError, ValueError, KeyError, TypeError) as error: raise SystemExit('Invalid trial: ' + str(error))
