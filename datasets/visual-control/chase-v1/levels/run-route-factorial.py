#!/usr/bin/env python3
"""Run paired fixed-epoch training-layout route diagnostics, never held-out.

Prepare inputs first with prepare-route-factorial.py, and run only on an idle
GPU. Output is one new experiment directory; failures retain partial work.
This is diagnostic, not a qualification or physical-robot evaluation.
The carry cue comes from simulator task state, not a physical sensor.
"""
import fcntl
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[4]
S = PROJECT / 'datasets/visual-control/chase-v1/levels'
P = PROJECT / 'build/flex/sim/levels-v2/pitch82'
O = P / 'search-dagger-l4-matched'
SCENES = O / 'route-factorial-scenes'
OUTPUT = O / 'selection-route-factorial'
PACKAGE = O / 'epoch8-pair'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec); spec.loader.exec_module(obj)
    return obj


factorial = module('factorial', S / 'prepare-route-factorial.py')
coverage = module('coverage', S / 'route-coverage.py')
package = module('package', S / 'package-matched-epoch8.py')
training = module('training', S / 'audit-matched-training.py')
selection = module('selection', S / 'audit-selection.py')
hidden = module('supervised_trial', PROJECT / 'flex/tests/run-physical-hidden-trial.py')


def sha(path):
    return coverage.digest(path)


def acquire_lock(path):
    lock = path.open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BaseException:
        lock.close()
        raise
    return lock


def require_capacity(path, minimum):
    if shutil.disk_usage(path).free < minimum:
        raise RuntimeError(f'insufficient free space at {path}')


def require_new_output(path):
    if path.exists() or path.is_symlink():
        raise ValueError(f'output already exists; preserve it: {path}')


def require_success(status, parent):
    if status['signal'] is not None or status['timedOut'] or status['clientExit'] != 0 or status['remainingWorkersTerminated']:
        raise RuntimeError(f'run failed or required cleanup; inspect {parent}')


def source_files(manifest):
    files = [PROJECT / 'build/flex/control/control', PROJECT / 'build/flex/control/simulator',
             PROJECT / 'build/flex/rocm-runtime/libamdhip64.so', Path(__file__),
             S / 'prepare-route-factorial.py', S / 'route-coverage.py', S / 'package-matched-epoch8.py',
             S / 'audit-matched-training.py', S / 'audit-selection.py',
             PROJECT / 'flex/tests/run-physical-hidden-trial.py', PROJECT / 'flex/tests/run-physical-rescan-trial.py',
             PROJECT / 'flex/tests/run-physical-hybrid-trial.py',
             O / 'training-inputs.sha256', O / 'training-match.json', SCENES / 'conditions.json', PACKAGE / 'manifest.json']
    for name in ('control', 'treatment'):
        model = PACKAGE / name
        files.extend(model / f for f in ('weights.bin', 'policy', 'receipt.json', 'training-receipt.json'))
        files.extend(sorted((model / 'kernels').iterdir()))
    for row in manifest['conditions']:
        scene = SCENES / row['catalog'] / '0'
        files.extend(scene / f for f in ('case.json', 'environment.bin', 'layout.json'))
    return {str(path): sha(path) for path in files}


def validate_game(condition, arm, output):
    model = PACKAGE / arm
    if selection.snapshot(output / 'policy', model) != sha(model / 'weights.bin'):
        raise ValueError('policy snapshot does not match')
    game = output / str(condition['seed'])
    result = json.loads((game / 'result.json').read_text())
    expected = {'seed': condition['seed'], 'game': 'fetch', 'controller': 'native neural policy',
                'level': 5, 'levelPlacement': 'other room', 'steps': 300, 'actionSeconds': 60,
                'blackout': False, 'farBricks': False, 'exploreTeacher': False, 'sweepTeacher': False,
                'suppliedMap': False, 'taskEventHint': False, 'carryCue': True,
                'policyWeightsSHA256': sha(model / 'weights.bin')}
    if any(result.get(key) != value for key, value in expected.items()):
        raise ValueError(f'result declaration differs: {game}')
    forbidden = ('straightBiasHundredths', 'straightAfterSteps', 'doorPass', 'doorEarly', 'sampledActions',
                 'actionNoisePercent', 'ensembleMembers', 'ensembleUntilSteps')
    if any(key in result for key in forbidden):
        raise ValueError(f'unexpected intervention: {game}')
    for file, key in (('case.json', 'caseSHA256'), ('environment.bin', 'environmentSHA256')):
        if sha(game / 'scene' / file) != condition[key]:
            raise ValueError(f'game scene differs: {game}/{file}')
    native = (game / 'native.log').read_text(errors='replace')
    policy_log = (output / 'policy.log').read_text(errors='replace')
    if re.search(r'\btimed out\b|\btimeout\b', native + '\n' + policy_log, re.I):
        raise ValueError(f'timeout in game: {game}')
    data = coverage.game(game)
    if any(not math.isclose(actual, wanted, rel_tol=0, abs_tol=1e-6)
           for actual, wanted in zip(data['startPose'], condition['startPose'])):
        raise ValueError(f'actual start pose differs: {game}')
    data['condition'] = condition['name']; data['layout'] = condition['layout']; data['heading'] = condition['startPose'][2]
    data['arm'] = arm
    return data


