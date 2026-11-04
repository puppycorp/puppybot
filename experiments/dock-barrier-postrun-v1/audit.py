#!/usr/bin/env python3
"""Re-audit a completed barrier trial without modifying its pinned evidence."""
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


original = load('original_barrier_audit', ROOT / 'experiments/dock-barrier-rendered-v1/audit.py')
monitor = load('original_barrier_monitor', ROOT / 'experiments/dock-barrier-rendered-v1/monitor.py')


def barrier(trace):
    events = []; prior = None; previous_step = None; previous_time = None; offset = None; seen = False; reason = None
    with Path(trace).open() as stream:
        for line in stream:
            row = json.loads(line); step = row.get('totalSteps'); time = row.get('timeMs'); discovery = row.get('discovery')
            if (type(step) is not int or step < 0 or type(row.get('step')) is not int or
                    row['step'] != step or type(time) is not int or time < 0):
                reason = 'invalid_tick_identity'; break
            if offset is None: offset = time - step * 20
            if time - step * 20 != offset or (previous_time is not None and time <= previous_time):
                reason = 'invalid_clock_offset_or_reversal'; break
            if previous_step is not None and step != previous_step + 1:
                reason = 'missing_or_duplicate_tick'; break
            previous_step = step; previous_time = time
            if discovery is None and not seen: continue
            if not isinstance(discovery, dict): reason = 'missing_discovery'; break
            seen = True; state = discovery.get('workerBarrier'); map_frame = discovery.get('mapFrameId')
            if not isinstance(state, dict) or set(state) != original.KEYS or any(type(state[k]) is not int for k in original.KEYS):
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
    if reason is None:
        if previous_step is None: reason = 'empty_trace'
        elif not seen: reason = 'discovery_not_observed'
        elif not events: reason = 'no_worker_wait_observed'
    return {'status': 'complete' if reason is None else 'censored', 'censorReason': reason,
            'clockOffsetMs': offset, 'waits': events,
            'scope': 'constant simulated clock offset checked against each tick; wallMs is worker submission-to-completion elapsed wall time'}


def audit(output):
    output = Path(output).absolute(); trial = output / 'trial'
    completion_path = output / 'completion.json'; worker_path = output / 'worker-result.json'
    completion = json.loads(completion_path.read_text()); worker = json.loads(worker_path.read_text())
    if (completion.get('status') != 'diagnostic_only' or
            completion.get('finalWorkerSHA256') != original.base.sha(worker_path) or
            completion.get('auditSHA256') != original.base.sha(trial / 'audit.json') or
            worker.get('inventory') != monitor.base.inventory(trial)):
        raise ValueError('completed trial receipt or evidence differs')
    saved = json.loads((trial / 'audit.json').read_text())
    if original.audit(trial) != saved: raise ValueError('original saved audit differs from independent rerun')
    original_barrier = original.barrier
    try:
        original.barrier = barrier
        corrected = original.audit(trial)
    finally:
        original.barrier = original_barrier
    if (completion.get('finalWorkerSHA256') != original.base.sha(worker_path) or
            completion.get('auditSHA256') != original.base.sha(trial / 'audit.json') or
            worker.get('inventory') != monitor.base.inventory(trial)):
        raise ValueError('trial evidence changed during postrun audit')
    return {'status': 'postrun_diagnostic_only', 'originalSavedAudit': saved, 'correctedAudit': corrected,
            'scope': 'separate read-only analysis of one completed simulated selection case; original censor and evidence preserved; no physical or real-time claim'}


if __name__ == '__main__':
    if len(sys.argv) != 2: raise SystemExit(__doc__)
    try: print(json.dumps(audit(sys.argv[1]), sort_keys=True))
    except (OSError, ValueError, KeyError, TypeError) as error: raise SystemExit('Invalid postrun audit: ' + str(error))
