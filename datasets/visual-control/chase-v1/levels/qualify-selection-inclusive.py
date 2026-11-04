#!/usr/bin/env python3
"""Fail-closed inclusive-loop helper for future selection qualification.

The selection qualification entry point remains disabled. This helper cannot
create a qualification receipt or enable a held-out run.
"""
import importlib.util
from pathlib import Path


HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


legacy = load('selection_qualification_legacy', HERE / 'qualify-selection.py')
inclusive = load('selection_qualification_inclusive_heldout', HERE / 'audit-heldout-inclusive.py')


def validate_games(games):
    for seed, (result, rows, start, _) in games.items():
        count = result.get('backForthSteps')
        if (result.get('backForthMetric') != inclusive.METRIC or type(count) is not int or
                not 0 <= count <= len(rows) or count != inclusive.backforth_steps(rows, start['robot'])):
            raise ValueError(f'missing or invalid inclusive back-and-forth metric for selection seed {seed}')
    return games


def strict_games(root, model, level, selection):
    # Preserve legacy score verification, but reconstruct the v2 count and
    # require an explicit version on every game before it may be qualified.
    return validate_games(legacy.strict_games(root, model, level, selection, inclusive))


if __name__ == '__main__':
    raise SystemExit('Selection qualification is disabled; this helper does not enable it.')
