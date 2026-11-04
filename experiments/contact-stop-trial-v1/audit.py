#!/usr/bin/env python3
"""Audit matched simulator records without treating a stop as a delivery."""
import json
from pathlib import Path


def rows(path):
    with Path(path).open() as stream:
        return [json.loads(line) for line in stream]


def audit_pair(disabled, enabled, prior):
    """Compare a pinned historical run, full disabled run and enabled run.

    The caller must separately verify model/scene identity and arm supervisors.
    Strict byte/JSON equality deliberately censors divergent trajectories.
    """
    disabled, enabled, prior = map(Path, (disabled, enabled, prior))
    for name in ('initial.json',):
        if disabled.joinpath(name).read_bytes() != prior.joinpath(name).read_bytes() or disabled.joinpath(name).read_bytes() != enabled.joinpath(name).read_bytes():
            raise ValueError('initial state differs')
    for name in ('case.json', 'environment.bin'):
        if disabled.joinpath('scene', name).read_bytes() != prior.joinpath('scene', name).read_bytes() or disabled.joinpath('scene', name).read_bytes() != enabled.joinpath('scene', name).read_bytes():
            raise ValueError('scene differs')
    result = json.loads(enabled.joinpath('result.json').read_text())
    full = json.loads(disabled.joinpath('result.json').read_text())
    if full.get('steps') != 300 or result.get('seed') != full.get('seed'):
        raise ValueError('invalid full baseline or seed')
    report_path = enabled / 'contact-stop.json'
    stopped = report_path.exists()
    if stopped:
        report = json.loads(report_path.read_text())
        trigger = report.get('triggerAfterActions')
        if (report.get('schema') != 'puppybot.sim-contact-stop.v1' or
                report.get('reason') != 'sustained_contact' or type(trigger) is not int or not 1 <= trigger <= 300 or
                report.get('observedActions') != trigger + 1 or report.get('zeroStopActions') != 1 or
                report.get('consecutiveContactSamples') != 3 or report.get('zeroCommandEchoObserved') is not True or
                report.get('stopCommandAcknowledged') is not False or report.get('goalGameCompleted') is not False or
                result.get('steps') != trigger + 1 or result.get('countAsFailedGame') is not True or
                result.get('fullHorizonCompleted') is not False or result.get('contactStopReason') != 'sustained_contact'):
            raise ValueError('invalid stopped-game report')
    else:
        trigger = 300
        if (result.get('steps') != 300 or result.get('countAsFailedGame') is not False or
                result.get('fullHorizonCompleted') is not True or result.get('contactStopReason') is not None):
            raise ValueError('invalid completed enabled game')
    for name in ('steer-probe.jsonl', 'hysteresis.jsonl'):
        control = rows(disabled / name); historical = rows(prior / name); treatment = rows(enabled / name)
        if len(control) != 300 or control != historical or len(treatment) != trigger or treatment != control[:trigger]:
            raise ValueError('policy history differs: ' + name)
    control = rows(disabled / 'decisions.jsonl'); historical = rows(prior / 'decisions.jsonl'); treatment = rows(enabled / 'decisions.jsonl')
    if len(control) != 300 or control != historical or len(treatment) != trigger + int(stopped) or treatment[:trigger] != control[:trigger]:
        raise ValueError('decision prefix differs')
    start = disabled.joinpath('chase.jsonl').read_bytes().splitlines()[0]
    if start != prior.joinpath('chase.jsonl').read_bytes().splitlines()[0] or start != enabled.joinpath('chase.jsonl').read_bytes().splitlines()[0]:
        raise ValueError('start differs')
    if stopped:
        zero = treatment[-1]; previous = treatment[-2]
        drive = zero['state']['controller']['drive']
        if (zero.get('action') != [0.0, 0.0] or drive['leftSpeed'] != 0 or drive['rightSpeed'] != 0 or
                zero['sequence'] != previous['sequence'] + 1 or zero['step'] != previous['step'] + 10):
            raise ValueError('zero request or simulator echo missing')
        # The guard consumes the three preceding drive responses; the stop
        # response itself can legitimately clear contact after zeroing drive.
        streak = 0; first = None
        for index, row in enumerate(treatment[:trigger], 1):
            drive = row['state']['controller']['drive']
            contact = row['proprio'][5] == 1.0
            moving = drive['leftSpeed'] != 0 or drive['rightSpeed'] != 0
            streak = streak + 1 if contact and moving else 0
            if streak >= 3 and first is None: first = index
        if first != trigger: raise ValueError('first sustained-contact threshold differs')
    return {'seed': full['seed'], 'triggerAfterActions': trigger if stopped else None,
            'stopped': stopped, 'countAsFailedGame': stopped,
            'disabledDeliveries': full['deliveries'], 'enabledDeliveries': result['deliveries'],
            'horizon': 300, 'stopAcknowledged': False,
            'scope': 'saved local simulator command echo; no physical-stop or execution attestation'}
