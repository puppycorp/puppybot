#!/usr/bin/env python3
"""Classify already-audited back-and-forth actions by saved post-action phase.

This is a descriptive selection diagnostic, not a policy or physical test.
"""
import collections
import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / 'build/flex/sim/levels-v2/pitch82/fresh-policy-selection-v3'
METRICS = ROOT / 'experiments/outbound-five-selection-metrics-v1/metrics.py'


def load_metrics():
    spec = importlib.util.spec_from_file_location('selection_metrics', METRICS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def audit():
    metrics = load_metrics()
    report_bytes = (OUTPUT / 'report.json').read_bytes()
    report = json.loads(report_bytes)
    result = {}
    for level in range(1, 6):
        task = f'L{level}'
        result[task] = {}
        for arm in ('control', 'treatment'):
            counts = collections.Counter()
            for game in metrics.load_games(OUTPUT / task, arm):
                rows = game['rows']
                marked = metrics.windows.marks(rows, game['events'][0]['robot'], True)
                for index in marked:
                    state = rows[index]['state']
                    counts[state['findReturn']['phase']] += 1
                    counts['blocked'] += bool(state['blocked'])
            total = sum(counts[phase] for phase in ('search', 'return', 'delivered', 'docked'))
            if total != report['inclusiveMetrics'][task][arm]['inclusiveBackForthActions']:
                raise ValueError('phase counts disagree with inclusive selection report')
            result[task][arm] = {'actions': total, 'search': counts['search'],
                                 'return': counts['return'], 'delivered': counts['delivered'],
                                 'docked': counts['docked'], 'blocked': counts['blocked']}
    if (OUTPUT / 'report.json').read_bytes() != report_bytes:
        raise ValueError('selection report changed during audit')
    return {'reportSHA256': hashlib.sha256(report_bytes).hexdigest(), 'levels': result,
            'scope': ('training-family saved virtual games; phase and blocked are post-action '
                      'state, not cause, physical behavior, or independent execution proof')}


if __name__ == '__main__':
    print(json.dumps(audit(), indent=2, sort_keys=True))
