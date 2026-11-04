#!/usr/bin/env python3
"""Re-audit a complete L3/L5 DAgger selection before considering holdout.

Usage: qualify-selection.py INDEX CHOICE_JSON NEW_RECEIPT

Requires complete baseline/candidate pairs for standard fetching and levels
1–5. This is deliberately separate from the disabled held-out runner. It
checks current selection and training artifacts, not unrecorded ancestry,
semantic scene independence, physical manipulation or previous holdout use.
"""
import hashlib
import importlib.util
import json
import math
import os
import subprocess
import sys
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[4]
LEVELS = Path(__file__).resolve().parent
BASE = PROJECT / 'build/flex/sim/levels-v2/pitch82'
TRAIN = BASE / 'search-dagger-l35-4workers'
PRIOR = BASE / 'search-dagger-4workers'
EXPECTED_SOURCES = {'teacher-L0': 96, 'teacher-L1': 96, 'teacher-L2': 96, 'teacher-L3': 96,
                    'teacher-L4': 256, 'teacher-L5': 128, 'student-L3': 128, 'student-L5': 128}


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, LEVELS / file)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def checksums(file):
    result = {}
    for line in file.read_text().splitlines():
        if line.startswith('\\') or '  ' not in line:
            raise ValueError(f'unsupported checksum record in {file}')
        sha, name = line.split('  ', 1)
        if len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
            raise ValueError(f'invalid checksum in {file}')
        path = Path(name)
        path = path if path.is_absolute() else PROJECT / path
        key = str(path.resolve())
        if key in result and result[key] != sha:
            raise ValueError(f'conflicting checksum for {path}')
        result[key] = sha
    return result


def require_pinned(manifest, path):
    if manifest.get(str(path.resolve())) != digest(path):
        raise ValueError(f'input absent or changed in manifest: {path}')


def model_files(model):
    receipt = json.loads((model / 'receipt.json').read_text())
    kernels = receipt.get('kernels')
    if not isinstance(kernels, dict) or len(kernels) < 5 or any(Path(name).name != name for name in kernels):
        raise ValueError(f'invalid model kernel receipt: {model}')
    files = [model / 'receipt.json', model / 'weights.bin', model / 'policy']
    if digest(model / 'weights.bin') != receipt['weightsSHA256'] or digest(model / 'policy') != receipt['binarySHA256']:
        raise ValueError(f'model receipt mismatch: {model}')
    for name, sha in kernels.items():
        path = model / 'kernels' / name
        if digest(path) != sha:
            raise ValueError(f'model kernel mismatch: {path}')
        files.append(path)
    return receipt, files


def source_shards():
    teacher = [BASE / f'kturn-L{level}' / f'shard-{shard}' for level in range(4) for shard in range(6)]
    teacher += [BASE / f'kturn-L{level}' / f'shard-{shard}' for level in (4, 5) for shard in range(8)]
    l3 = [PRIOR / 'dagger-L3' / f'shard-{shard}' for shard in range(4)]
    l5 = [TRAIN / 'dagger-L5' / f'shard-{shard}' for shard in range(4)]
    return teacher, l3, l5


