#!/usr/bin/env python3
"""Conservative local result check; not a resource or provenance monitor."""
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def audit(root, duration=None, candidate=None):
    root = Path(root)
    if duration is None and candidate is None:
        spec = importlib.util.spec_from_file_location('turn_pair_saved_check', Path(__file__).with_name('run.py'))
        runner = importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)
        manifest = json.loads((root / 'inputs.json').read_text())
        runner.check_manifest(root, manifest)
        for name in runner.ARMS:
            arm = root / name
            runner.check_invocation(root, manifest, name); runner.check_run_inputs(arm, manifest, name)
            if json.loads((arm / 'supervisor-result.json').read_text()) != json.loads((arm / 'monitor/supervisor-result.json').read_text()):
                raise ValueError('arm supervisor records differ')
            fresh = subprocess.run([sys.executable, '-I', str(runner.ROOT / 'flex/exploration/manipulation_audit.py'),
                                    manifest['case'], str(arm / 'run/trace.jsonl')], cwd=runner.ROOT,
                                   capture_output=True, text=True, timeout=60)
            if fresh.returncode or json.loads(fresh.stdout) != json.loads((arm / 'manipulation-audit.json').read_text()):
                raise ValueError('manipulation audit differs')
        arms = {name: audit(root / name, 10, name == 'candidate-10')
                for name in ('control-10', 'candidate-10')}
        runner.check_manifest(root, manifest)
        eligible = all(value['status'] == 'mechanism_observed' for value in arms.values())
        return {'status': 'diagnostic_only', 'comparisonEligible': eligible,
                'censorReason': None if eligible else 'one or both arm mechanisms were not observed',
                'arms': arms,
                'scope': 'two local simulated fault-injection outcomes; not physical, held-out or execution attestation'}
    if duration not in (0, 10, 60) or type(candidate) is not bool:
        raise ValueError('invalid arm')
    required = (root / 'supervisor-result.json', root / 'run/result.json',
                root / 'run/trace.jsonl', root / 'manipulation-audit.json')
    if any(not path.is_file() or path.is_symlink() for path in required):
        return {'status': 'censored', 'reason': 'missing outcome or trace'}
    supervisor, result, trace, manipulation = required
    supervised = json.loads(supervisor.read_text())
    outcome = json.loads(result.read_text())
    manipulation = json.loads(manipulation.read_text())
    if (type(supervised.get('clientExit')) is not int or supervised['clientExit'] != 0 or
            type(supervised.get('processGroup')) is not int or supervised['processGroup'] <= 0 or
            'signal' not in supervised or supervised['signal'] is not None or supervised.get('timedOut') is not False or
            supervised.get('remainingWorkersTerminated') is not False or
            outcome.get('collectorTerminal') is not True or
            outcome.get('stopCommandAcknowledged') is not True or
            outcome.get('traceSHA256') != sha(trace)):
        return {'status': 'censored', 'reason': 'unclean, incomplete or mismatched run'}
    if manipulation.get('status') != 'diagnostic_only' or type(manipulation.get('traceMeetsManipulationCriteria')) is not bool:
        return {'status': 'censored', 'reason': 'missing valid manipulation audit'}
    trigger = None; last = None; previous = None; lower = None; fail = None; initial_samples = None
    recovered_frames = set()
    with trace.open() as stream:
        for line in stream:
            row = json.loads(line)
            tick = row['totalSteps']
            if type(tick) is not int or (previous is not None and tick != previous + 1):
                return {'status': 'censored', 'reason': 'trace ticks are not consecutive'}
            previous = tick
            case = row.get('case')
            if not isinstance(case, dict) or not isinstance(case.get('turnProbe'), dict):
                return {'status': 'censored', 'reason': 'missing turn telemetry'}
            probe = case['turnProbe']
            if probe.get('duration') != duration:
                return {'status': 'censored', 'reason': 'fault mode differs'}
            if probe['triggerTick'] >= 0 and trigger is None:
                trigger = row
                initial_samples = case['dockVision']['samples']
                if (probe['triggerTick'] != tick or probe.get('eligible') is not True or probe.get('preStable', 0) < 3 or
                        type(probe.get('preFrame')) is not int or not tick - 10 <= probe['preFrame'] <= tick):
                    return {'status': 'censored', 'reason': 'trigger lacked previously fresh stable unchanged vision'}
            if trigger is not None and probe['triggerTick'] != trigger['case']['turnProbe']['triggerTick']:
                return {'status': 'censored', 'reason': 'trigger changed'}
            if probe['lowerTick'] >= 0 and lower is None:
                lower = row
            if case['phase'] == 'failed' and fail is None:
                fail = row
            if trigger is not None and duration and candidate and lower is None:
                if probe.get('waitTick') != trigger['totalSteps'] or probe.get('turning') is not True:
                    return {'status': 'mechanism_mismatch', 'reason': 'bounded wait was not maintained'}
            if trigger is not None and duration and candidate and (lower is None or lower is row):
                vision = case['dockVision']; frame = vision.get('frameId')
                if vision.get('valid') is True and type(frame) is int and frame >= trigger['totalSteps'] + duration:
                    recovered_frames.add(frame)
            # The immediate-stop control ends at the first faulted tick.
            # Do not require simulated post-failure sampling after termination.
            if trigger is not None and (fail is None or fail is row) and duration:
                start = trigger['totalSteps']; samples = case['dockVision'].get('samples')
                if type(samples) is not int or samples < initial_samples:
                    return {'status': 'censored', 'reason': 'invalid detector sample count'}
                if tick < start + duration:
                    if case['dockVision'].get('valid') is not False:
                        return {'status': 'mechanism_mismatch', 'reason': 'vision restored during fault'}
                    if probe.get('masked') != 1 + samples - initial_samples:
                        return {'status': 'mechanism_mismatch', 'reason': 'suppressed sample count differs'}
            if trigger is not None and lower is None:
                held = row.get('gripper', {})
                if held.get('held') is not True or held.get('releases') != trigger['gripper']['releases']:
                    return {'status': 'mechanism_mismatch', 'reason': 'payload or gripper changed before lowering'}
            last = row
    if trigger is None or last is None:
        return {'status': 'censored', 'reason': 'settled yaw trigger not observed'}
    p = trigger['case']['turnProbe']; t = trigger['totalSteps']
    if (duration and (p['masked'] < 1 or trigger['case']['dockVision']['valid'] is not False)) or (not duration and p['masked']):
        return {'status': 'mechanism_mismatch', 'reason': 'injection did not match the registered mode'}
    expected_stop = duration == 60 or (duration == 10 and not candidate)
    if expected_stop:
        if lower is not None or fail is None:
            return {'status': 'mechanism_mismatch', 'reason': 'expected stop did not occur before lowering'}
        reason = fail['case']['reason']
        expected = ('box observation reacquisition timed out after turn' if candidate else
                    'box observation lost or changed while turning above container')
        if (reason != expected or (candidate and fail['totalSteps'] - t != 50) or
                (not candidate and fail['totalSteps'] != t)):
            return {'status': 'mechanism_mismatch', 'reason': 'stop reason or deadline differed'}
    else:
        if lower is None:
            return {'status': 'mechanism_mismatch', 'reason': 'expected lowering was not issued'}
        event = lower['case']['turnProbe']; vision = lower['case']['dockVision']
        if event['lowerTick'] != lower['totalSteps'] or not vision['valid'] or vision['stableObservations'] < 3:
            return {'status': 'mechanism_mismatch', 'reason': 'lowering lacked fresh stable dock vision'}
        if duration and (event['lowerTick'] < t + duration or event['lowerTick'] >= t + 50 or
                         vision['frameId'] < t + duration or len(recovered_frames) < 3):
            return {'status': 'mechanism_mismatch', 'reason': 'recovery timing or frame differs'}
    return {'status': 'mechanism_observed', 'triggerTick': t,
            'lowerTick': None if lower is None else lower['totalSteps'],
            'failureReason': None if fail is None else fail['case']['reason'],
            'simulatedManipulationCriterion': manipulation['traceMeetsManipulationCriteria'],
            'scope': 'local saved-trace mechanism check only; source, GPU, disk and supervisor attestation require a separate monitor'}


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and supervised execution.')
