#!/usr/bin/env python3
"""Audit matched visual-stall games without counting an interrupted game as success."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    'visual_saved_hysteresis_audit', ROOT / 'experiments/l5-steering-hysteresis-v1/audit.py')
hysteresis = importlib.util.module_from_spec(spec); spec.loader.exec_module(hysteresis)


def rows(path):
    with Path(path).open() as stream:
        return [json.loads(line) for line in stream]


def first_stall(initial, decisions, hashes):
    """Reconstruct the guard from recorded images and local command echoes.

    A hash represents a saved actor-image digest, not proof of its underlying
    raw frame or of the actor's execution. Contact and simulator truth are not
    inputs to this calculation. The caller can append a stop-report image as
    the final observation, which occurs before the next policy action.
    """
    if len(hashes) > len(decisions) + 1:
        raise ValueError('missing frame observations')
    states = [initial] + [row['state'] for row in decisions[:len(hashes) - 1]]
    count = 0; previous = None; previous_tick = None
    for index, (image, state) in enumerate(zip(hashes, states)):
        if not isinstance(image, str) or len(image) != 64 or any(c not in '0123456789abcdef' for c in image):
            raise ValueError('invalid actor-image digest')
        tick = state['totalSteps']; camera = state['camera']; perception = state['case']['perception']
        drive = state['controller']['drive']; left = drive['leftSpeed']; right = drive['rightSpeed']
        if (type(tick) is not int or tick < 0 or type(left) is not int or type(right) is not int or
                not -100 <= left <= 100 or not -100 <= right <= 100 or
                camera['pose'] != 'driving' or camera['armSettled'] is not True or
                perception['frameId'] != tick or (previous_tick is not None and tick <= previous_tick)):
            raise ValueError('invalid or stale camera observation')
        if index and decisions[index - 1]['step'] != tick:
            raise ValueError('camera and decision tick differ')
        count = count + 1 if (previous is not None and tick == previous_tick + 10 and
                              (left != 0 or right != 0) and image == previous) else 1
        if count >= 5:
            return index, tick, count
        previous = image; previous_tick = tick
    return None


def audit_pair(disabled, enabled, prior=None, require_zero_contact=False):
    """Recheck matched inputs and early stop, optionally without contact feedback.

    The caller verifies source, model, simulator and supervisor identities. A
    prior run is mandatory for the standard arms; the contact-ablation arms can
    use prior=None because altering policy feedback may change trajectories.
    """
    disabled, enabled = Path(disabled), Path(enabled)
    prior = Path(prior) if prior is not None else None
    for name in ('initial.json', 'scene/case.json', 'scene/environment.bin'):
        contents = (disabled / name).read_bytes()
        if contents != (enabled / name).read_bytes() or (prior is not None and contents != (prior / name).read_bytes()):
            raise ValueError('initial or scene input differs')
    full = json.loads((disabled / 'result.json').read_text())
    result = json.loads((enabled / 'result.json').read_text())
    if (full.get('steps') != 300 or result.get('seed') != full.get('seed') or
            full.get('visualContactAblated') is not require_zero_contact or
            result.get('visualContactAblated') is not require_zero_contact):
        raise ValueError('invalid baseline or seed')
    report_path = enabled / 'visual-stall-stop.json'; stopped = report_path.exists()
    report = json.loads(report_path.read_text()) if stopped else None
    trigger = report.get('triggerAfterActions') if stopped else 300
    if stopped:
        if (report.get('schema') != 'puppybot.sim-visual-stall.v1' or
                report.get('reason') != 'repeated_actor_image' or type(trigger) is not int or not 4 <= trigger <= 300 or
                report.get('observedActions') != trigger + 1 or report.get('zeroStopActions') != 1 or
                report.get('identicalFrames') != 5 or report.get('zeroCommandEchoObserved') is not True or
                report.get('stopCommandAcknowledged') is not False or report.get('goalGameCompleted') is not False or
                result.get('steps') != trigger + 1 or result.get('countAsFailedGame') is not True or
                result.get('fullHorizonCompleted') is not False or result.get('visualStopReason') != 'repeated_actor_image'):
            raise ValueError('invalid stopped-game report')
        if trigger == 300:
            raise ValueError('post-horizon trigger image has no independent matched baseline digest')
    elif (result.get('steps') != 300 or result.get('countAsFailedGame') is not False or
          result.get('fullHorizonCompleted') is not True or result.get('visualStopReason') is not None):
        raise ValueError('invalid completed enabled game')

    history = {}
    for name in ('steer-probe.jsonl', 'hysteresis.jsonl', 'decisions.jsonl'):
        control = rows(disabled / name); treatment = rows(enabled / name)
        historical = rows(prior / name) if prior is not None else None
        expected = trigger + int(stopped) if name == 'decisions.jsonl' else trigger
        if (len(control) != 300 or len(treatment) != expected or treatment[:trigger] != control[:trigger] or
                (historical is not None and control != historical)):
            raise ValueError('matched saved history differs: ' + name)
        history[name] = (control, treatment)
    start = (disabled / 'chase.jsonl').read_bytes().splitlines()[0]
    if start != (enabled / 'chase.jsonl').read_bytes().splitlines()[0] or (prior is not None and start != (prior / 'chase.jsonl').read_bytes().splitlines()[0]):
        raise ValueError('start differs')
    control_probe, treated_probe = history['steer-probe.jsonl']
    control_decisions, treated_decisions = history['decisions.jsonl']
    # The baseline is a complete 300-action arm. Reconstruct every kick and
    # hysteresis decision, quantized drive echo, feedback and recurrent-state
    # chain. The enabled policy prefix must equal this independently checked
    # baseline above. This matters especially when contact ablation causes a
    # new trajectory that cannot be compared with the historical records.
    baseline = hysteresis.audit_hysteresis(control_probe, control_decisions, history['hysteresis.jsonl'][0])
    if type(full.get('contactSteps')) is not int or full['contactSteps'] != baseline['contactActions']:
        raise ValueError('baseline contact count differs from actor feedback')
    for probe, decisions in ((control_probe, control_decisions), (treated_probe, treated_decisions)):
        if require_zero_contact and any(row['proprio'][5] != 0.0 for row in decisions):
            raise ValueError('contact ablation was not recorded as zero')
        for index, actor in enumerate(probe):
            if actor.get('step') != index + 1:
                raise ValueError('policy decision sequence differs')
            drive = decisions[index]['state']['controller']['drive']
            if actor['echo'] != [drive['leftSpeed'], drive['rightSpeed'], drive['steeringAngleDeg']]:
                raise ValueError('recorded command echo differs')
            if require_zero_contact and actor['feedback'][5] != 0:
                raise ValueError('contact ablation was not recorded as zero')

    hashes = [actor['imageSHA256'] for actor in treated_probe]
    if stopped:
        hashes.append(report['triggerImageSHA256'])
    first = first_stall(json.loads((enabled / 'initial.json').read_text()), treated_decisions[:trigger], hashes)
    if stopped:
        if first is None or first[0] != trigger:
            raise ValueError('first five-image trigger differs')
        if (report.get('triggerTick') != first[1] or report.get('triggerFrameId') != first[1] or
                report.get('triggerLeftSpeed') != treated_decisions[trigger - 1]['state']['controller']['drive']['leftSpeed'] or
                report.get('triggerRightSpeed') != treated_decisions[trigger - 1]['state']['controller']['drive']['rightSpeed']):
            raise ValueError('trigger frame or drive report differs')
        if trigger < 300 and report['triggerImageSHA256'] != control_probe[trigger]['imageSHA256']:
            raise ValueError('trigger image differs from matched baseline actor image')
        zero = treated_decisions[-1]; previous = treated_decisions[-2]
        drive = zero['state']['controller']['drive']
        if (zero.get('action') != [0.0, 0.0] or drive['leftSpeed'] != 0 or drive['rightSpeed'] != 0 or
                zero['sequence'] != previous['sequence'] + 1 or zero['step'] != previous['step'] + 10):
            raise ValueError('zero action or simulator echo missing')
    elif first is not None:
        raise ValueError('unreported visual stall')
    return {'seed': full['seed'], 'triggerAfterActions': trigger if stopped else None,
            'stopped': stopped, 'countAsFailedGame': stopped, 'contactAblation': require_zero_contact,
            'disabledDeliveries': full['deliveries'], 'enabledDeliveries': result['deliveries'],
            'horizon': 300, 'stopAcknowledged': False,
            'scope': 'saved image digests and simulator command echo only; no physical-stop or execution attestation'}
