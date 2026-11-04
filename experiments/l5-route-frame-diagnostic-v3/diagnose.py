#!/usr/bin/env python3
"""Read-only provenance and action comparison for two prior L5 games.

This checks retained selection records, not the actor images (which were not
saved in the lean evaluation), execution provenance, or physical behavior.
"""
import hashlib
import json
import math
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'build/flex/sim/levels-v2/pitch82'
SELECTION = BASE / 'fresh-policy-selection-v3'
SEEDS = (7820010, 7820025)
ARMS = ('control', 'treatment')


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def read_rows(path):
    with Path(path).open() as source:
        return [json.loads(line) for line in source]


def check_file(path, frozen):
    path = Path(path)
    expected = frozen.get(str(path))
    if not expected or not path.is_file() or digest(path) != expected:
        raise ValueError(f'missing or changed frozen input: {path}')
    return expected


def check_sealed(path, sealed):
    path = Path(path)
    relative = str(path.relative_to(SELECTION))
    expected = sealed.get(relative)
    if (not isinstance(expected, dict) or path.is_symlink() or not path.is_file() or
            path.stat().st_size != expected.get('size') or digest(path) != expected.get('sha256')):
        raise ValueError(f'selection evidence differs: {path}')
    return expected['sha256']


def runtime_chain(path):
    path = Path(path).absolute()
    result, seen = {}, set()
    while path.is_symlink():
        if path in seen or len(seen) >= 16:
            raise ValueError('runtime symlink cycle')
        seen.add(path)
        target = os.readlink(path)
        result[str(path)] = 'link:' + target
        path = Path(os.path.abspath(path.parent / target))
    if not path.is_file():
        raise ValueError('runtime target missing')
    result[str(path)] = 'sha256:' + digest(path)
    return result


def detection_indices(rows):
    return [index for index, row in enumerate(rows)
            if row['state']['case']['perception']['detections']]


def actions_digest(rows):
    encoded = json.dumps([row['action'] for row in rows], separators=(',', ':')).encode()
    return hashlib.sha256(encoded).hexdigest()


def check_invocation(arm, model, sealed):
    path = SELECTION / 'supervisors/L5' / arm / 'invocation.json'
    check_sealed(path, sealed)
    recorded = read_json(path)
    expected = ['/usr/bin/bash', str(ROOT / 'datasets/visual-control/chase-v1/evaluate.sh'),
                str(SELECTION / 'L5'), arm, str(model), '--fetch', '--level', '5',
                '--camera-pitch', '82']
    settings = {'PUPPYBOT_CHASE_FULL': '0', 'PUPPYBOT_CHASE_HORIZON': '300',
                'PUPPYBOT_CHASE_PARTS': '4', 'PUPPYBOT_EVAL_SELECTION': '1',
                'PUPPYBOT_EVAL_SELECTION_SEED': '7820000', 'PUPPYBOT_EVAL_TWO_ROOM': '1',
                'PUPPYBOT_PROJECT': str(ROOT), 'SDL_VIDEODRIVER': 'offscreen',
                'LD_LIBRARY_PATH': str(ROOT / 'build/flex/rocm-runtime')}
    if recorded['argv'] != expected or any(recorded['environment'].get(k) != v for k, v in settings.items()):
        raise ValueError(f'archived invocation differs: {path}')
    return {'path': str(path), 'sha256': digest(path), 'argv': expected, 'settings': settings}


