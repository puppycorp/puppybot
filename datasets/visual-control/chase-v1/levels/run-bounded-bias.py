#!/usr/bin/env python3
"""Paired bounded-search-bias experiment on training layouts, not held-out.

Usage: run-bounded-bias.py pilot
       run-bounded-bias.py select|validate LEVEL    (LEVEL 1,3,4,5)
Prepare the isolated build first; prepare fresh-seed scenes before validation.
Both arms use the same fixed-epoch treatment model and raw-logit binary. The
control threshold is outside the 300-action horizon; treatment uses 70. A
successful pilot with at least one changed action is required before expansion.
Run only on an otherwise idle GPU. Simulator carry state is not a physical sensor.
"""
import importlib.util
import json
import math
import os
import re
import struct
import subprocess
import sys
from collections import defaultdict
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[4]
S = PROJECT / 'datasets/visual-control/chase-v1/levels'
P = PROJECT / 'build/flex/sim/levels-v2/pitch82'
O = P / 'search-dagger-l4-matched'
BUILD = O / 'bounded-bias-build'
DEV = O / 'route-factorial-scenes'
VALIDATION = O / 'bounded-bias-validation-scenes'
MODEL = O / 'epoch8-pair/treatment'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


base = load('route_runner', S / 'run-route-factorial.py')
builder = load('bias_builder', S / 'prepare-bounded-bias.py')
validation = load('validation', S / 'prepare-bias-validation.py')


def backforth_steps(rows, start):
    poses = [start] + [row['state']['pose'] for row in rows[:-1]]
    drive = [(row['action'][1] > 0) - (row['action'][1] < 0) for row in rows]
    steps, marked = 0, -1
    for t in range(20, len(rows)):
        flips = sum(drive[k] * drive[k - 1] < 0 for k in range(t - 19, t))
        turn = abs((poses[t][2] - poses[t - 20][2] + math.pi) % (2 * math.pi) - math.pi)
        if flips >= 4 and math.dist(poses[t][:2], poses[t - 20][:2]) < .25 and turn < math.radians(45):
            steps += t - max(marked, t - 20); marked = t
    return steps


def eligible_steps(rows, events, threshold):
    if not events or events[0].get('event') != 'start' or events[0].get('step') != 0:
        raise ValueError('invalid initial placement event')
    placement = 0; deliveries = 0; carrying = False; eligible = 0; delivery_steps = []
    for index, row in enumerate(rows):
        if not carrying and threshold <= index - placement < threshold + 30:
            eligible += 1
        state = row['state']['findReturn']; consumed, count = state['consumedIndex'], state['deliveries']
        if type(consumed) is not int or type(count) is not int or count < deliveries or count > deliveries + 1:
            raise ValueError('invalid simulator pickup/delivery sequence')
        if not carrying and consumed >= 0:
            carrying = True
        if count > deliveries:
            deliveries = count; carrying = False; placement = index + 1; delivery_steps.append(placement)
    logged_steps = [event.get('step') for event in events if event.get('event') == 'delivery']
    if logged_steps != delivery_steps:
        raise ValueError('placement events disagree with delivery state transitions')
    return eligible


