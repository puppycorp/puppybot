#!/usr/bin/env python3
"""Prospective fresh-selection contract; does not create scenes or launch games."""
import hashlib
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


design = load('fresh_selection_design', ROOT / 'experiments/selection-role-prototype-v1/design.py')


def contract():
    rows = design.rows()
    expected = [(level, index, 290 + index if level <= 3 else 291 + 2 * index,
                 index % 16, 1800000000 + 100 * level + index)
                for level in range(1, 6) for index in range(32)]
    if [(r['level'], r['index'], r['layoutId'], r['variant'], r['seed']) for r in rows] != expected:
        raise ValueError('selection identity mapping differs from prospective contract')
    if len({row['seed'] for row in rows}) != 160 or any(226 <= row['layoutId'] <= 289 for row in rows):
        raise ValueError('selection seeds duplicate or overlap reserved layout range')
    return {
        'schema': 'puppybot.fresh-selection-contract.v1',
        'status': 'design_only_not_registered',
        'scope': ('prospective development selection only; no scenes or games created; '
                  'not a held-out, promotion, execution-attestation or physical result'),
        'arms': [
            {'name': 'parent', 'model': 'student-s1', 'policy': 'single-neural', 'teacherIntervention': False},
            {'name': 'control', 'model': 'fixed-control', 'policy': 'single-neural', 'teacherIntervention': False},
            {'name': 'treatment', 'model': 'fixed-treatment', 'policy': 'single-neural', 'teacherIntervention': False},
            {'name': 'teacher', 'model': None, 'policy': 'exploring-reference', 'teacherIntervention': False},
        ],
        'rows': rows,
        'conditions': {'levels': [1, 2, 3, 4, 5], 'gamesPerLevelPerArm': 32,
                       'actionsPerGame': 300, 'simulatedSecondsPerGame': 60,
                       'cameraPitchDegrees': 82, 'odometry': 'wheel-drift',
                       'sameSceneAndSeedAcrossArms': True},
        'metrics': {
            'deliveryGameMinimum': {'numerator': 29, 'denominator': 32, 'eachLevel': True},
            'firstPickupLevel3Minimum': {'numerator': 29, 'denominator': 32},
            'doorwayLevel4Minimum': {'numerator': 4, 'denominator': 5,
                                     'unresolvedPlacementsIncluded': True},
            'backForth': {'windowActions': 20, 'maxShareExclusive': .02,
                          'positionMetresExclusive': .25, 'headingDegreesExclusive': 45,
                          'minimumDirectionReversals': 4, 'includeTerminalWindow': True,
                          'savedScoreVersion': 'pose20-final-inclusive-v2'},
            'longSearch': {'windowActions': 100, 'positionMetresExclusive': .3,
                           'headingDegreesExclusive': 45, 'includesStationary': True,
                           'separateDiagnostic': True},
            'rate': 'report deliveries per simulated minute by level; compare each student to teacher',
            'reliability': ('report all per-level outcomes and seed-paired wins/losses; conservatively require '
                            'treatment delivered-game counts at least the original parent and extra-epoch control'),
            'incomplete': 'retain and report all missing, failed or timed-out games; no pass on incomplete evidence',
        },
        'preconditions': [
            'fixed full-epoch pair completion, both model packages and full audit independently verified',
            'selection-only generator binary reproducibly built and bound to reviewed source and execution',
            'scene metadata checked against world collider boxes and separately against rendered geometry',
            'known model ancestry, scene, seed and geometry inventories explicitly enumerated and pinned',
            'selection and held-out role protection integrated into the actual ingestion path',
            'pinned protected scene manifest sealed before any selection game',
            'evaluation argv, runtime, model, scene bytes and actor boundary records pinned and audited',
            'guarded process and disk/GPU limits, clean supervisors and final inventory',
        ],
        'limits': ['current native ingestion guard is not integrated',
                   'held-out manifest has not been created and must not be fabricated',
                   'prior ancestry and semantic scene independence are not fully established',
                   'virtual consumption and delivery do not establish physical manipulation'],
    }


def digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


if __name__ == '__main__':
    value = contract()
    print(json.dumps({'sha256': digest(value), 'contract': value}, indent=2, sort_keys=True))