def validate_sources(index, baseline, candidate):
    training_manifest = TRAIN / 'training-inputs.sha256'
    subprocess.run(['sha256sum', '-c', str(training_manifest)], cwd=PROJECT, check=True, stdout=subprocess.DEVNULL)
    pins = checksums(training_manifest)
    candidate_receipt, _ = model_files(candidate)
    baseline_receipt, baseline_files = model_files(baseline)
    for path in baseline_files + [TRAIN / 'data/data.bin', TRAIN / 'data/map.bin', TRAIN / 'source-audit.json',
                                  TRAIN / 'l3-labels-audit.json', TRAIN / 'l5-labels-audit.json', TRAIN / 'preservation-audit.json']:
        require_pinned(pins, path)
    if (candidate_receipt.get('taskFeedback') is not False or candidate_receipt.get('carryCue') is not True
            or candidate_receipt.get('initialWeightsSHA256') != baseline_receipt['weightsSHA256']
            or candidate_receipt.get('dataSHA256') != digest(TRAIN / 'data/data.bin')
            or candidate_receipt.get('memoryMapTargetsSHA256') != digest(TRAIN / 'data/map.bin')):
        raise ValueError('candidate receipt does not match audited initial weights, data and map')
    teacher, l3, l5 = source_shards()
    for shard in teacher + l3 + l5:
        for name in ('report.json', 'data.bin', 'map.bin'):
            require_pinned(pins, shard / name)
    command = ['python3', '-I', str(LEVELS / 'audit-multi-shards.py'), '--expect-games', '1024',
               '--expect-teacher-shards', '40', '--expect-student-shards', '8', '--teacher', *map(str, teacher),
               '--student-group', str(BASE / 'more1-s0'), '3', *map(str, l3),
               '--student-group', str(PRIOR / 'student-s0'), '5', *map(str, l5)]
    fresh = json.loads(subprocess.check_output(command, cwd=PROJECT, text=True))
    old = json.loads((TRAIN / 'source-audit.json').read_text())
    if fresh.get('status') != 'passed' or fresh.get('gamesBySourceLevel') != EXPECTED_SOURCES or fresh.get('sceneStartSHA256') != old.get('sceneStartSHA256'):
        raise ValueError('source audit does not match current training shards')
    for level, shards in ((3, l3), (5, l5)):
        output = json.loads(subprocess.check_output(['python3', '-I', str(LEVELS / 'audit-student-labels.py'), *map(str, shards)], cwd=PROJECT, text=True))
        if output.get('status') != 'passed' or output.get('games') != 128 or output.get('teacherStudentDisagreementSteps', 0) < 1:
            raise ValueError(f'invalid level-{level} student label audit')
    preservation = json.loads(subprocess.check_output(['python3', '-I', str(LEVELS / 'audit-mixed-students.py'), str(TRAIN / 'data'), '256', *map(str, teacher + l3 + l5)], cwd=PROJECT, text=True))
    if preservation.get('status') != 'passed' or preservation.get('studentGames') != 256:
        raise ValueError('student data/map preservation audit failed')
    return candidate_receipt, training_manifest, fresh


def reject_interventions(result, source):
    interventions = ('straightBiasHundredths', 'straightAfterSteps', 'sampledActions', 'ensembleMembers',
                     'ensembleUntilSteps', 'actionNoisePercent', 'noisySteps', 'selfImitationKeepSteps',
                     'selfImitationRows', 'doorPass', 'doorEarly')
    if any(field in result for field in interventions) or result.get('farBricks') is not False or result.get('sweepTeacher') is not False:
        raise ValueError(f'non-default or unverified actor intervention: {source}')


def strict_games(root, model, level, selection, heldout):
    games = selection.load(root, model, level)
    selection.check_score(root, selection.summary(games))
    if len(list(root.glob('*/[0-9]*/result.json'))) != 32 or len({p.parent.parent for p in root.glob('*/[0-9]*/result.json')}) != 4:
        raise ValueError(f'expected four complete parts in {root}')
    for file in root.glob('*/[0-9]*/result.json'):
        result = json.loads(file.read_text())
        reject_interventions(result, file.parent)
        seed = result['seed']
        game = file.parent
        _, rows, start, _ = games[seed]
        if (result.get('game') != 'fetch' or result.get('controller') != 'native neural policy'
                or result.get('exploreTeacher') is not False or result.get('carryCue') is not True
                or result.get('taskEventHint') is not False or result.get('suppliedMap') is not False
                or result.get('maximumBrickDistanceM') != 0.35 or type(result.get('deliveries')) is not int
                or result['deliveries'] < 0 or type(result.get('backForthSteps')) is not int
                or not 0 <= result['backForthSteps'] <= 300
                or result['backForthSteps'] != heldout.backforth_steps(rows, start['robot'])):
            raise ValueError(f'invalid task or back-and-forth trace: {game}')
        expected_placement = {1: 'in view', 2: 'just off view', 3: 'same room out of view', 4: 'doorway drill', 5: 'other room'}
        if level in expected_placement and result.get('levelPlacement') != expected_placement[level]:
            raise ValueError(f'wrong placement: {game}')
    return games


def metric_observations(level, baseline, candidate, doorway=None):
    if candidate['games'] != 32 or baseline['games'] != 32:
        raise ValueError('selection needs 32 games per player')
    if not 0 <= candidate['backForthShare'] <= 1 or not 0 <= baseline['backForthShare'] <= 1:
        raise ValueError('invalid back-and-forth share')
    if level == 4 and (doorway is None or not 0 <= doorway[1] <= doorway[0]):
        raise ValueError('invalid level 4 doorway accounting')
    return {'deliveryReliabilityAtLeast90Percent': candidate['gamesWithDelivery'] >= 29,
            'firstPickupAtLeast90Percent': candidate['firstReturnGames'] >= 29 if level == 3 else None,
            'backForthBelow2Percent': candidate['backForthShare'] < 0.02,
            'doorwayAtLeast80Percent': bool(doorway[0]) and doorway[1] / doorway[0] >= 0.8 if level == 4 else None,
            'deliveryRateNoLowerThanBaseline': candidate['deliveriesPerMinute'] >= baseline['deliveriesPerMinute']}


