#!/usr/bin/env python3
"""Audit matched visual recovery, including independent manipulation outcomes."""
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


base = load('visual_matched_base_audit', ROOT / 'experiments/physical-search-fallback-trial-v1/audit.py')
visual = load('visual_matched_individual_audit', ROOT / 'experiments/visual-search-recovery-v1/audit.py')
base.__file__ = str(HERE / 'audit.py')


def protocol(run, enabled):
    # All arms have search enabled. Only the third has visual transfer enabled.
    summary = visual.audit_run(run, visual_enabled=enabled)
    trigger = summary['visualTriggerAction']
    return visual.adapted_protocol()(run, True, 90, 1499, trigger is not None,
                                     trigger if trigger is not None else -1)


base.protocol = protocol


def audit(root):
    root = Path(root).absolute(); result = base.audit(root)
    if all(arm.get('status') == 'complete' for arm in result['arms']):
        runs = {name: visual.audit_run(root / name / 'run', visual_enabled=name == 'candidate-search')
                for name in base.ARMS}
        candidate = runs['candidate-search']
        for arm in result['arms']:
            manipulation = arm.get('manipulation')
            if (not isinstance(manipulation, dict) or
                    type(manipulation.get('traceMeetsManipulationCriteria')) is not bool or
                    not isinstance(manipulation.get('captures'), list) or
                    not isinstance(manipulation.get('releases'), list)):
                raise ValueError('incomplete manipulation audit')
        matched_trigger = None
        if candidate['visualTriggerAction'] is not None:
            # The actor prefix contains observations before each policy action,
            # but the candidate does not call the actor on its trigger image.
            # Compare that separately saved image with the *next* actor input in
            # each disabled control; missing images are a censored comparison.
            trigger = root / 'candidate-search/run/visual-trigger.rgb'
            sequence = candidate['triggerObservationSequence']
            expected = trigger.read_bytes()
            matched_trigger = True
            for name in base.ARMS[:2]:
                image = root / name / 'run/actors' / f'actor-{sequence}.rgb'
                if (image.is_symlink() or not image.is_file() or image.read_bytes() != expected):
                    matched_trigger = False
        # A target-at-transfer handoff is a valid comparison outcome, even
        # though the older fallback audit called it search_not_started.
        if (result['matchedSavedPrefix'] and matched_trigger is not False and
                (candidate['searchStarted'] or candidate['handoff'])):
            result['comparisonEligible'] = True; result['censorReason'] = None
        if matched_trigger is False:
            result['comparisonEligible'] = False; result['censorReason'] = 'trigger_frame_mismatch_or_missing'
        result['visualRuns'] = runs
        result['matchedTriggerFrame'] = matched_trigger
        result['outcomes'] = {arm['arm']: {
            'completedSimulatedManipulation': arm['manipulation'].get('traceMeetsManipulationCriteria') is True,
            'collectorTerminal': runs[arm['arm']]['collectorTerminal'],
            'unfinishedAtPollLimit': bool((runs[arm['arm']]['searchStarted'] or runs[arm['arm']]['handoff']) and
                                         not runs[arm['arm']]['collectorTerminal']),
        } for arm in result['arms']}
        result['mechanismEligible'] = bool(result['comparisonEligible'] and candidate['visualTriggerAction'] is not None)
        result['mechanismCensorReason'] = (None if result['mechanismEligible'] else
            result['censorReason'] if not result['comparisonEligible'] else 'visual_trigger_not_observed')
    else:
        result['mechanismEligible'] = False; result['mechanismCensorReason'] = 'incomplete_arm'
    result['scope'] = ('same simulator and client, one previously used selection case; '
                       'first two arms disable visual transfer, third enables it; '
                       'simulated manipulation truth is not physical pickup or execution attestation')
    return result


if __name__ == '__main__':
    if len(sys.argv) != 2: raise SystemExit(__doc__)
    try: print(json.dumps(audit(sys.argv[1]), sort_keys=True))
    except (OSError, ValueError, KeyError, TypeError) as error: raise SystemExit('Invalid trial: ' + str(error))
