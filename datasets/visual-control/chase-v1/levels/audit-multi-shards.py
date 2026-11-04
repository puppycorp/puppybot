#!/usr/bin/env python3
"""Audit mixed teacher/student shards with different source policies.

Usage: audit-multi-shards.py --expect-games N --expect-teacher-shards N
    --expect-student-shards N --teacher SHARD... --student-group MODEL LEVEL SHARD...
Repeat --student-group for each distinct model and level. The ordered paths
must be the exact order passed to map-aggregate and mask-stuck.py. This checks
source provenance and train/validation scene/start overlap, but it does not
prove pretrained model ancestry or executable identity before old collections.
"""
import argparse
import hashlib
import importlib.util
import json
import re
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selection-base', type=int, default=7800000)
    parser.add_argument('--expect-games', type=int, required=True)
    parser.add_argument('--expect-teacher-shards', type=int, required=True)
    parser.add_argument('--expect-student-shards', type=int, required=True)
    parser.add_argument('--teacher', nargs='+', type=Path, required=True)
    parser.add_argument('--student-group', nargs='+', action='append', required=True,
                        help='MODEL LEVEL SHARD [SHARD ...]')
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('audit_shards', Path(__file__).with_name('audit-shards.py'))
    audit_shards = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit_shards)
    if len(args.teacher) != args.expect_teacher_shards:
        raise ValueError('teacher shard count mismatch')
    groups = []
    for group in args.student_group:
        if len(group) < 3 or group[1] not in ('0', '1', '2', '3', '4', '5'):
            raise ValueError('each student group requires MODEL LEVEL SHARD...')
        groups.append((Path(group[0]), int(group[1]), [Path(p) for p in group[2:]]))
    if sum(len(group[2]) for group in groups) != args.expect_student_shards:
        raise ValueError('student shard count mismatch')
    paths = args.teacher + [p for _, _, shards in groups for p in shards]
    if len({p.resolve() for p in paths}) != len(paths):
        raise ValueError('duplicate source shard')
    seen, total, fitting, by_level = set(), 0, 0, {}
    provenance = hashlib.sha256()
    train_scenes, validation_scenes = set(), set()
    sources = [(p, False, None, None, None) for p in args.teacher]
    for model, level, shards in groups:
        expected = audit_shards.digest(model / 'weights.bin')
        sources.extend((p, True, expected, model, level) for p in shards)
    for shard, student, expected, model, expected_level in sources:
        report = json.loads((shard / 'report.json').read_text())
        declarations = {'teacherUsesCameraDetections': True, 'teacherUsesReferenceGeometryForWallsOnly': True,
                        'teacherUsesTargetCoordinates': False, 'actorUsesReferencePose': False,
                        'actorUsesTargetCoordinates': False}
        if any(report.get(key) is not value for key, value in declarations.items()):
            raise ValueError(f'missing or conflicting provenance declarations: {shard}')
        match = re.search(r'-L([0-5])$', shard.parent.name)
        if not match:
            raise ValueError(f'cannot infer source level: {shard}')
        level = int(match.group(1))
        if expected_level is not None and level != expected_level:
            raise ValueError(f'wrong student source level: {shard}')
        n, fit = audit_shards.audit(shard, student, expected, model, args.selection_base, seen, provenance)
        for i in range(n):
            game = shard / f'expert-{i}'
            result = json.loads((game / 'result.json').read_text())
            if result.get('level') != level or result.get('game') != 'fetch':
                raise ValueError(f'wrong game or level: {game}')
            if level in (4, 5) and result.get('levelPlacement') != ('doorway drill' if level == 4 else 'other room'):
                raise ValueError(f'wrong level placement: {game}')
            h = hashlib.sha256()
            for name in ('case.json', 'environment.bin'):
                h.update((game / 'scene' / name).read_bytes())
            start = json.loads((game / 'chase.jsonl').read_text().splitlines()[0])
            h.update(json.dumps(start, sort_keys=True, separators=(',', ':')).encode())
            (train_scenes if i < fit else validation_scenes).add(h.digest())
        total += n
        fitting += fit
        key = f'{"student" if student else "teacher"}-L{level}'
        by_level[key] = by_level.get(key, 0) + n
    if total != args.expect_games or total > 1024:
        raise ValueError('total source games differ from the expected count or exceed 1024')
    if train_scenes & validation_scenes:
        raise ValueError('identical recorded scene/start appears in both training and validation')
    print(json.dumps({'status': 'passed', 'games': total, 'trainingGames': fitting,
                      'validationGames': total - fitting, 'gamesBySourceLevel': by_level,
                      'orderedShards': [str(p) for p in paths], 'sceneStartSHA256': provenance.hexdigest(),
                      'selectionSeeds': [args.selection_base, args.selection_base + 31],
                      'scope': 'source shard checks, self-reported input declarations and identical scene/start split only; pretrained ancestry and old simulator binaries not established'}, sort_keys=True))


if __name__ == '__main__':
    main()
