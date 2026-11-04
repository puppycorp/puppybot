#!/usr/bin/env python3
"""Read-only CPU plan for parent-driven L5 data; no collector is launched."""
import hashlib
import json
import os
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
SELECTION = P / 'fresh-policy-selection-v3'
MONITOR = P / 'fresh-policy-selection-monitored-v3'
MODEL = P / 'search-dagger-l35-4workers/student-s1'
PARENT_DATA = P / 'search-dagger-l35-4workers/data'
OUTPUT = P / 'parent-route-collector-v1'
SEEDS = (7820010, 7820011, 7820025, 7820026)
EXPECTED = ((10, 15, 10), (11, 17, 11), (25, 15, 9), (26, 17, 10))


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def runtime_chain(path):
    path = Path(path).absolute(); seen = set(); chain = {}
    while path.is_symlink():
        if path in seen or len(seen) >= 16:
            raise ValueError('runtime symlink cycle')
        seen.add(path); target = os.readlink(path); chain[str(path)] = 'link:' + target
        path = Path(os.path.abspath(path.parent / target))
    if not path.is_file():
        raise ValueError('runtime target missing')
    chain[str(path)] = 'sha256:' + sha(path)
    return chain


def command(shard):
    if shard not in (0, 1):
        raise ValueError('unknown shard')
    seed = (SEEDS[0], SEEDS[2])[shard]
    return [str(ROOT / 'build/flex/control/control'), 'collect', '--chase',
            '--scene-catalog', str(OUTPUT / 'catalogs' / str(shard)),
            '--output', str(OUTPUT / f'shard-{shard}'), '--episodes', '2', '--validation', '1',
            '--horizon', '300', '--seed', str(seed), '--lean', '--wheel-odometry', '--fetch',
            '--explore-teacher', '--level', '5', '--camera-pitch', '82', '--record-map', '--policy', str(MODEL)]


def source_paths(manifest):
    frozen = manifest['files']
    paths = [ROOT / 'build/flex/control/control', ROOT / 'build/flex/control/simulator',
             ROOT / 'build/flex/sim/puppybot.bin', ROOT / 'puppybot.json']
    paths += [MODEL / name for name in ('receipt.json', 'weights.bin', 'policy')]
    paths += sorted((MODEL / 'kernels').iterdir())
    for path in paths:
        if not path.is_file() or frozen.get(str(path)) != sha(path):
            raise ValueError(f'selection-frozen input differs: {path}')
    return paths


