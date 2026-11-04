#!/usr/bin/env python3
"""Audit completed chase shards before mixing them into a training dataset.

Usage: audit-shards.py [--selection-base N] [--student-weights SHA256 --student-model DIR]
                       [--teacher SHARD ...] [--student SHARD ...]
Pass each source exactly once. This reads all source data and decisions, and
should not be run concurrently with GPU collection on a resource-limited host.
The audit proves properties of the named sources, not prior model ancestry.
"""
import argparse
import hashlib
import json
import re
import struct
from pathlib import Path


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def audit(shard, student, expected_weights, model, selection, seen, provenance):
    report = json.loads((shard / 'report.json').read_text())
    if report.get('complete') is not True or report.get('studentDriven') is not student:
        raise ValueError(f'{shard}: incomplete report or wrong driver')
    if report.get('teacher') != 'exploring fetch teacher':
        raise ValueError(f'{shard}: unexpected teacher')
    if student:
        snapshot = shard / 'policy'
        receipt = json.loads((snapshot / 'receipt.json').read_text())
        if (snapshot / 'receipt.json').read_bytes() != (model / 'receipt.json').read_bytes():
            raise ValueError(f'{shard}: frozen policy receipt differs from current source model')
        if receipt.get('weightsSHA256') != expected_weights or digest(snapshot / 'weights.bin') != expected_weights:
            raise ValueError(f'{shard}: frozen policy weights mismatch')
        if digest(model / 'weights.bin') != expected_weights:
            raise ValueError(f'{model}: source weights mismatch')
        if digest(snapshot / 'policy') != receipt.get('binarySHA256') or digest(model / 'policy') != receipt.get('binarySHA256'):
            raise ValueError(f'{shard}: frozen policy binary mismatch')
        kernels = receipt.get('kernels')
        if not isinstance(kernels, dict) or not kernels:
            raise ValueError(f'{shard}: missing frozen kernel manifest')
        for name, expected in kernels.items():
            if Path(name).name != name or digest(snapshot / 'kernels' / name) != expected or digest(model / 'kernels' / name) != expected:
                raise ValueError(f'{shard}: frozen policy kernel mismatch: {name}')
        provenance.update((snapshot / 'receipt.json').read_bytes())
    n, fit, horizon = report['episodes'], report['trainingEpisodes'], report['sequenceLength']
    if horizon != 300 or fit < 1 or report['validationEpisodes'] != n - fit or fit >= n:
        raise ValueError(f'{shard}: invalid episode split or horizon')
    for name, magic, rowbytes, key in (('data.bin', b'PVDATA01', 21212, 'dataSHA256'),
                                       ('map.bin', b'PVMAP001', 144, 'mapSHA256')):
        file = shard / name
        with file.open('rb') as stream:
            header = stream.read(32)
        if len(header) != 32 or header[:8] != magic or struct.unpack('<qqq', header[8:]) != (n, fit, horizon):
            raise ValueError(f'{file}: invalid header')
        if file.stat().st_size != 32 + n * horizon * rowbytes or digest(file) != report.get(key):
            raise ValueError(f'{file}: size or report checksum mismatch')
    log_paths = [shard.with_suffix('.log'), shard / 'policy.log']
    for i in range(n):
        directory = shard / f'expert-{i}'
        result = json.loads((directory / 'result.json').read_text())
        seed = report['seed'] + i
        if seed in seen or selection <= seed < selection + 32:
            raise ValueError(f'{directory}: duplicate or selection seed {seed}')
        seen.add(seed)
        if result.get('seed') != seed or result.get('steps') != horizon or result.get('blackout') is not False:
            raise ValueError(f'{directory}: unexpected seed, horizon or blackout')
        if student and result.get('policyWeightsSHA256') != expected_weights:
            raise ValueError(f'{directory}: unexpected student weights')
        with (directory / 'decisions.jsonl').open('rb') as stream:
            if sum(1 for _ in stream) != horizon:
                raise ValueError(f'{directory}: incomplete decisions')
        for name in ('case.json', 'environment.bin'):
            scene_file = directory / 'scene' / name
            if not scene_file.is_file():
                raise ValueError(f'{directory}: missing scene {name}')
            provenance.update(str(scene_file).encode() + b'\0' + scene_file.read_bytes())
        with (directory / 'chase.jsonl').open('rb') as stream:
            start = stream.readline()
        if json.loads(start).get('event') != 'start':
            raise ValueError(f'{directory}: missing start event')
        provenance.update(start)
        log_paths.append(directory / 'native.log')
    for path in log_paths:
        if path.exists():
            with path.open(errors='replace') as stream:
                for line in stream:
                    if re.search(r'\btimed out\b|\btimeout\b', line, re.IGNORECASE):
                        raise ValueError(f'{path}: timeout recorded')
    return n, fit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selection-base', type=int, default=7800000)
    parser.add_argument('--student-weights', help='SHA256 of the student weights used to collect the student shards')
    parser.add_argument('--student-model', type=Path, help='current source model, including receipt and kernels')
    parser.add_argument('--expect-teacher-shards', type=int)
    parser.add_argument('--expect-student-shards', type=int)
    parser.add_argument('--expect-games', type=int)
    parser.add_argument('--teacher', nargs='*', type=Path, default=[])
    parser.add_argument('--student', nargs='*', type=Path, default=[])
    args = parser.parse_args()
    if not args.teacher and not args.student:
        parser.error('at least one shard is required')
    if args.expect_teacher_shards is not None and len(args.teacher) != args.expect_teacher_shards:
        parser.error('unexpected number of teacher shards')
    if args.expect_student_shards is not None and len(args.student) != args.expect_student_shards:
        parser.error('unexpected number of student shards')
    if args.student and (not args.student_weights or len(args.student_weights) != 64 or not args.student_model):
        parser.error('--student-weights SHA256 and --student-model DIR are required for student shards')
    seen, total, fitting = set(), 0, 0
    provenance = hashlib.sha256()
    paths = args.teacher + args.student
    if len({p.resolve() for p in paths}) != len(paths):
        parser.error('duplicate shard path')
    for student, shards in ((False, args.teacher), (True, args.student)):
        for shard in shards:
            n, fit = audit(shard, student, args.student_weights, args.student_model, args.selection_base, seen, provenance)
            total += n
            fitting += fit
    if args.expect_games is not None and total != args.expect_games:
        raise ValueError(f'expected {args.expect_games} games, got {total}')
    print(json.dumps({'status': 'passed', 'teacherShards': len(args.teacher), 'studentShards': len(args.student),
                      'games': total, 'trainingGames': fitting, 'validationGames': total - fitting,
                      'selectionSeeds': [args.selection_base, args.selection_base + 31],
                      'sceneStartSHA256': provenance.hexdigest(),
                      'selectionScope': 'source shards only; model ancestry is not audited',
                      'modelIdentityScope': 'snapshot matches current source; pre-run receipt and kernels were not recorded'}, sort_keys=True))


if __name__ == '__main__':
    main()