def validate_game(condition, arm, output, level):
    if base.selection.snapshot(output / 'policy', MODEL) != base.sha(MODEL / 'weights.bin'):
        raise ValueError('snapshot differs from fixed policy')
    game = output / str(condition['seed']); result = json.loads((game / 'result.json').read_text())
    expected = {'seed': condition['seed'], 'game': 'fetch', 'controller': 'native neural policy',
                'level': level, 'levelPlacement': {1: 'in view', 3: 'same room out of view', 4: 'doorway drill', 5: 'other room'}[level],
                'steps': 300, 'actionSeconds': 60, 'blackout': False, 'maximumBrickDistanceM': .35,
                'farBricks': False, 'exploreTeacher': False, 'sweepTeacher': False,
                'suppliedMap': False, 'taskEventHint': False, 'carryCue': True,
                'policyWeightsSHA256': base.sha(MODEL / 'weights.bin'), 'straightBiasHundredths': 50,
                'straightAfterSteps': 1000 if arm == 'control' else 70, 'straightWindowSteps': 30}
    if any((result.get(k) is not v if type(v) is bool else result.get(k) != v) for k, v in expected.items()):
        raise ValueError(f'result declaration differs: {game}')
    forbidden = ('doorPass', 'doorEarly', 'sampledActions', 'actionNoisePercent', 'ensembleMembers', 'ensembleUntilSteps')
    if any(key in result for key in forbidden):
        raise ValueError('unexpected intervention')
    eligible, changed = result.get('straightEligibleSteps'), result.get('straightChangedSteps')
    if (type(eligible) is not int or type(changed) is not int or not 0 <= changed <= eligible <= 300
            or (arm == 'control' and eligible != 0)):
        raise ValueError('invalid intervention counts')
    for name, key in (('case.json', 'caseSHA256'), ('environment.bin', 'environmentSHA256')):
        if base.sha(game / 'scene' / name) != condition[key]:
            raise ValueError('scene differs')
    native = (game / 'native.log').read_text(errors='replace')
    policy_log = (output / 'policy.log').read_text(errors='replace')
    if re.search(r'\btimed out\b|\btimeout\b', native + '\n' + policy_log, re.I):
        raise ValueError('timeout in game')
    events = [json.loads(line) for line in (game / 'chase.jsonl').read_text().splitlines()]
    if not events or events[0].get('event') != 'start':
        raise ValueError('missing start')
    start = events[0]; robot, brick = start['robot'], start['brick']
    if (not isinstance(robot, list) or len(robot) != 3 or not isinstance(brick, list) or len(brick) != 2
            or any(type(x) not in (int, float) or not math.isfinite(x) for x in robot + brick)
            or any(not math.isclose(a, b, abs_tol=1e-6, rel_tol=0) for a, b in zip(robot, condition['startPose']))):
        raise ValueError('invalid start or target position')
    rows = [json.loads(line) for line in (game / 'decisions.jsonl').read_text().splitlines()]
    if len(rows) != 300 or any(b['step'] != a['step'] + 10 for a, b in zip(rows, rows[1:])):
        raise ValueError('incomplete or nonconsecutive actions')
    states = [row['state'] for row in rows]
    if any(s.get('trainingOracle', {}).get('enabled') is not False or s['trainingOracle'].get('queries') != 0 for s in states):
        raise ValueError('oracle enabled or queried')
    if eligible_steps(rows, events, 1000 if arm == 'control' else 70) != eligible:
        raise ValueError('eligible count differs from recorded placement and carry transitions')
    actions = [row['action'] for row in rows]
    if any(not isinstance(a, list) or len(a) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1 for v in a) for a in actions):
        raise ValueError('invalid action')
    classes = [(-.6, 1), (0, 1), (.6, 1), (-.6, -1), (0, -1), (.6, -1), (0, 0)]
    if any(not any(all(math.isclose(v, candidate, rel_tol=0, abs_tol=1e-6) for v, candidate in zip(a, c)) for c in classes) for a in actions):
        raise ValueError('action is not a supported discrete drive class')
    deliveries = result.get('deliveries'); backforth = result.get('backForthSteps')
    if (type(deliveries) is not int or not 0 <= deliveries <= 300 or type(backforth) is not int or not 0 <= backforth <= 300
            or sum(event.get('event') == 'delivery' for event in events) != deliveries):
        raise ValueError('invalid delivery or back-and-forth result')
    if eligible > min(300, 30 * (deliveries + 1)):
        raise ValueError('eligible count exceeds bounded per-search windows')
    poses = [robot] + [s['pose'] for s in states]; base.coverage.geometry(poses)
    if backforth_steps(rows, robot) != backforth:
        raise ValueError('back-and-forth result differs from action and pose trace')
    pickup = next((i + 1 for i, state in enumerate(states) if state['findReturn']['phase'] == 'return'), None)
    search = base.coverage.geometry(poses[:(pickup if pickup is not None else 300) + 1])
    data = (game / 'scene/environment.bin').read_bytes(); count = struct.unpack_from('<q', data, 8)[0]
    walls = {struct.unpack_from('<d', data, 256 + i * 128 + 48)[0] for i in range(count)
             if data[256 + i * 128:256 + i * 128 + 48].startswith(b'Wall.partition')}
    if len(walls) != 1:
        raise ValueError('ambiguous partition')
    wall = next(iter(walls)); other = (brick[0] > wall) != (robot[0] > wall)
    entry = next((i + 1 for i, p in enumerate(poses[1:]) if (p[0] > wall) == (brick[0] > wall)), None) if other else None
    return {'condition': condition['name'], 'layout': condition['layout'], 'heading': condition['startPose'][2],
            'seed': condition['seed'], 'level': level, 'arm': arm, 'startPose': robot, 'initialBrick': brick,
            'environmentSHA256': condition['environmentSHA256'], 'targetOtherRoom': other, 'firstEntryAction': entry,
            'firstPickupAction': pickup, 'deliveries': deliveries, 'backForthSteps': backforth,
            'biasEligibleSteps': eligible, 'biasChangedSteps': changed, 'searchRoute': search,
            'decisionsSHA256': base.sha(game / 'decisions.jsonl'), 'resultSHA256': base.sha(game / 'result.json')}, actions