def snapshot():
    registered = P / 'fresh-policy-selection-plan-v3.json'
    manifest = read(SELECTION / 'inputs.json')
    if manifest != read(registered):
        raise ValueError('selection inputs differ from registered plan')
    runtime = runtime_chain(ROOT / 'build/flex/rocm-runtime/libamdhip64.so')
    if runtime != manifest['runtime']:
        raise ValueError('selection GPU runtime changed')
    completion = read(MONITOR / 'completion.json')
    if (completion.get('status') != 'diagnostic_only' or
            completion.get('evidenceSHA256') != sha(MONITOR / 'evidence.json') or
            completion.get('frozenManifestSHA256') != sha(SELECTION / 'inputs.json') or
            completion.get('monitorResultSHA256') != sha(MONITOR / 'monitor-result.json') or
            read(MONITOR / 'monitor-result.json') != {'status': 'passed'}):
        raise ValueError('selection completion evidence differs')
    evidence = read(MONITOR / 'evidence.json')
    sealed = evidence['files']['files']
    sources = source_paths(manifest)
    receipt = read(MODEL / 'receipt.json')
    parent_hashes = {str(PARENT_DATA / name): sha(PARENT_DATA / name) for name in ('data.bin', 'map.bin')}
    if (receipt['weightsSHA256'] != sha(MODEL / 'weights.bin') or
            receipt['binarySHA256'] != sha(MODEL / 'policy') or
            receipt['dataSHA256'] != parent_hashes[str(PARENT_DATA / 'data.bin')] or
            receipt['memoryMapTargetsSHA256'] != parent_hashes[str(PARENT_DATA / 'map.bin')]):
        raise ValueError('parent model to baseline dataset lineage differs')
    rows = []
    for shard in range(2):
        for episode in range(2):
            index = 2 * shard + episode
            expected_index, layout, variant = EXPECTED[index]
            row = manifest['design']['tasks'][4]['rows'][expected_index]
            if (row['index'], row['seed'], row['layout'], row['variant']) != (expected_index, SEEDS[index], layout, variant):
                raise ValueError('selection row differs from fixed design')
            scene = Path(row['scene']); scene_hashes = {}
            for name in ('case.json', 'environment.bin', 'layout.json'):
                path = scene / name
                if name == 'case.json':
                    if path.is_symlink():
                        raise ValueError('scene case is symlinked')
                elif (not path.is_symlink() or
                      os.readlink(path) != manifest['sceneLinks'].get(str(path)) or
                      path.resolve(strict=True) != scene.parent / name):
                    raise ValueError('selection scene link differs')
                if not path.is_file() or manifest['files'].get(str(path)) != sha(path):
                    raise ValueError(f'selection scene differs: {path}')
                scene_hashes[name] = sha(path)
            meta = read(scene / 'layout.json')
            if meta.get('fit') is not True or meta.get('reservedHeldOut') is True or meta['layoutId'] != layout:
                raise ValueError('scene is not a fitting layout')
            original = SELECTION / 'L5/control' / str(expected_index // 8) / str(SEEDS[index])
            archived = {}
            for name in ('initial.json', 'result.json', 'decisions.jsonl', 'chase.jsonl',
                         'scene/case.json', 'scene/environment.bin'):
                path = original / name; rel = str(path.relative_to(SELECTION)); pin = sealed.get(rel)
                if (not path.is_file() or path.is_symlink() or not isinstance(pin, dict) or
                        pin.get('size') != path.stat().st_size or pin.get('sha256') != sha(path)):
                    raise ValueError(f'original selection record differs: {path}')
                archived[name] = pin['sha256']
            result = read(original / 'result.json')
            events = [json.loads(line) for line in (original / 'chase.jsonl').read_text().splitlines()]
            deliveries = [event['step'] for event in events if event['event'] == 'delivery']
            if (result['seed'] != SEEDS[index] or result['steps'] != 300 or
                    result['policyWeightsSHA256'] != receipt['weightsSHA256'] or
                    len(deliveries) != result['deliveries'] or
                    (episode == 0 and (not deliveries or deliveries[0] != (163, 189)[shard]))):
                raise ValueError('original game identity differs')
            rows.append({'shard': shard, 'episode': episode, 'role': 'fit' if episode == 0 else 'companion_only',
                         'seed': SEEDS[index], 'layout': layout, 'variant': variant, 'scene': str(scene),
                         'sceneSHA256': scene_hashes, 'selectionRun': str(original),
                         'selectionSHA256': archived, 'originalDeliveries': result['deliveries'],
                         'firstDeliveryStep': deliveries[0] if deliveries else None})
    files = {str(path): sha(path) for path in sources}
    files.update(parent_hashes)
    local = (HERE / 'plan.py', HERE / 'audit.py', HERE / 'test.py', HERE / 'README.md',
             ROOT / 'flex/control/chase.flex', ROOT / 'flex/control/environment.flex',
             ROOT / 'flex/control/main.flex', ROOT / 'flex/control/dataset.flex',
             ROOT / 'experiments/outbound-prefix-mask-v1/mask.py',
             ROOT / 'diary/128-parent-retention-feasibility.md')
    files.update({str(path): sha(path) for path in local})
    return {'schema': 'puppybot.parent-route-collector-plan.v1', 'status': 'cpu_plan_only',
            'rows': rows, 'commands': [command(0), command(1)],
            'environment': {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()),
                            'SDL_VIDEODRIVER': 'offscreen', 'PUPPYBOT_PROJECT': str(ROOT),
                            'LD_LIBRARY_PATH': str(ROOT / 'build/flex/rocm-runtime')},
            'inputSHA256': files, 'runtime': runtime, 'selectionCompletionSHA256': sha(MONITOR / 'completion.json'),
            'selectionEvidenceSHA256': sha(MONITOR / 'evidence.json'),
            'selectionManifestSHA256': sha(SELECTION / 'inputs.json'),
            'semantics': {'actor': 'parent policy chooses and executes each action',
                          'data': 'PVDATA01 pre-action RGB and feedback, teacher action label, map',
                          'journal': 'decisions[i].action is the executed action; state/proprio are post-step',
                          'selfImitation': False, 'fitting': 'episode 0 of each shard only; companions never added',
                          'gate': 'must independently audit full collection, first-delivery prefix and label differences'},
            'scope': ('prior selection scenes are now fitting-family data; no independent selection, '
                      'held-out, physical, GPU collection or training claim')}


if __name__ == '__main__':
    print(json.dumps(snapshot(), indent=2, sort_keys=True, allow_nan=False))
