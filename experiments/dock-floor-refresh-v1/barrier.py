#!/usr/bin/env python3
"""Audit worker barriers, allowing only evidenced retry-local map changes."""
import json
from pathlib import Path


KEYS = {'waits', 'lastFrameId', 'lastWorkerCompleteTick', 'lastWallMs', 'failures'}


def states(row):
    discovery = row.get('discovery')
    case = row.get('case', {})
    box = case.get('boxSearch', {}) if isinstance(case, dict) else {}
    pickup = discovery.get('pickup', {}) if isinstance(discovery, dict) else {}
    return discovery, box, pickup


def barrier(trace):
    events = []; switches = []; prior = None; previous_step = None; previous_time = None
    previous_row = None; offset = None; seen = False; reason = None; saved_global = None
    with Path(trace).open() as stream:
        for line in stream:
            row = json.loads(line); step = row.get('totalSteps'); time = row.get('timeMs')
            discovery, box, pickup = states(row)
            if (type(step) is not int or step < 0 or type(row.get('step')) is not int or
                    row['step'] != step or type(time) is not int or time < 0):
                reason = 'invalid_tick_identity'; break
            if offset is None: offset = time - step * 20
            if time - step * 20 != offset or (previous_time is not None and time <= previous_time):
                reason = 'invalid_clock_offset_or_reversal'; break
            if previous_step is not None and step != previous_step + 1:
                reason = 'missing_or_duplicate_tick'; break
            previous_step = step; previous_time = time
            if discovery is None and not seen: previous_row = row; continue
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
                    if map_frame != previous_map:
                        _, old_box, old_pickup = states(previous_row)
                        retry = box.get('floorRetry') if isinstance(box, dict) else None
                        old_retry = old_box.get('floorRetry') if isinstance(old_box, dict) else None
                        entering = (map_frame == 0 and previous_map > 0 and saved_global is None and
                            isinstance(retry, dict) and retry == {'attempted': True, 'mapping': True} and
                            isinstance(old_retry, dict) and old_retry == {'attempted': False, 'mapping': False} and
                            isinstance(pickup, dict) and pickup.get('mappingHeldFloor') is True and
                            pickup.get('localDockMap') is True and isinstance(old_pickup, dict) and
                            old_pickup.get('localDockMap') is False and type(box.get('mapRefreshes')) is int and
                            type(old_box.get('mapRefreshes')) is int and box['mapRefreshes'] == old_box['mapRefreshes'] + 1)
                        restoring = (saved_global is not None and map_frame == saved_global and
                            isinstance(pickup, dict) and pickup.get('localDockMap') is False and
                            pickup.get('mappingHeldFloor') is False and isinstance(old_pickup, dict) and
                            old_pickup.get('localDockMap') is True)
                        if entering:
                            saved_global = previous_map; switches.append({'kind': 'enter_retry_local_map', 'step': step, 'savedFrameId': previous_map})
                        elif restoring:
                            switches.append({'kind': 'restore_transit_map', 'step': step, 'restoredFrameId': map_frame}); saved_global = None
                        else:
                            reason = 'map_changed_without_observed_wait'; break
                else:
                    frame = state['lastFrameId']; tick = state['lastWorkerCompleteTick']; wall = state['lastWallMs']
                    if frame <= previous_map or frame <= prior['lastFrameId'] or frame > tick or tick != step or wall < 0 or wall >= 15000:
                        reason = 'invalid_or_unobserved_completion'; break
                    applied = map_frame == frame and previous_map != frame
                    events.append({'frameId': frame, 'workerCompleteTick': tick, 'wallMs': wall,
                                   'mapApplied': applied, 'mapFrameId': map_frame,
                                   'mapAppliedTick': step if applied else None})
                    if not applied: reason = 'completion_without_observed_map_application'; break
            prior = dict(state); previous_map = map_frame; previous_row = row
    if reason is None:
        if previous_step is None: reason = 'empty_trace'
        elif not seen: reason = 'discovery_not_observed'
        elif not events: reason = 'no_worker_wait_observed'
    return {'status': 'complete' if reason is None else 'censored', 'censorReason': reason,
            'clockOffsetMs': offset, 'waits': events, 'mapSwitches': switches,
            'scope': 'constant simulated clock offset and evidenced retry-local map transitions checked; wallMs is worker submission-to-completion elapsed wall time'}
