#!/usr/bin/env python3
"""Audit the staged same-binary footprint comparison, including clock offset."""
import importlib.util
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


original = load('footprint_original_barrier_audit', ROOT / 'experiments/dock-barrier-rendered-v1/audit.py')
clock = load('footprint_offset_barrier_audit', ROOT / 'experiments/dock-barrier-postrun-v1/audit.py')
original.base.__file__ = str(HERE / 'audit.py')
original.barrier = clock.barrier
old_high = original.clearance.elevation.high_summary


def high_summary(trace, enabled, frame_times):
    # This comparison enables the same survey in every arm.
    return old_high(trace, True, frame_times)


original.clearance.elevation.high_summary = high_summary


def audit(root):
    result = original.audit(root)
    # The inherited mechanism flag referred to survey elevation, not the
    # tested floor guard; without guard-call instrumentation it is not evidence
    # that the changed guard was reached or changed a particular decision.
    result['mechanismEligible'] = False
    result['mechanismCensorReason'] = 'guard_effect_not_instrumented'
    result['scope'] = ('same simulator binary and one known selection case; high survey and worker barrier enabled '
                       'in all arms; only the observed-floor guard flag differs; '
                       'saved records do not attest execution or physical safety; worker wall time is separate')
    return result


if __name__ == '__main__':
    if len(sys.argv) != 2: raise SystemExit(__doc__)
    try: print(json.dumps(audit(sys.argv[1]), sort_keys=True))
    except (OSError, ValueError, KeyError, TypeError) as error: raise SystemExit('Invalid trial: ' + str(error))
