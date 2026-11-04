#!/usr/bin/env python3
"""Read-only preparation gate for already supplied candidate scene files.

This does not generate scenes or prove complete ancestry or binary provenance.
"""
import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
GENERATOR = ROOT / 'datasets/visual-control/expanded-rooms-v1/generate-diverse.flex'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = load('selection_preparation_guard', HERE / 'guard.py')
design = load('selection_preparation_design', HERE / 'design.py')
transform = load('selection_preparation_transform', HERE / 'transform.py')


def prepare(candidate_root, generator_source, generator_binary, heldout_manifest, heldout_sha,
            prior_seeds, prior_layouts, prior_cases, prior_environments):
    """Construct a candidate manifest in memory; never launch the generator."""
    if (not isinstance(prior_cases, (list, tuple, set, frozenset)) or
            not isinstance(prior_environments, (list, tuple, set, frozenset)) or
            not prior_cases or not prior_environments or
            any(not isinstance(value, str) or not guard.HASH.fullmatch(value)
                for value in (*prior_cases, *prior_environments))):
        raise ValueError('explicit prior case and environment hash inventories required')
    prior_cases, prior_environments = set(prior_cases), set(prior_environments)
    source = guard.read_snapshot(generator_source, 4 * 1024 * 1024)
    binary = guard.read_snapshot(generator_binary, 64 * 1024 * 1024)
    original = guard.read_snapshot(GENERATOR, 4 * 1024 * 1024)
    if source.decode() != transform.transform(original.decode()):
        raise ValueError('generator source is not the reviewed transform')
    reserved = guard.load_manifest(heldout_manifest, heldout_sha, 'heldout')
    heldout_cases = {row['caseSHA256'] for row in reserved.values()}
    heldout_envs = {row['environmentSHA256'] for row in reserved.values()}
    rows, layouts = [], []
    root = Path(candidate_root)
    for identity in design.rows():
        level, index, layout_id = identity['level'], identity['index'], identity['layoutId']
        relative = f'generated/{layout_id}/{identity["variant"]}'
        scene = root / relative
        layout_data = guard.read_snapshot(scene / 'layout.json', 4 * 1024 * 1024)
        case = guard.read_snapshot(scene / 'case.json', 32 * 1024 * 1024)
        environment = guard.read_snapshot(scene / 'environment.bin', 32 * 1024 * 1024)
        metadata, parsed_case = json.loads(layout_data), json.loads(case)
        if (not isinstance(metadata, dict) or not isinstance(parsed_case, dict) or
                metadata.get('generator') != 'diverse-v1' or type(metadata.get('layoutId')) is not int or
                metadata['layoutId'] != layout_id or metadata.get('fit') is not False or
                metadata.get('selectionOnly') is not True or metadata.get('reservedHeldOut', False) is not False or
                metadata.get('wideHeading', False) is not False or
                not isinstance(metadata.get('rooms'), list) or len(metadata['rooms']) != 1 + layout_id % 2 or
                not isinstance(metadata.get('obstacles'), list) or len(metadata['obstacles']) != 1 or
                not environment.startswith(b'PBENV001') or len(environment) < 256):
            raise ValueError('candidate scene metadata or environment invalid')
        guard.start_pose(metadata.get('startPose'))
        case_sha, env_sha = guard.digest(case), guard.digest(environment)
        if case_sha in heldout_cases or env_sha in heldout_envs:
            raise ValueError('candidate exact bytes overlap reserved heldout')
        if case_sha in prior_cases or env_sha in prior_environments:
            raise ValueError('candidate exact bytes overlap supplied prior history')
        row = {'level': level, 'index': index, 'layoutId': layout_id, 'seed': identity['seed'],
               'scene': relative, 'caseSHA256': case_sha, 'environmentSHA256': env_sha,
               'layoutSHA256': guard.digest(layout_data), 'startPose': metadata['startPose']}
        rows.append(row); layouts.append(metadata)
    for level in range(1, 6):
        indices = range((level - 1) * 32, level * 32)
        if (len({rows[i]['environmentSHA256'] for i in indices}) != 32 or
                len({guard.start_pose(rows[i]['startPose']) for i in indices}) != 32 or
                len({design.geometry(layouts[i]) for i in indices}) != 32):
            raise ValueError('candidate level has duplicate environment, start pose or exact metadata geometry')
    history = design.compare_history(prior_seeds, prior_layouts, layouts)
    history['priorCaseHashes'] = len(prior_cases)
    history['priorEnvironmentHashes'] = len(prior_environments)
    history['priorCaseInventorySHA256'] = guard.digest(json.dumps(sorted(prior_cases), separators=(',', ':')).encode())
    history['priorEnvironmentInventorySHA256'] = guard.digest(json.dumps(sorted(prior_environments), separators=(',', ':')).encode())
    # Recheck files whose bytes certify the roles and identity. A registered
    # launcher must repeat scene snapshot/hash checks immediately before use.
    for row in rows:
        scene = root / row['scene']
        for name, key, limit in (('layout.json', 'layoutSHA256', 4 * 1024 * 1024),
                                 ('case.json', 'caseSHA256', 32 * 1024 * 1024),
                                 ('environment.bin', 'environmentSHA256', 32 * 1024 * 1024)):
            if guard.digest(guard.read_snapshot(scene / name, limit)) != row[key]:
                raise ValueError('candidate scene changed during preparation')
    if (guard.read_snapshot(generator_source, 4 * 1024 * 1024) != source or
            guard.read_snapshot(generator_binary, 64 * 1024 * 1024) != binary or
            guard.read_snapshot(GENERATOR, 4 * 1024 * 1024) != original or
            guard.load_manifest(heldout_manifest, heldout_sha, 'heldout') != reserved):
        raise ValueError('preparation inputs changed')
    return {'status': 'selection_not_evaluated', 'task': 'virtual-fetch', 'gamesPerLevel': 32,
            'generatorSourceSHA256': guard.digest(source), 'generatorSHA256': guard.digest(binary),
            'rows': rows, 'history': history,
            'scope': ('supplied records and metadata geometry only; source-to-binary provenance, metadata-to-world '
                      'geometry, complete ancestry and near-overlap are unproven')}


if __name__ == '__main__':
    raise SystemExit('Disabled: no candidate scenes generated or registered by this module.')
