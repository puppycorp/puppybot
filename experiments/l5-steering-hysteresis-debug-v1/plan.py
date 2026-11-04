#!/usr/bin/env python3
"""Fixed post-hoc reproduction plan; this module does not start a trial."""
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
SCENES = ROOT / 'build/flex/sim/expanded-rooms-v1/scenes'
MODEL = P / 'search-dagger-heading/models/heading-epoch8-pair/treatment'
BUILD = P / 'l5-steering-hysteresis-build-v1'
OUTPUT = P / 'l5-steering-hysteresis-debug-v1'
KICK_PLAN = P / 'l5-steering-kick-plan-v1.json'
KICK_REPORT = P / 'l5-steering-kick-diagnostic-v1/report.json'
HYS_PLAN = P / 'l5-steering-hysteresis-plan-v1.json'


def design():
    conditions = [
        {'index': 0, 'oldIndex': 2, 'layout': 13, 'variant': 2, 'seed': 6800102,
         'scene': str(SCENES / '13/2')},
        {'index': 1, 'oldIndex': 7, 'layout': 15, 'variant': 3, 'seed': 6800107,
         'scene': str(SCENES / '15/3')},
    ]
    return {'schema': 'puppybot.l5-steering-hysteresis-debug-draft.v1',
            'status': 'draft_not_registered', 'conditions': conditions,
            'arms': ['control', 'kick', 'kick-hysteresis'], 'episodesPerArm': 2,
            'horizon': 300, 'level': 5, 'cameraPitch': 82, 'model': str(MODEL),
            'purpose': 'reproduce the two previously oscillating kick trajectories and investigate the post-hoc guard',
            'metrics': ['per-game back-and-forth actions', 'guard activation and first changed action',
                        'first virtual consumption', 'completed virtual delivery', 'matched actor prefix'],
            'scope': 'deliberately selected known failure cases; no generalization, held-out, physical or promotion claim',
            'prerequisite': 'freeze current inputs and exact commands; independently review and supervise all six arms with fresh output paths and disk/GPU monitors'}


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def command(row, arm):
    if row not in design()['conditions'] or arm not in design()['arms']:
        raise ValueError('unknown fixed case or arm')
    output = OUTPUT / 'games' / str(row['index']) / arm
    flag = '--steer-probe-control' if arm == 'control' else '--steer-probe-enabled'
    argv = [str(BUILD / 'control'), 'run', '--fetch', '--policy', str(MODEL),
            '--scene', row['scene'], '--output', str(output), '--episodes', '1',
            '--horizon', '300', '--seed', str(row['seed']), '--level', '5', '--lean',
            '--wheel-odometry', '--camera-pitch', '82', flag]
    if arm == 'kick-hysteresis':
        argv.append('--steer-hysteresis')
    return argv


def preflight(kick_plan, kick_report, hys_plan):
    """Check archived prior failures and match current case, model and binary pins.

    This is a read-only preflight, not registration or an execution attestation.
    A future frozen registration must also bind the executor and runtime chain.
    """
    if (kick_plan.get('schema') != 'puppybot.l5-steering-kick-plan.v1' or
            kick_plan.get('status') != 'frozen_before_play' or
            hys_plan.get('schema') != 'puppybot.l5-steering-hysteresis-plan.v1' or
            hys_plan.get('status') != 'frozen_before_play' or
            kick_report.get('status') != 'diagnostic_only'):
        raise ValueError('invalid prior plan or report')
    prior_scenes = kick_plan['scenes']
    prior_pairs = kick_report['pairs']
    for row in design()['conditions']:
        prior = [x for x in prior_scenes if x.get('index') == row['oldIndex']]
        pairs = [x for x in prior_pairs if x.get('seed') == row['seed']]
        if (len(prior) != 1 or len(pairs) != 1 or
                any(prior[0].get(key) != row[key] for key in ('layout', 'variant', 'seed', 'scene')) or
                pairs[0].get('triggered') is not True or pairs[0].get('interventionMostlyBackForth') is not True):
            raise ValueError('prior case or failure differs')
        scene = Path(row['scene'])
        for name in ('case.json', 'environment.bin', 'layout.json'):
            if sha(scene / name) != prior[0]['files'][name]:
                raise ValueError('prior scene changed: ' + name)
    # The previous kick and this diagnostic use different controller binaries.
    # The new matched arms must all use the current hysteresis binary, not the
    # archived kick binary; source/model/simulator changes require a new plan.
    files = hys_plan['files']
    shared = (MODEL / 'policy', MODEL / 'weights.bin', ROOT / 'build/flex/control/simulator',
              ROOT / 'build/flex/sim/puppybot.bin')
    for path in (BUILD / 'control', *shared):
        if (str(path) not in files or (path in shared and kick_plan['files'].get(str(path)) != files[str(path)]) or
                sha(path) != files[str(path)]):
            raise ValueError('current input differs from archived pin: ' + str(path))
    if kick_plan['runtime'] != hys_plan['runtime']:
        raise ValueError('prior runtime chains differ')
    return {'status': 'preflight_only', 'cases': len(design()['conditions']),
            'scope': 'selected archived metadata and current hashes only; runtime chain must be reverified at registration'}


if __name__ == '__main__':
    raise SystemExit('Disabled; requires separate reviewed registration, executor and resource monitor.')
