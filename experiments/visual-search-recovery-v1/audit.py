#!/usr/bin/env python3
"""Audit a saved hybrid protocol, including a recorded early visual transfer.

The prior fallback auditor remains authoritative for protocol and actor checks.
This adapter changes only its fixed action/poll bounds and the documented
early-search branch; unexpected prior source changes fail closed.
"""
import importlib.util
import hashlib
import inspect
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    'visual_search_prior_audit', ROOT / 'experiments/physical-search-fallback-trial-v1/audit.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
PRIOR_PROTOCOL_SHA256 = 'e7990a1e650dc695d0020cc279799444f5e5d87cf7863bcb27ff46034bf7e82f'


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('prior protocol audit differs from reviewed adapter')
    return text.replace(old, new, 1)


def adapted_protocol():
    source = inspect.getsource(base.protocol)
    if hashlib.sha256(source.encode()).hexdigest() != PRIOR_PROTOCOL_SHA256:
        raise ValueError('prior protocol audit source changed')
    changes = [
        ('def protocol(run,enabled):',
         'def protocol(run,enabled,nav_limit,poll_limit,visual_early,visual_trigger):'),
        ("result.get('navigationActionLimit')!=90", "result.get('navigationActionLimit')!=nav_limit"),
        ("result.get('collectorPollLimit')!=1499", "result.get('collectorPollLimit')!=poll_limit"),
        ("not 1<=result['policyActions']<=90", "not 1<=result['policyActions']<=nav_limit"),
        ("not enabled or searches>1 or actions!=90 or ack not in (2,8)",
         "not enabled or searches>1 or (actions!=nav_limit and not (visual_early and actions==visual_trigger)) or ack not in (2,8)"),
        ('if actions<90:expected=6 if detections else 2',
         'if actions<nav_limit:expected=6 if detections else (8 if visual_early and actions==visual_trigger else 2)'),
        ('elif actions<90:expected=2',
         "elif actions<nav_limit:expected=3 if visual_early and i and requests[i-1]['command']==8 else 2"),
        ('polls==1499', 'polls==poll_limit'),
        ('polls>1499', 'polls>poll_limit'),
        ('polls!=1499', 'polls!=poll_limit'),
    ]
    for old, new in changes:
        source = replace_once(source, old, new)
    namespace = dict(base.__dict__)
    exec(compile(source, str(Path(base.__file__)), 'exec'), namespace)
    return namespace['protocol']


def read_image(path):
    image = path.read_bytes()
    if len(image) != 21168:
        raise ValueError('missing or malformed recorded actor image')
    return image


def visual_first_trigger(run, protocol, trigger_image):
    """Reconstruct the detector from actual saved actor and trigger bytes."""
    journal = protocol['journal']; requests = protocol['requests']
    observations = []
    for index, request in enumerate(requests):
        if request['command'] == 2:
            if index == 0:
                raise ValueError('drive lacks prior observation')
            row = journal[index - 1]
            observations.append((row, read_image(run / 'actors' / f"actor-{row['sequence']}.rgb")))
        elif request['command'] == 8 and trigger_image is not None:
            if index == 0:
                raise ValueError('search lacks prior observation')
            observations.append((journal[index - 1], trigger_image))
    previous = None; count = 0
    for offset, (row, image) in enumerate(observations):
        drive = row.get('driveCommand'); tick = row.get('totalSteps')
        if (row.get('owner') != 0 or row.get('imageValid') is not True or
                row.get('cameraDriving') is not True or row.get('cameraStill') is not True or
                type(tick) is not int or row.get('cameraFrame') != tick or
                not isinstance(drive, list) or len(drive) != 3 or
                any(type(value) is not int for value in drive) or
                any(abs(value) > 100 for value in drive[:2])):
            raise ValueError('invalid visual detector observation')
        if previous is not None and tick <= previous[0]:
            raise ValueError('replayed visual detector observation')
        same = previous is not None and image == previous[1]
        count = count + 1 if same and tick == previous[0] + 10 and (drive[0] or drive[1]) else 1
        if count >= 5:
            return offset, row['sequence'], tick
        previous = tick, image
    return None


def audit_run(run, *, visual_enabled, nav_limit=90, poll_limit=1499):
    run = Path(run)
    if (type(visual_enabled) is not bool or type(nav_limit) is not int or type(poll_limit) is not int or
            not 1 <= nav_limit <= 300 or not 1 <= poll_limit <= 1500):
        raise ValueError('explicit run settings required')
    result = json.loads((run / 'result.json').read_text())
    fields = ('visualRecoveryReason', 'visualRecoveryTriggerAction', 'visualRecoveryOutcome')
    artifact = run / 'visual-trigger.rgb'
    if not visual_enabled:
        if any(field in result for field in fields) or artifact.exists() or artifact.is_symlink():
            raise ValueError('disabled run emitted visual recovery evidence')
        reason = 0; trigger = -1; outcome = None
    else:
        if any(field not in result for field in fields):
            raise ValueError('missing visual recovery outcome')
        reason, trigger, outcome = (result[field] for field in fields)
        if type(reason) is not int or type(trigger) is not int or not isinstance(outcome, str):
            raise ValueError('invalid visual recovery outcome')
        if reason == 2:
            raise ValueError('censored: detector-invalid outcome cannot be reconstructed from saved frames')
        if reason not in (0, 1):
            raise ValueError('unknown visual recovery reason')
        if reason == 0 and (trigger != -1 or outcome != 'not_triggered' or artifact.exists() or artifact.is_symlink()):
            raise ValueError('contradictory untriggered result')
        if reason == 1 and (not 4 <= trigger < nav_limit or trigger != result.get('policyActions') or
                            artifact.is_symlink() or not artifact.is_file()):
            raise ValueError('missing or invalid early visual trigger')
    early = visual_enabled and reason == 1
    protocol = adapted_protocol()(run, True, nav_limit, poll_limit, early, trigger)
    images = read_image(artifact) if early else None
    first = visual_first_trigger(run, protocol, images)
    if early:
        if first is None or first[0] != trigger:
            raise ValueError('recorded images do not establish first visual trigger')
        request = next((r for r in protocol['requests'] if r['command'] == 8), None)
        if request is None or request['sequence'] != first[1] + 1:
            raise ValueError('trigger image not immediately followed by search request')
        expected = ('target_handoff_unverified' if result['handoff'] else
                    'search_started_unverified' if result['searchFallbackStarted'] else 'transfer_did_not_start')
        if outcome != expected:
            raise ValueError('transfer outcome contradicts protocol')
    elif visual_enabled and first is not None:
        raise ValueError('saved actor images show an unreported visual trigger')
    return {'status': 'diagnostic_only', 'visualEnabled': visual_enabled,
            'visualTriggerAction': trigger if early else None,
            'triggerObservationSequence': first[1] if early else None,
            'triggerTick': first[2] if early else None,
            'visualRecoveryOutcome': outcome, 'policyActions': protocol['actions'],
            'searchStarted': protocol['searchStep'] is not None,
            'handoff': protocol['handoffStep'] is not None,
            'collectorTerminal': protocol['terminal'],
            'scope': 'saved simulator protocol and resized image bytes only; no physical, raw-camera or execution attestation'}