def pair_check(control, treatment, control_actions, treatment_actions):
    for key in ('condition', 'seed', 'level', 'startPose', 'initialBrick', 'environmentSHA256'):
        if control[key] != treatment[key]:
            raise ValueError(f'paired input mismatch: {key}')
    if control_actions[:70] != treatment_actions[:70]:
        raise ValueError('paired actions diverged before intervention window')
    divergence = next((i + 1 for i, (a, b) in enumerate(zip(control_actions, treatment_actions)) if a != b), None)
    if bool(treatment['biasChangedSteps']) != (divergence is not None):
        raise ValueError('reported bias action changes disagree with paired action sequences')
    return divergence


def main():
    if len(sys.argv) == 2 and sys.argv[1] == 'pilot':
        stage, level = 'pilot', 5
    elif len(sys.argv) == 3 and sys.argv[1] in ('select', 'validate') and sys.argv[2] in ('1', '3', '4', '5'):
        stage, level = sys.argv[1], int(sys.argv[2])
    else:
        raise SystemExit(__doc__)
    os.chdir(PROJECT); scenes = VALIDATION if stage == 'validate' else DEV
    output = O / f'bounded-bias-{stage}-L{level}'
    with base.acquire_lock(P / '.l4-matched.lock'):
        base.require_new_output(output); base.require_capacity(P, 12 * 1024**3)
        build_manifest = json.loads((BUILD / 'inputs.json').read_text()); builder.verify(BUILD, build_manifest)
        base.package.verify(O / 'control-s0', O / 'treatment-s0', O / 'epoch8-pair')
        checked = base.training.audit(P / 'search-dagger-l35-4workers/student-s0', O / 'control-s0', O / 'treatment-s0')
        if checked != json.loads((O / 'training-match.json').read_text()): raise ValueError('training match changed')
        subprocess.run(['/usr/bin/sha256sum', '-c', str(O / 'training-inputs.sha256')], check=True, stdout=subprocess.DEVNULL)
        base.SCENES = scenes
        if stage == 'validate':
            base.factorial.SEEDS = validation.SEEDS
            files = validation.inventory(); current = {str(p): base.sha(p) for p in sorted(files)}
            inventory = json.loads((scenes / 'inventory.json').read_text())
            if inventory['seeds'] != list(validation.SEEDS) or inventory['shards'] != current:
                raise ValueError('validation seed inventory changed')
        manifest = json.loads((scenes / 'conditions.json').read_text()); base.factorial.verify(base.factorial.SCENES, scenes, manifest)
        conditions = manifest['conditions']
        if stage == 'pilot':
            conditions = [c for c in conditions if (c['layout'], c['startPose'][2], c['seed']) == (15, .42, 7800001)]
            if len(conditions) != 1: raise ValueError('targeted pilot missing')
        else:
            pilot_root = O / 'bounded-bias-pilot-L5'
            pilot = json.loads((pilot_root / 'report.json').read_text())
            if (pilot.get('status') != 'diagnostic_only' or pilot.get('totalChangedSteps', 0) < 1
                    or pilot.get('controlSHA256') != base.sha(BUILD / 'control')
                    or pilot.get('policySHA256') != base.sha(MODEL / 'weights.bin')):
                raise ValueError('matching pilot has not established a changed action')
            for path, expected in json.loads((pilot_root / 'inputs.json').read_text()).items():
                if base.sha(Path(path)) != expected:
                    raise ValueError('pilot input changed')
            dev_manifest = json.loads((DEV / 'conditions.json').read_text())
            targets = [c for c in dev_manifest['conditions'] if (c['layout'], c['startPose'][2], c['seed']) == (15, .42, 7800001)]
            if len(targets) != 1:
                raise ValueError('pilot condition missing')
            c = targets[0]; parent = pilot_root / c['name']
            left, left_actions = validate_game(c, 'control', parent / 'control/run', 5)
            right, right_actions = validate_game(c, 'treatment', parent / 'treatment/run', 5)
            pair_check(left, right, left_actions, right_actions)
            if right['biasChangedSteps'] < 1:
                raise ValueError('pilot action change is not supported by its game')
        inputs = base.source_files(manifest)
        extra_inputs = (Path(__file__), S / 'bounded-bias-source.py', S / 'prepare-bounded-bias.py', S / 'prepare-bias-validation.py',
                        BUILD / 'inputs.json', BUILD / 'control', BUILD / 'bounded-probe',
                        PROJECT / 'build/flex/sim/puppybot.bin', PROJECT / 'puppybot.json')
        for path in extra_inputs:
            inputs[str(path)] = base.sha(path)
        output.mkdir(); (output / 'inputs.json').write_text(json.dumps(inputs, sort_keys=True, indent=2) + '\n')
        env = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'PUPPYBOT_PROJECT': str(PROJECT),
               'LD_LIBRARY_PATH': str(PROJECT / 'build/flex/rocm-runtime'), 'SDL_VIDEODRIVER': 'offscreen'}
        games = []; pairs = []; placements = {}
        for condition in conditions:
            base.require_capacity(P, 8 * 1024**3); pair = []; action_pair = []
            for arm in ('control', 'treatment'):
                current = base.source_files(manifest)
                for path in extra_inputs: current[str(path)] = base.sha(path)
                if current != inputs: raise ValueError('experiment input changed before arm')
                parent = output / condition['name'] / arm; parent.mkdir(parents=True)
                game_output = parent / 'run'; monitor = parent / 'monitor'; monitor.mkdir()
                command = [str(BUILD / 'control'), 'run', '--chase', '--scene-catalog', str(scenes / condition['catalog']),
                           '--output', str(game_output), '--episodes', '1', '--horizon', '300', '--seed', str(condition['seed']),
                           '--lean', '--wheel-odometry', '--policy', str(MODEL), '--fetch', '--level', str(level), '--camera-pitch', '82',
                           '--straight-bias', '50', '--straight-after', '1000' if arm == 'control' else '70']
                (parent / 'command.json').write_text(json.dumps(command, indent=2) + '\n')
                status = base.hidden.supervise(command, monitor, env, 180); base.require_success(status, parent)
                data, actions = validate_game(condition, arm, game_output, level)
                pair.append(data); action_pair.append(actions); games.append(data)
                current = base.source_files(manifest)
                for path in extra_inputs:
                    current[str(path)] = base.sha(path)
                if current != inputs: raise ValueError('experiment input changed')
            divergence = pair_check(*pair, *action_pair)
            if level == 5:
                key = (condition['layout'], condition['seed'])
                if key in placements and placements[key] != pair[0]['initialBrick']:
                    raise ValueError('level-5 placement changed across headings')
                placements[key] = pair[0]['initialBrick']
            pairs.append({'condition': condition['name'], 'firstDifferentAction': divergence,
                          'treatmentBiasChangedSteps': pair[1]['biasChangedSteps']})
        base.factorial.verify(base.factorial.SCENES, scenes, manifest); builder.verify(BUILD, build_manifest)
        base.package.verify(O / 'control-s0', O / 'treatment-s0', O / 'epoch8-pair')
        groups = defaultdict(list)
        for game in games: groups[(game['layout'], game['heading'], game['arm'])].append(game)
        summary = []
        for (layout, heading, arm), items in sorted(groups.items()):
            entry_times = [x['firstEntryAction'] for x in items if x['firstEntryAction'] is not None]
            summary.append({'layout': layout, 'heading': heading, 'arm': arm, 'games': len(items),
                            'deliveries': sum(x['deliveries'] for x in items),
                            'gamesWithDelivery': sum(x['deliveries'] > 0 for x in items),
                            'firstPickups': sum(x['firstPickupAction'] is not None for x in items),
                            'targetOtherRoom': sum(x['targetOtherRoom'] for x in items),
                            'firstEntries': len(entry_times),
                            'meanEntryActionAmongEntries': sum(entry_times) / len(entry_times) if entry_times else None,
                            'backForthSteps': sum(x['backForthSteps'] for x in items),
                            'backForthShare': sum(x['backForthSteps'] for x in items) / (len(items) * 300),
                            'biasEligibleSteps': sum(x['biasEligibleSteps'] for x in items),
                            'biasChangedSteps': sum(x['biasChangedSteps'] for x in items)})
        report = {'status': 'diagnostic_only', 'stage': stage, 'level': level, 'groups': summary, 'pairs': pairs, 'games': games,
                  'totalChangedSteps': sum(g['biasChangedSteps'] for g in games if g['arm'] == 'treatment'),
                  'controlSHA256': base.sha(BUILD / 'control'), 'policySHA256': base.sha(MODEL / 'weights.bin'),
                  'scope': 'training-layout selection; single policy and rebuilt binary; 30-action bias window per search; eligible steps recomputed from task-state transitions; exact changed-action count is not independently reconstructed without raw logits; L1/L3/L4 placements can depend on heading, so only the arms within a condition are matched; simulator carry cue is not a physical sensor; no heldout, actor-input attestation or physical-hardware claim'}
        (output / 'report.json').write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
        print(json.dumps({'status': report['status'], 'games': len(games), 'changedSteps': report['totalChangedSteps'], 'output': str(output)}))


if __name__ == '__main__': main()
