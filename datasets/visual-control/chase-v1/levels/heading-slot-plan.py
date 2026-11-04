#!/usr/bin/env python3
"""Authorize only the four historical L5 correction slots, not arbitrary offsets.

The derived order is the exact historical experiment-35 ordering: all fitting
games by source, then all validation games by source. This is an input plan,
not proof that the historical aggregate itself was constructed from it.
"""
import json
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[4]
P = PROJECT / 'build/flex/sim/levels-v2/pitch82'
B = P / 'search-dagger-4workers'
M = P / 'search-dagger-l35-4workers'
PREVIOUS = P / 'search-dagger-l4-matched'


def fixed_shards():
    ordered = [P / f'kturn-L{level}/shard-{shard}' for level in range(4) for shard in range(6)]
    ordered += [PREVIOUS / f'dagger-L4/shard-{shard}' for shard in range(4)]
    ordered += [P / f'kturn-L4/shard-{shard}' for shard in range(4, 8)]
    ordered += [P / f'kturn-L5/shard-{shard}' for shard in range(8)]
    ordered += [B / f'dagger-L3/shard-{shard}' for shard in range(4)]
    ordered += [M / f'dagger-L5/shard-{shard}' for shard in range(4)]
    return ordered


def derive(ordered, replaced):
    if len(ordered) != 48 or len(replaced) != 4 or ordered[-4:] != replaced or len({p.resolve() for p in ordered}) != 48:
        raise ValueError('unexpected historical shard ordering')
    shards = []
    for path in ordered:
        r = json.loads((path / 'report.json').read_text())
        n, fit = r.get('episodes'), r.get('trainingEpisodes')
        if (r.get('complete') is not True or type(n) is not int or type(fit) is not int or not 1 <= fit < n
                or r.get('validationEpisodes') != n - fit or r.get('sequenceLength') != 300):
            raise ValueError(f'invalid historical shard report: {path}')
        if path in replaced and (n, fit, r.get('studentDriven')) != (32, 30, True):
            raise ValueError('historical L5 replacement shard differs')
        shards.append((path, n, fit))
    total = sum(n for _, n, _ in shards); fitting = sum(fit for _, _, fit in shards)
    if (total, fitting) != (1024, 928): raise ValueError('historical aggregate dimensions differ')
    fitting_order = [(path, i) for path, n, fit in shards for i in range(fit)]
    validation_order = [(path, i) for path, n, fit in shards for i in range(fit, n)]
    order = fitting_order + validation_order
    slots = [i for i, (path, _) in enumerate(order) if path in replaced]
    expected = list(range(808, 928)) + list(range(1016, 1024))
    if slots != expected: raise ValueError('historical replacement slots differ')
    return {'status': 'slot_plan_only', 'totalGames': total, 'fittingGames': fitting,
            'fitOffset': 808, 'validationOffset': 1016, 'replacedSlots': slots,
            'unaffectedGames': 896, 'scope': 'derived from historical shard reports; aggregate provenance must be checked separately'}


def fixed_plan():
    paths = fixed_shards()
    return derive(paths, paths[-4:])


if __name__ == '__main__':
    print(json.dumps(fixed_plan(), sort_keys=True))
