#!/usr/bin/env python3
"""Preview fitting teacher identities from the saved, audited pilot only.

This module does not write an aggregate, verify an outer monitor, authorize
training, or accept a caller-supplied screen result.  The pilot itself is
currently unrun and its own screen explicitly does not authorize training.
"""
import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


pilot = load('qualified_outbound_pilot', ROOT / 'experiments/outbound-teacher-prefix-pilot-v1/audit.py')
mask = load('qualified_outbound_mask', HERE / 'mask.py')


def snapshot():
    """Hash direct local pilot evidence before and after its saved-game audit."""
    root = pilot.plan.OUTPUT
    if root.is_symlink() or not root.is_dir(): raise ValueError('pilot output missing or symlinked')
    paths = [root / 'catalog.json', root / 'launch-plan.json',
             root / 'student/policy/receipt.json', root / 'student/policy/weights.bin',
             root / 'student/policy/policy']
    kernels = root / 'student/policy/kernels'
    if kernels.is_symlink() or not kernels.is_dir(): raise ValueError('invalid pilot policy kernel directory')
    paths.extend(sorted(kernels.iterdir()))
    for row in pilot.plan.design()['rows']:
        paths.extend(root / 'catalog' / str(row['index']) / name
                     for name in ('case.json', 'environment.bin', 'layout.json'))
    optional = []
    for arm in ('student', 'teacher'):
        shard = root / arm
        optional.extend((root / (arm + '.log'), shard / 'policy.log'))
        paths.extend((shard / 'report.json', shard / 'data.bin', shard / 'map.bin',
                      root / ('monitor-' + arm) / 'invocation.json',
                      root / ('monitor-' + arm) / 'supervisor-result.json'))
        for row in pilot.plan.design()['rows']:
            game = shard / ('expert-' + str(row['index']))
            if game.is_symlink() or not game.is_dir() or game.resolve().parent != shard.resolve():
                raise ValueError('invalid or detached pilot episode')
            optional.append(game / 'native.log')
            paths.extend(game / name for name in ('result.json', 'initial.json', 'chase.jsonl', 'decisions.jsonl',
                                                  'scene/case.json', 'scene/environment.bin'))
    result = {}
    for path in optional:
        if path.is_symlink(): raise ValueError('symlinked optional pilot evidence')
        if path.exists(): paths.append(path)
        else: result[str(path)] = None
    for path in paths:
        relative = path.relative_to(root); parent = root
        for name in relative.parts[:-1]:
            parent = parent / name
            if parent.is_symlink() or not parent.is_dir(): raise ValueError('symlinked pilot evidence directory')
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('missing or detached pilot evidence')
        result[str(path)] = mask.sha(path)
    return result


def identities(result):
    """Extract only helpful fitting identities from the recomputed screen."""
    design = pilot.plan.design(); rows = design['rows']; games = result.get('games')
    if (result.get('status') != 'screen_passed' or result.get('trainingAuthorized') is not False or
            not isinstance(games, list) or len(games) != len(rows)):
        raise ValueError('pilot screen did not pass or is incomplete')
    helpful = []; worse = 0
    for expected, item in zip(rows, games):
        if (not isinstance(item, dict) or any(item.get(key) != expected[key] for key in ('index', 'seed', 'fitting')) or
                type(item.get('index')) is not int or type(item.get('seed')) is not int or
                type(item.get('fitting')) is not bool or type(item.get('teacherHelpful')) is not bool or
                type(item.get('teacherWorse')) is not bool or
                (item['teacherHelpful'] and item['teacherWorse'])):
            raise ValueError('pilot screen case identity or flags differ')
        worse += int(item['teacherWorse'])
        if item['teacherHelpful']: helpful.append(expected)
    fit = [row for row in helpful if row['fitting']]
    validation = [row for row in helpful if not row['fitting']]
    limits = design['gate']; layouts = {row['layout'] for row in fit}
    if (len(fit) < limits['minimumHelpfulFittingGames'] or len(layouts) < limits['minimumHelpfulFittingLayouts'] or
            len(validation) < limits['minimumHelpfulValidationGames'] or worse > limits['maximumTeacherWorseGames'] or
            result.get('fittingHelpful') != len(fit) or result.get('fittingHelpfulLayouts') != len(layouts) or
            result.get('validationHelpful') != len(validation) or result.get('teacherWorse') != worse):
        raise ValueError('pilot screen totals or gate differ')
    return [{'episode': row['index'], 'seed': row['seed']} for row in fit]