def paired_check(control, treatment):
    for key in ('condition', 'seed', 'startPose', 'initialBrick', 'environmentSHA256'):
        if control[key] != treatment[key]:
            raise ValueError(f'paired scene, start or placement differs: {key}')


def main():
    if len(sys.argv) != 1:
        raise SystemExit(__doc__)
    os.chdir(PROJECT)
    with acquire_lock(P / '.l4-matched.lock'):
        require_new_output(OUTPUT)
        require_capacity(P, 12 * 1024**3)
        manifest = json.loads((SCENES / 'conditions.json').read_text())
        factorial.verify(factorial.SCENES, SCENES, manifest)
        package.verify(O / 'control-s0', O / 'treatment-s0', PACKAGE)
        checked = training.audit(P / 'search-dagger-l35-4workers/student-s0', O / 'control-s0', O / 'treatment-s0')
        if checked != json.loads((O / 'training-match.json').read_text()):
            raise ValueError('training match changed')
        subprocess.run(['/usr/bin/sha256sum', '-c', str(O / 'training-inputs.sha256')], check=True, stdout=subprocess.DEVNULL)
        inputs = source_files(manifest)
        OUTPUT.mkdir()
        (OUTPUT / 'inputs.json').write_text(json.dumps(inputs, sort_keys=True, indent=2) + '\n')
        env = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'PUPPYBOT_PROJECT': str(PROJECT),
               'LD_LIBRARY_PATH': str(PROJECT / 'build/flex/rocm-runtime'), 'SDL_VIDEODRIVER': 'offscreen'}
        all_games = []; placements = {}
        for condition in manifest['conditions']:
            require_capacity(P, 8 * 1024**3)
            pair = []
            for arm in ('control', 'treatment'):
                parent = OUTPUT / condition['name'] / arm; parent.mkdir(parents=True)
                game_output = parent / 'run'; monitor = parent / 'monitor'; monitor.mkdir()
                command = [str(PROJECT / 'build/flex/control/control'), 'run', '--chase', '--scene-catalog',
                           str(SCENES / condition['catalog']), '--output', str(game_output), '--episodes', '1',
                           '--horizon', '300', '--seed', str(condition['seed']), '--lean', '--wheel-odometry',
                           '--policy', str(PACKAGE / arm), '--fetch', '--level', '5', '--camera-pitch', '82']
                (parent / 'command.json').write_text(json.dumps(command, indent=2) + '\n')
                status = hidden.supervise(command, monitor, env, 180)
                require_success(status, parent)
                data = validate_game(condition, arm, game_output); pair.append(data); all_games.append(data)
                if source_files(manifest) != inputs:
                    raise ValueError('evaluation inputs changed')
            paired_check(*pair)
            # Placement should not change when yaw alone changes. Stop if it does.
            placement_key = (condition['layout'], condition['seed'])
            if placement_key in placements and placements[placement_key] != pair[0]['initialBrick']:
                raise ValueError('level-5 placement changed across headings')
            placements[placement_key] = pair[0]['initialBrick']
        factorial.verify(factorial.SCENES, SCENES, manifest)
        package.verify(O / 'control-s0', O / 'treatment-s0', PACKAGE)
        grouped = defaultdict(list)
        for game in all_games:
            grouped[(game['layout'], game['heading'], game['arm'])].append(game)
        groups = []
        for (layout, heading, arm), games in sorted(grouped.items()):
            entered = [g['firstEntryAction'] for g in games if g['firstEntryAction'] is not None]
            groups.append({'layout': layout, 'heading': heading, 'arm': arm, 'games': len(games),
                           'entered': len(entered), 'meanEntryActionAmongEntries': sum(entered) / len(entered) if entered else None,
                           'firstPickups': sum(g['firstPickupAction'] is not None for g in games),
                           'deliveries': sum(g['deliveries'] for g in games),
                           'meanSearchUniqueCells': sum(g['searchRoute']['uniqueCells'] for g in games) / len(games)})
        report = {'status': 'diagnostic_only', 'groups': groups, 'games': all_games,
                  'scope': 'paired epoch-8 policies on training-layout factorial scenes; carry cue is simulator-derived task state, not a physical sensor; no heldout, actor-input attestation, or physical hardware claim; layout changes also change other geometry and appearance; search-cell windows may end at different pickup times'}
        (OUTPUT / 'report.json').write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
        print(json.dumps({'status': report['status'], 'games': len(all_games), 'output': str(OUTPUT)}))


if __name__ == '__main__':
    main()
