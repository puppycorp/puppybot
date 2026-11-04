#!/usr/bin/env python3
"""Audit a matched simulated high-survey experiment and its image evidence."""
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


survey = load('elevation_saved_survey_audit', ROOT / 'experiments/dock-survey-trial-v1/audit.py')
base = survey.base
base.__file__ = str(HERE / 'audit.py')


def rows(path):
    result = survey.original_rows(path)
    if Path(path).name == 'trace.jsonl':
        # Remove only opt-in metadata from comparisons, never from the raw
        # diagnostic audit below. It is not robot pose or scene state.
        for row in result:
            case = row.get('case', {})
            case.pop('surveyHigh', None)
            case.get('dockVision', {}).pop('surveyDiagnostic', None)
    return result


base.rows = rows


def camera_times(path):
    result = {}
    for item in Path(path).glob('survey-*.sensor.camera.json'):
        camera = json.loads(item.read_text()); frame = camera.get('frameId'); captured = camera.get('capturedMs')
        if type(frame) is not int or type(captured) is not int: raise ValueError('invalid camera frame time')
        if frame in result and result[frame] != captured: raise ValueError('conflicting camera frame times')
        result[frame] = captured
    return result


def high_summary(trace, enabled, frame_times):
    counts = ('attempts', 'accepted', 'ikRejected', 'moveRejected')
    keys = (*counts, 'requestId', 'settledStep', 'armStillMatching', 'targetTicks')
    previous = None; frame_set = set(frame_times); frames_after_accept = []; settled_frames = []; found = set()
    latest_accepted_step = None; accepted_request = None; targets = {}; settled = {}; aiming_seen = False
    with Path(trace).open() as stream:
        for line in stream:
            row = json.loads(line); case = row.get('case', {})
            high = case.get('surveyHigh'); tick = row.get('step')
            if tick in frame_set:
                if type(row.get('timeMs')) is not int or row['timeMs'] != frame_times[tick]:
                    raise ValueError('camera capture time differs from trace')
                found.add(tick)
            if not enabled:
                if high is not None: raise ValueError('disabled high-survey metadata present')
                continue
            if not isinstance(high, dict) or set(high) != set(keys): raise ValueError('high-survey metadata missing')
            if any(type(high[k]) is not int or high[k] < 0 for k in counts): raise ValueError('invalid high-survey counters')
            if (type(high['requestId']) is not int or high['requestId'] < 0 or
                    type(high['settledStep']) is not int or high['settledStep'] < -1 or
                    type(high['armStillMatching']) is not bool): raise ValueError('invalid high-survey association')
            if previous is not None and any(high[k] < previous[k] for k in counts): raise ValueError('high-survey counter decreased')
            if high['accepted'] + high['ikRejected'] + high['moveRejected'] > high['attempts']:
                raise ValueError('inconsistent high-survey counters')
            if previous is not None and high['attempts'] != previous['attempts']:
                # Only a single unambiguous accepted attempt can associate a
                # later frame with the latest requested high pose. Multiple
                # changes in one tick are retained but not credited.
                accepted = (high['attempts'] - previous['attempts'] == 1 and
                            high['accepted'] - previous['accepted'] == 1 and
                            high['ikRejected'] == previous['ikRejected'] and
                            high['moveRejected'] == previous['moveRejected'])
                latest_accepted_step = row.get('step') if accepted else None
                accepted_request = high['requestId'] if accepted else None
                aiming_seen = False
                if latest_accepted_step is not None and type(latest_accepted_step) is not int:
                    raise ValueError('invalid high-survey acceptance tick')
            request = high['requestId']; target = high['targetTicks']; tick = row.get('step')
            if request == 0:
                if target is not None or high['settledStep'] != -1 or high['armStillMatching']:
                    raise ValueError('inactive high-survey association is contradictory')
                latest_accepted_step = None; accepted_request = None; aiming_seen = False
            else:
                if (request != high['accepted'] or not isinstance(target, list) or len(target) != 4 or
                        any(type(x) is not int for x in target)):
                    raise ValueError('invalid high-survey target or request')
                if request in targets and targets[request] != target: raise ValueError('high-survey target changed')
                targets[request] = target
                if request in settled and high['settledStep'] < 0: raise ValueError('settled high-survey target reset without a new request')
                if high['settledStep'] >= 0:
                    if type(tick) is not int or high['settledStep'] > tick: raise ValueError('settled tick is in future')
                    if request in settled and settled[request] != high['settledStep']: raise ValueError('settled tick changed')
                    settled[request] = high['settledStep']
                if high['armStillMatching']:
                    camera = row.get('camera'); ticks = row.get('ticks'); gripper = row.get('gripper')
                    if (high['settledStep'] < 0 or case.get('phase') != 'finding box' or
                            not isinstance(camera, dict) or camera.get('armSettled') is not True or
                            not isinstance(gripper, dict) or gripper.get('held') is not True or
                            not isinstance(ticks, list) or len(ticks) != 4 or any(type(x) is not int for x in ticks) or
                            any(abs(x - y) > 8 for x, y in zip(ticks, target))):
                        raise ValueError('reported high-pose association contradicts simulator trace')
                if request == accepted_request and case.get('phase') == 'aiming TCP camera':
                    aiming_seen = True
            if (row.get('step') in frame_set and latest_accepted_step is not None and
                    row['step'] > latest_accepted_step):
                frames_after_accept.append(row['step'])
                if (request == accepted_request and aiming_seen and high['armStillMatching'] and
                        high['settledStep'] > latest_accepted_step and row['step'] > high['settledStep']):
                    settled_frames.append({'frameId': row['step'], 'requestId': request,
                                           'settledStep': high['settledStep'], 'targetTicks': target})
            previous = high
    if enabled and previous is None: raise ValueError('empty high-survey trace')
    if found != frame_set: raise ValueError('camera frame missing from trace')
    return {'enabled': enabled, 'counters': previous, 'framesAfterAcceptance': frames_after_accept,
            'settledFrames': settled_frames,
            'scope': 'local simulated command and frame records only; no arm or payload safety claim'}


