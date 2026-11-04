#!/usr/bin/env python3
"""Audit matched floor-refresh trial without crediting a partial recovery."""
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


prior = load('floor_retry_previous_audit', ROOT / 'experiments/observed-footprint-matched-v1/audit.py')
barrier = load('floor_retry_barrier', HERE / 'barrier.py')
prior.original.base.__file__ = str(HERE / 'audit.py')
prior.original.barrier = barrier.barrier
old_rows = prior.original.base.rows


def rows(path):
    result = old_rows(path)
    if Path(path).name == 'trace.jsonl':
        # Strip only the candidate's opt-in counters in comparative checks;
        # independently audit those counters from raw trace rows below.
        for row in result:
            row.get('case', {}).get('boxSearch', {}).pop('floorRetry', None)
    return result


prior.original.base.rows = rows


def retry_report(trace, enabled):
    previous = None; attempt_tick = None; mapping_start = None; mapping_end = None
    with Path(trace).open() as stream:
        for line in stream:
            row = json.loads(line); case = row.get('case', {}); box = case.get('boxSearch', {})
            state = box.get('floorRetry') if isinstance(box, dict) else None
            if not enabled:
                if state is not None: raise ValueError('disabled retry metadata present')
                continue
            if not isinstance(state, dict) or set(state) != {'attempted', 'mapping'} or any(type(v) is not bool for v in state.values()):
                raise ValueError('invalid retry metadata')
            if state['mapping'] and not state['attempted']: raise ValueError('mapping without retry')
            if previous is not None and previous['attempted'] and not state['attempted']:
                raise ValueError('retry attempt unexpectedly reset')
            if state['attempted'] and attempt_tick is None: attempt_tick = row['step']
            if state['mapping'] and mapping_start is None: mapping_start = row['step']
            if previous and previous['mapping'] and not state['mapping']:
                if mapping_end is not None: raise ValueError('multiple retry mappings')
                mapping_end = row['step']
            if mapping_end is not None and state['mapping']: raise ValueError('retry mapping restarted')
            previous = state
    if enabled and previous is None: raise ValueError('retry metadata absent')
    return {'enabled': enabled, 'attemptTick': attempt_tick, 'mappingStartTick': mapping_start,
            'mappingEndTick': mapping_end, 'mappingActiveAtEnd': previous['mapping'] if previous else False,
            'scope': 'simulator counters only; no camera, motor or physical safety attestation'}


def audit(root):
    root = Path(root).absolute(); result = prior.audit(root)
    if all(arm.get('status') == 'complete' for arm in result['arms']):
        result['floorRetry'] = {name: retry_report(root / name / 'run/trace.jsonl', name == 'candidate-search')
                                for name in prior.original.base.ARMS}
    else:
        result['floorRetry'] = {'status': 'censored_incomplete_arm'}
    result['mechanismEligible'] = False
    result['mechanismCensorReason'] = 'floor_map_and_stage_effect_not_independently_attested'
    result['scope'] = ('one known simulated selection case; same binary, high survey, barrier and corrected '
                       'footprint in all arms; retry enabled only in candidate; recorded retry is not delivery '
                       'or physical safety proof; worker wall time is separate')
    return result


if __name__ == '__main__':
    if len(sys.argv) != 2: raise SystemExit(__doc__)
    try: print(json.dumps(audit(sys.argv[1]), sort_keys=True))
    except (OSError, ValueError, KeyError, TypeError) as error: raise SystemExit('Invalid trial: ' + str(error))