def frozen_selection():
    """Bind scene exclusions to the actual already-registered selection design."""
    path = pilot.plan.P / 'fresh-policy-selection-plan-v2.json'
    if path.is_symlink() or not path.is_file(): raise ValueError('frozen selection manifest missing')
    before = mask.sha(path); value = json.loads(path.read_text())
    if (value.get('schema') != 'puppybot.fresh-policy-selection-plan.v1' or
            value.get('status') != 'frozen_before_play' or
            value.get('design') != pilot.plan.selection.design() or mask.sha(path) != before):
        raise ValueError('frozen selection design differs')
    return {'path': str(path), 'sha256': before, 'design': value['design']}


def preview():
    """Run the actual pilot audit and return a non-authorizing selection preview."""
    sources = {str(path): mask.sha(path) for path in (Path(__file__), HERE / 'mask.py')}
    frozen = frozen_selection()
    inputs = pilot.plan.preflight()
    before = snapshot()
    result = pilot.audit()
    helpful = identities(result)
    rows = {row['index']: row for row in pilot.plan.design()['rows']}
    selection_scenes = {(row['layout'], row['variant']) for task in frozen['design']['tasks']
                        for row in task['rows']}
    selected = []; overlap_excluded = []
    teacher = pilot.plan.OUTPUT / 'teacher'
    for item in helpful:
        row = rows[item['episode']]
        if (row['layout'], row['variant']) in selection_scenes:
            overlap_excluded.append({'episode': item['episode'], 'seed': item['seed'],
                                     'layout': row['layout'], 'variant': row['variant'],
                                     'reason': 'same_layout_variant_as_current_selection'})
            continue
        game = teacher / ('expert-' + str(item['episode']))
        evidence = {name: before[str(game / name)] for name in
                    ('result.json', 'initial.json', 'chase.jsonl', 'decisions.jsonl')}
        selected.append({**item, 'evidence': evidence})
    helpful_indices = {item['episode'] for item in helpful}
    other_excluded = [{'episode': row['index'], 'seed': row['seed'], 'layout': row['layout'],
                       'variant': row['variant'],
                       'reason': 'pilot_validation' if not row['fitting'] else 'not_helpful_in_pilot_screen'}
                      for row in rows.values() if not row['fitting'] or row['index'] not in helpful_indices]
    post_filter_layouts = {rows[item['episode']]['layout'] for item in selected}
    limits = pilot.plan.design()['gate']
    if (len(selected) < limits['minimumHelpfulFittingGames'] or
            len(post_filter_layouts) < limits['minimumHelpfulFittingLayouts']):
        raise ValueError('post-hoc exact-scene filter leaves insufficient fitting examples')
    after = snapshot()
    if (before != after or pilot.plan.preflight() != inputs or frozen_selection() != frozen or
            sources != {str(path): mask.sha(path) for path in (Path(__file__), HERE / 'mask.py')}):
        raise ValueError('pilot evidence or recorded inputs changed during audit')
    entry = {'dataSHA256': before[str(teacher / 'data.bin')],
             'reportSHA256': before[str(teacher / 'report.json')], 'episodes': selected}
    encoded = json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return {'status': 'selection_preview_only', 'outerMonitorVerified': False,
            'usableForTraining': False, 'selection': {str(teacher): entry},
            'screenSHA256': hashlib.sha256(encoded).hexdigest(), 'evidenceSHA256': before,
            'selectorSourcesSHA256': sources, 'frozenSelectionManifestSHA256': frozen['sha256'],
            'exactSceneOverlapExcluded': overlap_excluded, 'otherExcluded': other_excluded,
            'postFilterFittingGames': len(selected), 'postFilterFittingLayouts': len(post_filter_layouts),
            'sharedLayoutFamilies': sorted({row['layout'] for row in rows.values()} &
                                           {row[0] for row in selection_scenes}),
            'scope': ('recomputed local pilot audit only; monitor, preserve-shard provenance, '
                      'training/held-out qualification and execution are not verified; '
                      'exact-scene filtering is post-hoc and does not establish distinct geometry')}


if __name__ == '__main__':
    raise SystemExit('Preview requires a completed audited pilot; this tool never authorizes training.')
