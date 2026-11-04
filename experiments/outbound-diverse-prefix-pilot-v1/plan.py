#!/usr/bin/env python3
"""Bound the diverse-room outbound pilot before any collection or training."""
import importlib.util
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SCENES = ROOT / 'build/flex/sim/levels-v1/diverse-scenes'
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
OUTPUT = P / 'outbound-diverse-prefix-pilot-v1'
CATALOG = OUTPUT / 'catalog'
SELECTION = P / 'fresh-policy-selection-v2/inputs.json'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prior = load('diverse_outbound_prior_plan', ROOT / 'experiments/outbound-teacher-prefix-pilot-v1/plan.py')
original_design = prior.design
original_preflight = prior.preflight
original_scene_links = prior.selection.scene_links
prior.OUTPUT = OUTPUT
prior.CATALOG = CATALOG
prior.SCENES = SCENES


def design():
    result = original_design()
    specs = [(layout, variant, True) for layout in (27, 29, 31) for variant in (8, 9, 10)]
    specs += [(layout, 11, False) for layout in (33, 35, 37)]
    result['schema'] = 'puppybot.outbound-diverse-prefix-pilot-design.v1'
    result['gate']['backForthMetric'] = 'pose20-prefix-bounded-final-inclusive-v1'
    result['rows'] = [{'index': i, 'seed': prior.BASE_SEED + i, 'layout': layout,
                       'variant': variant, 'fitting': fitting,
                       'scene': str(SCENES / str(layout) / str(variant))}
                      for i, (layout, variant, fitting) in enumerate(specs)]
    result['scope'] = ('12 matched scenes from six previously used diverse layouts; '
                       'no unseen-scene, held-out, physical, or promotion claim')
    return result


def scene_links(row):
    return original_scene_links(row, scenes=SCENES)


def check_selection_separation(scenes):
    """Compare bytes with all current selection scenes, not semantic similarity."""
    payload = json.loads(SELECTION.read_text())
    tasks = payload.get('design', {}).get('tasks')
    if not isinstance(tasks, list) or len(tasks) != 5:
        raise ValueError('current selection design is missing')
    selected = [row for task in tasks for row in task.get('rows', [])]
    if len(selected) != 160:
        raise ValueError('current selection does not have 160 rows')
    evidence = [{'scene': row['scene'],
                 'caseSHA256': prior.register.base.sha(Path(row['scene']) / 'case.json'),
                 'environmentSHA256': prior.register.base.sha(Path(row['scene']) / 'environment.bin')}
                for row in selected]
    case_hashes = {row['caseSHA256'] for row in evidence}
    env_hashes = {row['environmentSHA256'] for row in evidence}
    for row in scenes:
        if row['files']['case.json'] in case_hashes or row['files']['environment.bin'] in env_hashes:
            raise ValueError('candidate exactly overlaps the current selection')
    return {'selectionManifestSHA256': prior.register.base.sha(SELECTION),
            'selectionSceneHashesSHA256': hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest(),
            'selectionRows': len(selected), 'caseHashOverlap': False, 'environmentHashOverlap': False,
            'scope': 'exact source-file bytes only; not semantic or ancestry independence'}


def preflight():
    selection_before = prior.register.base.sha(SELECTION)
    result = original_preflight()
    separation = check_selection_separation(result['scenes'])
    if separation['selectionManifestSHA256'] != selection_before:
        raise ValueError('current selection manifest changed during check')
    files = result['sourceFiles']
    local = [HERE / name for name in ('plan.py', 'run.py', 'monitor.py', 'audit.py')]
    local += [ROOT / 'experiments/l5-teacher-rollin-pilot-v1/monitor.py',
              ROOT / 'experiments/diverse-teacher-level-swap-v1/audit.py',
              ROOT / 'experiments/final-loop-window-v1/audit.py']
    for path in local:
        if path.is_symlink() or not path.is_file():
            raise ValueError('pilot source missing or symlinked')
        files[str(path)] = prior.register.base.sha(path)
    files[str(SELECTION)] = selection_before
    result['selectionSeparation'] = separation
    result['scope'] = ('read-only local inputs; disjoint from current selection by case and environment bytes; '
                       'named-root history skips symlinks and cannot establish semantic novelty or model ancestry')
    return result


prior.design = design
prior.selection.scene_links = scene_links
prior.preflight = preflight
command = prior.command
environment = prior.environment
prepare_catalog = prior.prepare_catalog
verify_catalog = prior.verify_catalog
freeze = prior.freeze


if __name__ == '__main__':
    print(json.dumps(preflight(), sort_keys=True, indent=2, allow_nan=False))
