#!/usr/bin/env python3
"""Read saved placements to distinguish old and current level conventions."""
import collections
import hashlib
import importlib.util
import json
import math
import os
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SIM = ROOT / 'build/flex/sim'
LEGACY = SIM / 'levels-v1/pitch82'
CURRENT = SIM / 'levels-v2/pitch82'
SELECTION = CURRENT / 'fresh-policy-selection-v2/inputs.json'
FIT_LAYOUTS = (27, 29, 31)
VALIDATION_LAYOUTS = (33, 35, 37)


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def inspect_group(base, level, expected_games):
    root = base / f'{"div" if base == LEGACY else "kturn"}-L{level}'
    groups = collections.defaultdict(lambda: collections.Counter())
    totals = collections.Counter()
    shards = sorted(path for path in root.glob('shard-*') if path.is_dir())
    for shard in shards:
        number = int(shard.name.split('-')[1])
        report = json.loads((shard / 'report.json').read_text())
        games = list(shard.glob('expert-*'))
        teacher = 'sweeping fetch teacher' if base == LEGACY else 'exploring fetch teacher'
        if (not report.get('complete') or report.get('episodes') != len(games) or
                report.get('teacher') != teacher or report.get('studentDriven') is not False):
            raise ValueError(f'incomplete saved shard: {shard}')
        for game in games:
            index = int(game.name.split('-')[1])
            catalog = root / 'catalogs' / str(number) / str(index)
            layout = json.loads((catalog / 'layout.json').read_text())
            rooms = layout['rooms']
            if len(rooms) != 2 or rooms[0][2] != rooms[1][0]:
                raise ValueError('not a vertical two-room scene')
            partition = rooms[0][2]
            if layout.get('door') is not None and layout['door'][0] != partition:
                raise ValueError('door and room boundary differ')
            if digest(game / 'scene/environment.bin') != digest(catalog / 'environment.bin'):
                raise ValueError('saved environment differs from catalog')
            result = json.loads((game / 'result.json').read_text())
            with (game / 'chase.jsonl').open() as stream:
                start = json.loads(stream.readline())
            if (start.get('event') != 'start' or start.get('step') != 0 or result.get('level') != level or
                    result.get('seed') != report.get('seed') + index or result.get('controller') != teacher):
                raise ValueError('unexpected saved start or level')
            side_a = start['robot'][0] > partition
            side_b = start['brick'][0] > partition
            side = 'opposite' if side_a != side_b else 'same'
            deliveries = result['deliveries']
            if result.get('steps') != 300 or result.get('actionSeconds') != 60 or type(deliveries) is not int or deliveries < 0:
                raise ValueError('incomplete or invalid game result')
            for counter in (totals, groups[layout['layoutId']]):
                counter['games'] += 1
                counter[side] += 1
                counter['deliveries'] += deliveries
                counter['delivered_games'] += deliveries > 0
                counter['level_marker_' + str(result.get('levelPlacement', 'absent'))] += 1
    if totals['games'] != expected_games:
        raise ValueError('unexpected game count')
    return {'total': dict(totals), 'byLayout': {str(k): dict(v) for k, v in sorted(groups.items())}}