def pair_evidence(level, index, baseline, candidate, selection, heldout, goal):
    label = 'standard' if level == 0 else f'L{level}'
    root = TRAIN / f'selection-{label}'
    manifest = root / f'pair-s{index}.inputs.sha256'
    saved = root / f'pair-s{index}.audit.json'
    if not manifest.is_file() or not saved.is_file():
        raise ValueError(f'missing paired selection evidence: {label}')
    subprocess.run(['sha256sum', '-c', str(manifest)], cwd=PROJECT, check=True, stdout=subprocess.DEVNULL)
    pins = checksums(manifest)
    _, left_files = model_files(baseline)
    _, right_files = model_files(candidate)
    required = left_files + right_files + [PROJECT / 'build/flex/control/control', PROJECT / 'build/flex/control/simulator',
                PROJECT / 'build/flex/rocm-runtime/libamdhip64.so', PROJECT / 'datasets/visual-control/chase-v1/evaluate.sh',
                LEVELS / 'audit-selection.py', LEVELS / ('selection-pair-extra.sh' if level in (0, 2) else 'selection-pair-l35.sh'),
                TRAIN / 'source-audit.json', TRAIN / 'training-inputs.sha256']
    for g in range(32):
        layout = 12 + g % 6 if level < 4 else 13 + 2 * (g % 3)
        scene = PROJECT / 'build/flex/sim/expanded-rooms-v1/scenes' / str(layout) / str(g % 16)
        required.extend(scene / name for name in ('case.json', 'environment.bin', 'layout.json'))
    for path in required:
        require_pinned(pins, path)
    left_root, right_root = root / f'baseline-s{index}', root / f'student-s{index}'
    left = strict_games(left_root, baseline, level, selection, heldout)
    right = strict_games(right_root, candidate, level, selection, heldout)
    for seed in left:
        if left[seed][2:] != right[seed][2:] or left[seed][0].get('levelPlacement') != right[seed][0].get('levelPlacement'):
            raise ValueError(f'unmatched paired selection game {label}, seed {seed}')
    a, b = selection.summary(left), selection.summary(right)
    door, left_door = None, None
    if level == 4:
        pairs = []
        for player in (left_root, right_root):
            values = []
            for file in sorted(player.glob('*/[0-9]*/result.json')):
                directory = file.parent
                events = [json.loads(line) for line in (directory / 'chase.jsonl').read_text().splitlines()]
                values.append(goal.doorway(events, directory))
            pairs.append((sum(x[0] for x in values), sum(x[1] for x in values)))
        left_door, door = pairs
    observations = metric_observations(level, a, b, door)
    recorded = json.loads(saved.read_text())
    if recorded.get('status') != 'paired selection audit passed' or recorded.get('level') != level or recorded.get('seeds') != [7800000, 7800031] or recorded.get('baseline') != a or recorded.get('student') != b:
        raise ValueError(f'saved selection audit disagrees with current traces: {label}')
    evidence = hashlib.sha256()
    for player in (left_root, right_root):
        score = root / f'score-{player.name}.json'
        evidence.update(f'{score.relative_to(root)}\0{digest(score)}\n'.encode())
        for part in sorted(p for p in player.iterdir() if p.is_dir() and p.name.isdecimal()):
            for path in [player / f'{part.name}.log', part / 'policy.log', *sorted((part / 'policy').rglob('*'))]:
                if path.is_file():
                    evidence.update(f'{path.relative_to(root)}\0{digest(path)}\n'.encode())
        for file in sorted(player.glob('*/[0-9]*/result.json')):
            for name in ('result.json', 'decisions.jsonl', 'chase.jsonl', 'scene/case.json', 'scene/environment.bin', 'native.log'):
                path = file.parent / name
                evidence.update(f'{path.relative_to(root)}\0{digest(path)}\n'.encode())
    subprocess.run(['sha256sum', '-c', str(manifest)], cwd=PROJECT, check=True, stdout=subprocess.DEVNULL)
    return {'level': label, 'baseline': a, 'candidate': b, 'baselineDoorway': left_door, 'candidateDoorway': door,
            'baselineLongSearchReturnShare': sum(goal.long_search_share(game[1]) for game in left.values()) / 32,
            'candidateLongSearchReturnShare': sum(goal.long_search_share(game[1]) for game in right.values()) / 32,
            'selectionObservations': observations,
            'manifestSHA256': digest(manifest), 'auditSHA256': digest(saved), 'traceInventorySHA256': evidence.hexdigest(),
            'runtime': {name: digest(PROJECT / 'build/flex/control' / name) for name in ('control', 'simulator')}}