def game(task, row, arm, frozen, model, model_sha, sealed):
    seed, index = row['seed'], row['index']
    run = SELECTION / task / arm / str(index // 8) / str(seed)
    scene = Path(row['scene'])
    for name in ('initial.json', 'result.json', 'decisions.jsonl', 'chase.jsonl',
                 'scene/case.json', 'scene/environment.bin'):
        check_sealed(run / name, sealed)
    for name in ('case.json', 'environment.bin'):
        check_file(scene / name, frozen)
        if digest(run / 'scene' / name) != digest(scene / name):
            raise ValueError(f'archived scene differs: {run / name}')
    check_file(scene / 'layout.json', frozen)
    result = read_json(run / 'result.json')
    if (result['seed'] != seed or result['steps'] != 300 or result['level'] != 5 or
            result['policyWeightsSHA256'] != model_sha or not result['carryCue'] or
            result['blackout'] or result['taskEventHint'] or result['suppliedMap']):
        raise ValueError(f'archived game metadata differs: {run}')
    decisions = read_rows(run / 'decisions.jsonl')
    events = read_rows(run / 'chase.jsonl')
    if len(decisions) != 300 or not events or events[0]['event'] != 'start' or events[0]['step'] != 0:
        raise ValueError(f'incomplete archived game: {run}')
    if any(len(decision['action']) != 2 or
           any(not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > 1
               for value in decision['action']) for decision in decisions):
        raise ValueError(f'invalid action: {run}')
    if (any(right['step'] - left['step'] != 10 for left, right in zip(decisions, decisions[1:])) or
            sum(event['event'] == 'delivery' for event in events) != result['deliveries']):
        raise ValueError(f'actions or delivery events disagree with the result: {run}')
    return {'run': str(run), 'model': str(model), 'resultSHA256': digest(run / 'result.json'),
            'decisionsSHA256': digest(run / 'decisions.jsonl'),
            'eventsSHA256': digest(run / 'chase.jsonl'), 'actionSequenceSHA256': actions_digest(decisions),
            'deliveryCount': result['deliveries'], 'initialRobot': events[0]['robot'],
            'initialBrick': events[0]['brick'], 'componentDetectionIndices': detection_indices(decisions)}, decisions


def diagnose():
    manifest_path = SELECTION / 'inputs.json'
    registered_path = BASE / 'fresh-policy-selection-plan-v3.json'
    manifest = read_json(manifest_path)
    if manifest != read_json(registered_path):
        raise ValueError('archived inputs differ from registered plan')
    design, frozen = manifest['design'], manifest['files']
    monitor = BASE / 'fresh-policy-selection-monitored-v3'
    completion = read_json(monitor / 'completion.json')
    evidence_path = monitor / 'evidence.json'
    if completion.get('status') != 'diagnostic_only' or digest(evidence_path) != completion.get('evidenceSHA256'):
        raise ValueError('sealed selection evidence differs')
    evidence = read_json(evidence_path)
    if evidence.get('status') != 'diagnostic_only':
        raise ValueError('unexpected selection evidence status')
    sealed = evidence['files']['files']
    check_sealed(SELECTION / 'report.json', sealed)
    if read_json(SELECTION / 'report.json') != evidence['report']:
        raise ValueError('sealed report differs from evidence')
    runtime = runtime_chain(ROOT / 'build/flex/rocm-runtime/libamdhip64.so')
    if runtime != manifest.get('runtime'):
        raise ValueError('frozen runtime chain differs')
    if design['horizon'] != 300 or design['actionSeconds'] != 0.2 or design['cameraPitch'] != 82:
        raise ValueError('registered run parameters differ')
    pinned = {}
    for relative in ('build/flex/control/control', 'build/flex/control/simulator',
                     'build/flex/sim/puppybot.bin', 'puppybot.json'):
        path = ROOT / relative
        pinned[str(path)] = check_file(path, frozen)
    model_shas, invocations = {}, {}
    for arm in ARMS:
        model = Path(design['models'][arm])
        for path in [model / 'receipt.json', model / 'weights.bin', model / 'policy',
                     *sorted((model / 'kernels').iterdir())]:
            pinned[str(path)] = check_file(path, frozen)
        model_shas[arm] = pinned[str(model / 'weights.bin')]
        invocations[arm] = check_invocation(arm, model, sealed)
    task = design['tasks'][4]
    if task['name'] != 'L5' or task['level'] != 5:
        raise ValueError('unexpected registered task')
    games = []
    for seed in SEEDS:
        index = seed - 7820000
        row = task['rows'][index]
        if row['seed'] != seed or row['index'] != index or row['layout'] != 15:
            raise ValueError('unexpected seed or layout')
        results, histories = {}, {}
        for arm in ARMS:
            results[arm], histories[arm] = game('L5', row, arm, frozen,
                                                 Path(design['models'][arm]), model_shas[arm], sealed)
        if (results['control']['initialRobot'] != results['treatment']['initialRobot'] or
                results['control']['initialBrick'] != results['treatment']['initialBrick']):
            raise ValueError('paired initial states differ')
        first = next((i for i, (left, right) in enumerate(zip(histories['control'], histories['treatment']))
                      if left['action'] != right['action']), None)
        games.append({'seed': seed, 'scene': row, 'firstDifferentActionIndex': first,
                      'caseSHA256': digest(Path(row['scene']) / 'case.json'),
                      'environmentSHA256': digest(Path(row['scene']) / 'environment.bin'),
                      'arms': results})
    return {'schema': 'puppybot.l5-route-frame-diagnostic.v1',
            'status': 'saved_record_diagnostic_only', 'inputsSHA256': digest(manifest_path),
            'registeredPlanSHA256': digest(registered_path), 'sealedEvidenceSHA256': digest(evidence_path), 'pinnedFiles': pinned,
            'invocations': invocations, 'runtime': runtime, 'games': games,
            'scope': ('Previously used training-family selection records. Logged case-component '
                      'detections are not the actor inputs; actor frames were not retained. '
                      'No execution attestation, held-out, physical or promotion claim.')}


if __name__ == '__main__':
    print(json.dumps(diagnose(), indent=2, sort_keys=True, allow_nan=False))
