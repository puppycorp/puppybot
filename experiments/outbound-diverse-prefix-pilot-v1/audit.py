#!/usr/bin/env python3
"""Audit the diverse pilot through the unchanged outbound shard verifier."""
import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


plan = load('diverse_pilot_audit_plan', HERE / 'plan.py')
prior = load('diverse_pilot_prior_audit', ROOT / 'experiments/outbound-teacher-prefix-pilot-v1/audit.py')
inclusive = load('diverse_pilot_prefix_window', ROOT / 'experiments/final-loop-window-v1/audit.py')
prior.plan = plan.prior
prior.screen.plan = plan.prior
original_audit_arm = prior.audit_arm


def prefix_reversal_steps(rows, start, first_consumption):
    """Count the union of 20-action windows strictly before consumption."""
    if first_consumption is None:
        prefix = len(rows)
    elif type(first_consumption) is int and 1 <= first_consumption <= len(rows):
        prefix = first_consumption - 1
    else:
        raise ValueError('invalid first consumption action')
    # Include the final complete window; later actions and poses cannot mark
    # prefix actions merely because a window crosses the pickup boundary.
    return len(inclusive.marks(rows[:prefix], start, True))


def audit_arm(root, arm, inputs):
    """Retain prior shard checks, then replace its post-pickup-contaminated score."""
    games, labels = original_audit_arm(root, arm, inputs)
    for index, game in enumerate(games):
        events = Path(root) / f'expert-{index}' / 'chase.jsonl'
        with events.open() as stream:
            start = json.loads(stream.readline())
        first = game['first']
        if start.get('event') != 'start' or prior.outbound.first_consumption(game['rows']) != first:
            raise ValueError('initial event or first consumption changed during audit')
        game['before'] = prefix_reversal_steps(game['rows'], start['robot'], first)
    return games, labels


prior.audit_arm = audit_arm


def audit():
    result = prior.audit(plan.OUTPUT)
    if result.get('status') not in ('screen_passed', 'screen_failed') or result.get('trainingAuthorized') is not False:
        raise ValueError('unexpected pilot screen result')
    result['outboundBackForthMetric'] = 'pose20-prefix-bounded-final-inclusive-v1'
    result['scope'] = ('matched saved local outputs from previously used diverse scenes; '
                       'no execution attestation, model improvement, training, held-out or physical claim')
    return result


if __name__ == '__main__':
    print(json.dumps(audit(), sort_keys=True, indent=2, allow_nan=False))
