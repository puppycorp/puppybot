#!/usr/bin/env python3
"""Independent read-only lineage and command audit for the CPU collector plan."""
import hashlib
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
SELECTION = P / 'fresh-policy-selection-v3'
MONITOR = P / 'fresh-policy-selection-monitored-v3'
MODEL = P / 'search-dagger-l35-4workers/student-s1'
DATA = P / 'search-dagger-l35-4workers/data'
OUTPUT = P / 'parent-route-collector-v1'


def sha(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def validate_design(plan):
    if plan.get('schema') != 'puppybot.parent-route-collector-plan.v1' or plan.get('status') != 'cpu_plan_only':
        raise ValueError('unexpected plan status')
    rows = plan['rows']
    expected = [(0, 0, 'fit', 7820010, 15, 10), (0, 1, 'companion_only', 7820011, 17, 11),
                (1, 0, 'fit', 7820025, 15, 9), (1, 1, 'companion_only', 7820026, 17, 10)]
    actual = [(x['shard'], x['episode'], x['role'], x['seed'], x['layout'], x['variant']) for x in rows]
    if actual != expected or [rows[i]['firstDeliveryStep'] for i in (0, 2)] != [163, 189]:
        raise ValueError('fit/companion design differs')
    commands = []
    for shard, seed in enumerate((7820010, 7820025)):
        commands.append([str(ROOT / 'build/flex/control/control'), 'collect', '--chase', '--scene-catalog',
                         str(OUTPUT / 'catalogs' / str(shard)), '--output', str(OUTPUT / f'shard-{shard}'),
                         '--episodes', '2', '--validation', '1', '--horizon', '300', '--seed', str(seed),
                         '--lean', '--wheel-odometry', '--fetch', '--explore-teacher', '--level', '5',
                         '--camera-pitch', '82', '--record-map', '--policy', str(MODEL)])
    semantics = {'actor': 'parent policy chooses and executes each action',
                 'data': 'PVDATA01 pre-action RGB and feedback, teacher action label, map',
                 'journal': 'decisions[i].action is the executed action; state/proprio are post-step',
                 'selfImitation': False, 'fitting': 'episode 0 of each shard only; companions never added',
                 'gate': 'must independently audit full collection, first-delivery prefix and label differences'}
    if plan.get('commands') != commands or plan.get('semantics') != semantics:
        raise ValueError('collector command or supervision differs')
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'SDL_VIDEODRIVER': 'offscreen',
           'PUPPYBOT_PROJECT': str(ROOT), 'LD_LIBRARY_PATH': str(ROOT / 'build/flex/rocm-runtime')}
    if plan.get('environment') != env:
        raise ValueError('collector environment differs')
    if any('--self-imitate' in command or '--sample-actions' in command for command in commands):
        raise ValueError('collector overwrites teacher labels')
    return rows