def audit(root):
    root = Path(root).absolute(); result = base.audit(root)
    if all(arm.get('status') == 'complete' for arm in result['arms']):
        diagnostics = {}; high = {}
        for name in base.ARMS:
            trace = root / name / 'run/trace.jsonl'
            diagnostics[name] = survey.diagnostic(root / name / 'diagnostic', trace)
            high[name] = high_summary(trace, name == 'candidate-search', camera_times(root / name / 'diagnostic'))
        candidate = high['candidate-search']
        accepted_frames = candidate['framesAfterAcceptance']
        result['surveyDiagnostic'] = diagnostics; result['highSurvey'] = high
        settled_frames = candidate['settledFrames']
        result['acceptedCommandAndLaterFrameObserved'] = bool(accepted_frames)
        # The marker, targets and encoders are simulator-local; this is not an
        # independent physical pose, collision-safety or visibility claim.
        result['mechanismEligible'] = bool(result['comparisonEligible'] and settled_frames)
        result['mechanismCensorReason'] = (None if result['mechanismEligible'] else
            result['censorReason'] if not result['comparisonEligible'] else 'no_frame_at_recorded_settled_high_target')
        result['outcomes'] = {}
        for arm in result['arms']:
            manipulation = arm.get('manipulation')
            if (not isinstance(manipulation, dict) or type(manipulation.get('traceMeetsManipulationCriteria')) is not bool or
                    not isinstance(manipulation.get('captures'), list) or not isinstance(manipulation.get('releases'), list)):
                raise ValueError('incomplete manipulation audit')
            result['outcomes'][arm['arm']] = {'completedSimulatedManipulation': manipulation['traceMeetsManipulationCriteria']}
    else:
        result['mechanismEligible'] = False; result['mechanismCensorReason'] = 'incomplete_arm'
    result['scope'] = ('same simulator and one known selection case; first two arms disable high survey, third enables it; '
                       'recorded simulation evidence only, no physical safety or execution attestation')
    return result


if __name__ == '__main__':
    if len(sys.argv) != 2: raise SystemExit(__doc__)
    try: print(json.dumps(audit(sys.argv[1]), sort_keys=True))
    except (OSError, ValueError, KeyError, TypeError) as error: raise SystemExit('Invalid trial: ' + str(error))