def validate_choice(chosen, candidate, training_manifest, audit_paths):
    labels = {'standard', 'L1', 'L2', 'L3', 'L4', 'L5'}
    if (chosen.get('schema') != 'puppybot.selection-choice.v1' or not isinstance(chosen.get('rationale'), str)
            or not chosen['rationale'].strip() or chosen.get('selectedWeightsSHA256') != digest(candidate / 'weights.bin')
            or chosen.get('candidateReceiptSHA256') != digest(candidate / 'receipt.json')
            or chosen.get('trainingManifestSHA256') != digest(training_manifest)):
        raise ValueError('choice does not bind the selected candidate, receipt and training manifest')
    audits = chosen.get('selectionAuditSHA256')
    if not isinstance(audits, dict) or set(audits) != labels or set(audit_paths) != labels:
        raise ValueError('choice must bind all six paired selection audits')
    for label, sha in audits.items():
        if sha != digest(audit_paths[label]):
            raise ValueError(f'choice refers to changed {label} selection audit')


def main():
    if len(sys.argv) != 4 or sys.argv[1] not in ('0', '1', '2'):
        raise SystemExit(__doc__)
    index, choice, output = int(sys.argv[1]), Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve()
    if output.exists():
        raise ValueError(f'refusing to overwrite: {output}')
    baseline, candidate = PRIOR / f'student-s{index}', TRAIN / f'student-s{index}'
    # Do not hash multi-gigabyte datasets until every paired selection exists.
    for label in ('standard', 'L1', 'L2', 'L3', 'L4', 'L5'):
        root = TRAIN / f'selection-{label}'
        if not (root / f'pair-s{index}.inputs.sha256').is_file() or not (root / f'pair-s{index}.audit.json').is_file():
            raise ValueError(f'missing complete paired selection evidence: {label}')
    # The existing lean logs do not record exact control argv or the actor's
    # carry-cue input. In particular --search-cue changes that input without
    # a result.json flag. File hashes alone cannot establish its absence.
    # Refuse to create a qualification receipt until an independent argv and
    # actor-input attestation verifier is implemented and exercised.
    raise ValueError('selection qualification disabled: exact argv and actor-input attestation is not implemented')
    choice_bytes = choice.read_bytes()
    choice_sha = hashlib.sha256(choice_bytes).hexdigest()
    chosen = json.loads(choice_bytes)
    audit_paths = {label: TRAIN / f'selection-{label}' / f'pair-s{index}.audit.json'
                   for label in ('standard', 'L1', 'L2', 'L3', 'L4', 'L5')}
    validate_choice(chosen, candidate, TRAIN / 'training-inputs.sha256', audit_paths)
    os.environ['PUPPYBOT_PROJECT'] = str(PROJECT)
    receipt, training_manifest, source = validate_sources(index, baseline, candidate)
    selection = module('selection', 'audit-selection.py')
    heldout = module('heldout', 'audit-heldout.py')
    goal = module('goal', 'goal-report.py')
    results = [pair_evidence(level, index, baseline, candidate, selection, heldout, goal) for level in range(6)]
    if len({json.dumps(pair['runtime'], sort_keys=True) for pair in results}) != 1:
        raise ValueError('selection pairs use different control or simulator binaries')
    if digest(choice) != choice_sha:
        raise ValueError('selection choice changed during verification')
    validate_choice(chosen, candidate, TRAIN / 'training-inputs.sha256', audit_paths)
    subprocess.run(['sha256sum', '-c', str(training_manifest)], cwd=PROJECT, check=True, stdout=subprocess.DEVNULL)
    report = {'status': 'selection_artifacts_verified', 'candidateWeightsSHA256': receipt['weightsSHA256'],
              'candidateReceiptSHA256': digest(candidate / 'receipt.json'), 'trainingManifestSHA256': digest(training_manifest),
              'sourceAuditSHA256': digest(TRAIN / 'source-audit.json'), 'sourceSceneStartSHA256': source['sceneStartSHA256'],
              'selectionChoiceSHA256': choice_sha, 'qualifierSHA256': digest(Path(__file__)), 'pairs': results,
              'limitations': ['selection-only evidence; no claim about prior held-out use or complete ancestry',
                              'virtual pickup/docking only; physical delivery is not measured',
                              'paired baselines are not the exploring teacher; teacher comparison remains required on held-out games',
                              'input hashes do not independently prove preregistration time or semantic independence']}
    with output.open('x') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(f'Selection artifacts verified; receipt written to {output}. Held-out runner remains disabled.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
        raise SystemExit(f'Selection not qualified: {error}')