def catalog_comparison():
    selection = json.loads(SELECTION.read_text())['design']['tasks']
    selected = [row for task in selection for row in task['rows']]
    selected_env = {digest(Path(row['scene']) / 'environment.bin') for row in selected}
    selected_case = {digest(Path(row['scene']) / 'case.json') for row in selected}
    rows = []
    pilot_file = ROOT / 'experiments/outbound-teacher-prefix-pilot-v1/plan.py'
    spec = importlib.util.spec_from_file_location('prior_outbound_pilot', pilot_file)
    prior = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prior)
    preflight = prior.preflight()
    seeds = [row['seed'] for row in preflight['design']['rows']]
    if seeds != list(range(6910000, 6910012)):
        raise ValueError('prior pilot seed design changed')
    for fitting, layouts, variants in ((True, FIT_LAYOUTS, (8, 9, 10)),
                                       (False, VALIDATION_LAYOUTS, (11,))):
        for layout in layouts:
            for variant in variants:
                scene = SIM / 'levels-v1/diverse-scenes' / str(layout) / str(variant)
                if scene.is_symlink() or not scene.is_dir() or {p.name for p in scene.iterdir()} != {'case.json', 'environment.bin', 'layout.json'}:
                    raise ValueError('unexpected candidate scene inventory')
                if (scene / 'case.json').is_symlink():
                    raise ValueError('candidate case is symlinked')
                for name in ('layout.json', 'environment.bin'):
                    link = scene / name
                    if not link.is_symlink() or Path(os.path.abspath(link.parent / os.readlink(link))) != scene.parent / name:
                        raise ValueError('candidate layout link changed')
                metadata = json.loads((scene / 'layout.json').read_text())
                if metadata.get('layoutId') != layout or metadata.get('fit') is not True or len(metadata['rooms']) != 2:
                    raise ValueError('unexpected candidate scene')
                raw = (scene / 'environment.bin').read_bytes()
                if len(raw) < 256 or raw[:8] != b'PBENV001':
                    raise ValueError('invalid environment')
                count, vertices, repeated = struct.unpack_from('<qqq', raw, 8)
                if not 1 <= count <= 160 or vertices != repeated or vertices < 3 or vertices % 3 or len(raw) != 256 + count * 128 + vertices * 72:
                    raise ValueError('invalid environment dimensions')
                pose = struct.unpack_from('<3d', raw, 96)
                walls = [struct.unpack_from('<d', raw, 256 + i * 128 + 48)[0] for i in range(count)
                         if raw[256 + i * 128:256 + i * 128 + 48].startswith(b'Wall.partition')]
                if len(walls) != 2 or not all(math.isfinite(v) for v in (*pose, *walls)) or walls[0] != walls[1] or walls[0] <= pose[0]:
                    raise ValueError('invalid two-room spawn or walls')
                if abs(metadata['rooms'][0][2] - walls[0]) > 1e-9 or abs(metadata['rooms'][1][0] - walls[0]) > 1e-9:
                    raise ValueError('partition metadata differs')
                environment_hash, case_hash = digest(scene / 'environment.bin'), digest(scene / 'case.json')
                rows.append({'index': len(rows), 'seed': seeds[len(rows)], 'fit': fitting, 'layout': layout,
                             'variant': variant, 'scene': str(scene), 'spawn': list(pose),
                             'environmentSHA256': environment_hash, 'caseSHA256': case_hash,
                             'layoutSHA256': digest(scene / 'layout.json'),
                             'environmentInCurrentSelection': environment_hash in selected_env,
                             'caseInCurrentSelection': case_hash in selected_case})
    return {'selectionManifestSHA256': digest(SELECTION), 'candidates': rows,
            'namedHistorySeedInventory': {'records': preflight['history']['records'],
                'sha256': preflight['history']['sha256'],
                'skippedSymlinkDirectories': len(preflight['history']['skippedSymlinkDirectories'])},
            'distinctCandidateEnvironmentHashes': len({r['environmentSHA256'] for r in rows}),
            'distinctCandidateCaseHashes': len({r['caseSHA256'] for r in rows})}


def audit():
    return {'legacyL4': inspect_group(LEGACY, 4, 64), 'legacyL5': inspect_group(LEGACY, 5, 64),
            'currentL4': inspect_group(CURRENT, 4, 256), 'currentL5': inspect_group(CURRENT, 5, 128),
            'exploratoryCatalog': catalog_comparison(),
            'scope': 'saved local records only; no run, training, unseen-scene, physical or execution claim'}


if __name__ == '__main__':
    print(json.dumps(audit(), sort_keys=True, indent=2, allow_nan=False))