def audit(plan):
    rows = validate_design(plan)
    required = [ROOT / 'build/flex/control/control', ROOT / 'build/flex/control/simulator',
                ROOT / 'build/flex/sim/puppybot.bin', ROOT / 'puppybot.json',
                *[MODEL / x for x in ('receipt.json', 'weights.bin', 'policy')],
                *sorted((MODEL / 'kernels').iterdir()), DATA / 'data.bin', DATA / 'map.bin',
                *[Path(__file__).resolve().parent / x for x in ('plan.py', 'audit.py', 'test.py', 'README.md')],
                *[ROOT / 'flex/control' / x for x in ('chase.flex', 'environment.flex', 'main.flex', 'dataset.flex')],
                ROOT / 'experiments/outbound-prefix-mask-v1/mask.py',
                ROOT / 'diary/128-parent-retention-feasibility.md']
    if set(plan['inputSHA256']) != {str(path) for path in required}:
        raise ValueError('pinned input inventory differs')
    for name, expected in plan['inputSHA256'].items():
        path = Path(name)
        if path.is_symlink() or not path.is_file() or sha(path) != expected:
            raise ValueError(f'plan input differs: {name}')
    completion = read(MONITOR / 'completion.json')
    if (completion.get('status') != 'diagnostic_only' or
            sha(MONITOR / 'completion.json') != plan['selectionCompletionSHA256'] or
            sha(MONITOR / 'evidence.json') != plan['selectionEvidenceSHA256'] or
            completion['evidenceSHA256'] != plan['selectionEvidenceSHA256'] or
            completion['frozenManifestSHA256'] != plan['selectionManifestSHA256'] or
            sha(SELECTION / 'inputs.json') != plan['selectionManifestSHA256'] or
            read(MONITOR / 'monitor-result.json') != {'status': 'passed'}):
        raise ValueError('selection evidence chain differs')
    receipt_paths = {'launchSHA256': 'launch.json', 'monitorResultSHA256': 'monitor-result.json',
                     'diskSHA256': 'disk.jsonl', 'telemetrySHA256': 'telemetry.jsonl',
                     'outerSupervisorStatusSHA256': 'outer-monitor/supervisor-result.json',
                     'finalInventoryInvocationSHA256': 'final-inventory-monitor/invocation.json',
                     'finalInventoryStatusSHA256': 'final-inventory-monitor/supervisor-result.json',
                     'finalInventoryResultSHA256': 'final-inventory-monitor/client.log'}
    for key, relative in receipt_paths.items():
        if sha(MONITOR / relative) != completion.get(key):
            raise ValueError(f'selection receipt differs: {key}')
    for name in ('outer-monitor/supervisor-result.json', 'final-inventory-monitor/supervisor-result.json'):
        status = read(MONITOR / name)
        if (status.get('clientExit') != 0 or status.get('signal') is not None or
                status.get('timedOut') is not False or status.get('remainingWorkersTerminated') is not False):
            raise ValueError('selection supervisor did not finish cleanly')
    if json.loads((MONITOR / 'final-inventory-monitor/client.log').read_text()) != {'status': 'final_inventory_verified'}:
        raise ValueError('selection final inventory did not pass')
    evidence = read(MONITOR / 'evidence.json')
    if evidence.get('status') != 'diagnostic_only' or read(SELECTION / 'report.json') != evidence['report']:
        raise ValueError('selection report differs from sealed evidence')
    inventory = evidence['files']['files']
    manifest = read(SELECTION / 'inputs.json')
    if manifest != read(P / 'fresh-policy-selection-plan-v3.json'):
        raise ValueError('registered selection manifest differs')
    selected_pins = [ROOT / 'build/flex/control/control', ROOT / 'build/flex/control/simulator',
                     ROOT / 'build/flex/sim/puppybot.bin', ROOT / 'puppybot.json',
                     *[MODEL / x for x in ('receipt.json', 'weights.bin', 'policy')],
                     *sorted((MODEL / 'kernels').iterdir())]
    if any(manifest['files'].get(str(path)) != plan['inputSHA256'].get(str(path)) for path in selected_pins):
        raise ValueError('model or binary differs from frozen selection')
    if plan['runtime'] != manifest['runtime']:
        raise ValueError('runtime registration differs')
    path = ROOT / 'build/flex/rocm-runtime/libamdhip64.so'; chain = {}; visited = set()
    while path.is_symlink():
        if path in visited or len(visited) >= 16:
            raise ValueError('runtime cycle')
        visited.add(path); target = os.readlink(path); chain[str(path)] = 'link:' + target
        path = Path(os.path.abspath(path.parent / target))
    chain[str(path)] = 'sha256:' + sha(path)
    if chain != plan['runtime']:
        raise ValueError('runtime chain changed')
    receipt = read(MODEL / 'receipt.json')
    if (sha(MODEL / 'weights.bin') != receipt['weightsSHA256'] or
            sha(MODEL / 'policy') != receipt['binarySHA256'] or
            plan['inputSHA256'].get(str(DATA / 'data.bin')) != receipt['dataSHA256'] or
            plan['inputSHA256'].get(str(DATA / 'map.bin')) != receipt['memoryMapTargetsSHA256']):
        raise ValueError('parent model/data lineage differs')
    known = set(manifest['files'])
    for row in rows:
        if row['layout'] in range(226, 290):
            raise ValueError('reserved held-out layout')
        scene = Path(row['scene']); meta = read(scene / 'layout.json')
        if scene != ROOT / 'build/flex/sim/expanded-rooms-v1/scenes' / str(row['layout']) / str(row['variant']):
            raise ValueError('scene path differs')
        if meta.get('fit') is not True or meta.get('reservedHeldOut') is True or meta['layoutId'] != row['layout']:
            raise ValueError('scene role differs')
        if set(row['sceneSHA256']) != {'case.json', 'environment.bin', 'layout.json'}:
            raise ValueError('scene input inventory incomplete')
        for name, digest in row['sceneSHA256'].items():
            path = scene / name
            if (str(path) not in known or manifest['files'][str(path)] != digest or sha(path) != digest):
                raise ValueError('selection scene hash differs')
            if name == 'case.json':
                if path.is_symlink(): raise ValueError('symlinked case')
            elif (not path.is_symlink() or os.readlink(path) != manifest['sceneLinks'].get(str(path)) or
                  path.resolve(strict=True) != scene.parent / name):
                raise ValueError('scene link differs')
        original = Path(row['selectionRun'])
        expected_run = SELECTION / 'L5/control' / str((row['seed'] - 7820000) // 8) / str(row['seed'])
        if original != expected_run or set(row['selectionSHA256']) != {'initial.json', 'result.json', 'decisions.jsonl',
                                                                          'chase.jsonl', 'scene/case.json', 'scene/environment.bin'}:
            raise ValueError('selection game inventory differs')
        for name, digest in row['selectionSHA256'].items():
            path = original / name; rel = str(path.relative_to(SELECTION)); item = inventory.get(rel)
            if (path.is_symlink() or not path.is_file() or not isinstance(item, dict) or
                    item.get('sha256') != digest or item.get('size') != path.stat().st_size or sha(path) != digest):
                raise ValueError('saved selection game differs from sealed inventory')
        result = read(original / 'result.json')
        events = [json.loads(line) for line in (original / 'chase.jsonl').read_text().splitlines()]
        deliveries = [event['step'] for event in events if event['event'] == 'delivery']
        if (result['seed'] != row['seed'] or result['steps'] != 300 or
                result['policyWeightsSHA256'] != receipt['weightsSHA256'] or
                result['deliveries'] != len(deliveries) or
                (deliveries[0] if deliveries else None) != row['firstDeliveryStep']):
            raise ValueError('selection model or seed differs')
    return {'status': 'lineage_plan_only', 'fit': 2, 'companionOnly': 2,
            'scope': ('independent local byte/receipt checks only; no collector launch, '
                      'exhaustive ancestry, unobserved frames, held-out or physical proof')}


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('audit.py PLAN_JSON')
    print(json.dumps(audit(read(sys.argv[1])), sort_keys=True))
