#!/usr/bin/env python3
"""Read-only inventory of explicitly audited parent-training source shards.

This never opens held-out catalogs or generates scenes. It does not establish
complete pretraining ancestry, semantic/near geometry or model execution.
"""
import hashlib
import importlib.util
import json
import os
import stat
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = ROOT / 'build/flex/sim/levels-v2/pitch82'
SOURCE_AUDIT = BASE / 'search-dagger-l35-4workers/source-audit.json'
SOURCE_AUDIT_SHA256 = '5250411694d9641002b14dfe259f647051efb22dc66fa903cf5dea0f12fc38a3'


def load_geometry():
    path = HERE / 'world_geometry.py'
    spec = importlib.util.spec_from_file_location('prior_world_geometry', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(data):
    return hashlib.sha256(data).hexdigest()


def stable_read(path, maximum):
    path = Path(path).absolute()
    if path.resolve(strict=True) != path:
        raise ValueError(f'symlinked source is not an approved scene snapshot: {path}')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size < 1 or before.st_size > maximum:
            raise ValueError(f'invalid prior file size or type: {path}')
        chunks = []
        while True:
            block = os.read(fd, 1024 * 1024)
            if not block:
                break
            chunks.append(block)
        after = os.fstat(fd)
        data = b''.join(chunks)
        if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) or
                len(data) != before.st_size):
            raise ValueError(f'prior file changed during read: {path}')
        return data
    finally:
        os.close(fd)


def object_json(data):
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError('expected a JSON object')
    return value


def inventory(source_path=SOURCE_AUDIT, source_sha=SOURCE_AUDIT_SHA256, *, allowed_root=BASE,
              expected_shards=48, expected_games=1024, expected_fit=928):
    """Inventory named shard rows; overrides exist only for synthetic tests."""
    geometry = load_geometry()
    geometry_bytes = stable_read(HERE / 'world_geometry.py', 1024 * 1024)
    source_bytes = stable_read(source_path, 16 * 1024 * 1024)
    if digest(source_bytes) != source_sha:
        raise ValueError('source-audit digest differs')
    source = object_json(source_bytes)
    shards = source.get('orderedShards')
    if (source.get('status') != 'passed' or not isinstance(shards, list) or
            len(shards) != expected_shards or len(set(shards)) != expected_shards or
            source.get('games') != expected_games or source.get('trainingGames') != expected_fit or
            source.get('validationGames') != expected_games - expected_fit):
        raise ValueError('source-audit counts or ordered shards differ')
    root = Path(allowed_root).absolute().resolve(strict=True)
    seen_seeds, rows, shard_rows = set(), [], []
    provenance = hashlib.sha256()
    fit_count = 0
    for name in shards:
        if not isinstance(name, str):
            raise ValueError('invalid shard path')
        shard = Path(name).absolute()
        if shard.resolve(strict=True) != shard or not shard.is_relative_to(root) or not shard.is_dir():
            raise ValueError('unsafe or missing source shard')
        report_bytes = stable_read(shard / 'report.json', 1024 * 1024)
        report = object_json(report_bytes)
        seed, count, fit = report.get('seed'), report.get('episodes'), report.get('trainingEpisodes')
        if (report.get('complete') is not True or type(seed) is not int or seed < 0 or
                type(count) is not int or not 1 <= count <= 1024 or type(fit) is not int or
                not 0 <= fit <= count or report.get('validationEpisodes') != count - fit or
                report.get('sequenceLength') != 300):
            raise ValueError('invalid source shard report')
        shard_rows.append({'path': str(shard), 'reportSHA256': digest(report_bytes),
                           'seed': seed, 'episodes': count, 'fitting': fit})
        student_driven = report.get('studentDriven')
        if type(student_driven) is not bool:
            raise ValueError('missing source shard driver identity')
        if student_driven:
            receipt = stable_read(shard / 'policy/receipt.json', 1024 * 1024)
            object_json(receipt)
            provenance.update(receipt)
            shard_rows[-1]['policyReceiptSHA256'] = digest(receipt)
        for index in range(count):
            game = shard / f'expert-{index}'
            result_bytes = stable_read(game / 'result.json', 1024 * 1024)
            case = stable_read(game / 'scene/case.json', 32 * 1024 * 1024)
            environment = stable_read(game / 'scene/environment.bin', 32 * 1024 * 1024)
            journal = stable_read(game / 'chase.jsonl', 16 * 1024 * 1024)
            result = object_json(result_bytes)
            first_line = journal.splitlines(keepends=True)[0]
            first = object_json(first_line)
            if (result.get('seed') != seed + index or result.get('game') != 'fetch' or
                    result.get('steps') != 300 or first.get('event') != 'start' or first.get('step') != 0):
                raise ValueError('source game identity or start differs')
            start = geometry.finite_vector(first.get('robot'), 3)
            actual_seed = seed + index
            if actual_seed in seen_seeds:
                raise ValueError('duplicate prior game seed')
            seen_seeds.add(actual_seed)
            for filename, blob in (('case.json', case), ('environment.bin', environment)):
                provenance.update(str(game / 'scene' / filename).encode() + b'\0' + blob)
            provenance.update(first_line)
            rows.append({'shard': str(shard), 'episode': index, 'seed': actual_seed,
                         'split': 'fit' if index < fit else 'validation',
                         'resultSHA256': digest(result_bytes), 'caseSHA256': digest(case),
                         'environmentSHA256': digest(environment),
                         'colliderGeometrySHA256': geometry.collider_digest(environment),
                         'projectedPhysicsSHA256': geometry.projected_physics_digest(environment),
                         'startEventSHA256': digest(first_line), 'startPose': list(start)})
        fit_count += fit
    if len(rows) != expected_games or fit_count != expected_fit:
        raise ValueError('inventoried prior split differs')
    if source.get('sceneStartSHA256') != provenance.hexdigest():
        raise ValueError('source scene/start bytes differ from archived audit')
    if (stable_read(source_path, 16 * 1024 * 1024) != source_bytes or
            stable_read(HERE / 'world_geometry.py', 1024 * 1024) != geometry_bytes):
        raise ValueError('inventory inputs changed during scan')
    canonical = json.dumps(rows, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return {'status': 'named_parent_shards_inventoried', 'sourceAuditSHA256': source_sha,
            'geometrySourceSHA256': digest(geometry_bytes), 'sceneStartSHA256': provenance.hexdigest(),
            'shards': shard_rows, 'games': rows,
            'gamesSHA256': digest(canonical), 'counts': {'shards': len(shard_rows), 'games': len(rows),
                'fit': fit_count, 'validation': len(rows) - fit_count,
                'uniqueSeeds': len(seen_seeds), 'uniqueCases': len({r['caseSHA256'] for r in rows}),
                'uniqueEnvironments': len({r['environmentSHA256'] for r in rows}),
                'uniqueColliderGeometries': len({r['colliderGeometrySHA256'] for r in rows}),
                'uniqueProjectedPhysics': len({r['projectedPhysicsSHA256'] for r in rows})},
            'scope': ('only named parent-training shard copies and declared seed ranges; '
                      'archived scene/start digest binds scene bytes and student receipts, '
                      'not historical result/report bytes; no atomic snapshot, complete model ancestry, '
                      'execution, rendered-mesh, complete physics equivalence or near-geometry claim')}


if __name__ == '__main__':
    print(json.dumps(inventory(), sort_keys=True, indent=2, allow_nan=False))
