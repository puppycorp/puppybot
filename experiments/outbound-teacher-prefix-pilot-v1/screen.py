#!/usr/bin/env python3
"""Conservative quality screen over already-audited matched pilot records.

The screen does not itself validate simulator files or authorize training.
Callers must first use a separately reviewed saved-game and label auditor.
"""
import importlib.util
from pathlib import Path


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('outbound_pilot_design', HERE / 'plan.py')
plan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plan)


def pickup(value):
    if value is None:
        return None
    if type(value) is not int or not 1 <= value <= plan.HORIZON:
        raise ValueError('invalid first-consumption action')
    return value


def evaluate(records):
    expected = plan.design()['rows']; limits = plan.design()['gate']
    if not isinstance(records, list) or len(records) != len(expected):
        raise ValueError('all matched games, including misses, are required')
    helpful = []; worse = []; output = []
    for record, row in zip(records, expected):
        if not isinstance(record, dict) or any(record.get(key) != row[key] for key in ('index', 'seed', 'layout', 'fitting')):
            raise ValueError('pilot case identity or order differs')
        if (any(type(record.get(key)) is not int for key in ('index', 'seed', 'layout')) or
                type(record.get('fitting')) is not bool or
                'studentFirstConsumptionAction' not in record or
                'teacherFirstConsumptionAction' not in record):
            raise ValueError('missing or mistyped case or consumption evidence')
        for key in ('sceneMatched', 'initialMatched', 'completeHorizon', 'labelsVerified'):
            if record.get(key) is not True:
                raise ValueError('pilot evidence is incomplete: ' + key)
        student = pickup(record.get('studentFirstConsumptionAction'))
        teacher = pickup(record.get('teacherFirstConsumptionAction'))
        flagged = record.get('teacherOutboundBackForthActions')
        if (type(flagged) is not int or flagged < 0 or
                (teacher is None and flagged > plan.HORIZON) or
                (teacher is not None and flagged >= teacher)):
            raise ValueError('invalid outbound back-and-forth count')
        # A missing student pickup is right-censored at 300, not an assumed
        # later action. Restrict teacher to <=200 so it is at least 100 actions
        # earlier than the observed horizon in that case.
        useful = (teacher is not None and teacher <= limits['teacherPickupNoLaterThan'] and
                  (student is None or student - teacher >= limits['minimumEarlierActions']) and
                  flagged <= limits['maximumTeacherOutboundBackForthActions'])
        regressed = student is not None and (teacher is None or teacher > student)
        if useful: helpful.append(row)
        if regressed: worse.append(row)
        output.append({'index': row['index'], 'seed': row['seed'], 'fitting': row['fitting'],
                       'teacherHelpful': useful, 'teacherWorse': regressed})
    fit = [row for row in helpful if row['fitting']]
    valid = [row for row in helpful if not row['fitting']]
    passed = (len(fit) >= limits['minimumHelpfulFittingGames'] and
              len({row['layout'] for row in fit}) >= limits['minimumHelpfulFittingLayouts'] and
              len(valid) >= limits['minimumHelpfulValidationGames'] and
              len(worse) <= limits['maximumTeacherWorseGames'])
    return {'status': 'screen_passed' if passed else 'screen_failed',
            'fittingHelpful': len(fit), 'fittingHelpfulLayouts': len({row['layout'] for row in fit}),
            'validationHelpful': len(valid), 'teacherWorse': len(worse), 'games': output,
            'trainingAuthorized': False,
            'scope': 'quality arithmetic over caller-supplied audited records only; not saved-file verification, a model gain or a held-out result'}


if __name__ == '__main__':
    raise SystemExit('Disabled: call only after a separate saved-game and label audit.')
