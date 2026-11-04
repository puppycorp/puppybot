#!/usr/bin/env python3
"""Re-audit one recorded hybrid simulator trial; never commands the robot.

Capture and delivery here refer to the simulated contact model. World state,
body identity and containment are inspected only after the run.
"""
import importlib.util
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


hidden = load('physical_hidden_audit', ROOT / 'flex/tests/run-physical-hidden-trial.py')


def validate_protocol(journal):
    if len(journal) < 2:
        raise ValueError('missing protocol observations')
    for index, row in enumerate(journal):
        tick = row.get('totalSteps'); ack = row.get('ack'); command = row.get('driveCommand')
        if (type(tick) is not int or tick < 0 or type(row.get('step')) is not int or row['step'] != tick or
                type(row.get('owner')) is not int or type(row.get('timeMs')) is not int or row['timeMs'] < 0 or
                type(row.get('sequence')) is not int or row['sequence'] != index + 1 or
                type(ack) is not int or ack not in (0, 1, 2, 3, 4, 5, 7) or
                not isinstance(command, list) or len(command) != 3 or
                any(type(value) is not int for value in command)):
            raise ValueError('invalid protocol record')
        owner = row.get('owner'); image = row.get('imageValid'); detections = row.get('rgbDetections')
        if owner == 0:
            if (type(detections) is not int or detections < 0 or type(row.get('cameraFrame')) is not int or
                    row['cameraFrame'] != tick or row.get('cameraDriving') is not True or row.get('cameraStill') is not True):
                raise ValueError('invalid navigation camera observation')
        elif (detections is not None or type(row.get('cameraFrame')) is not int or row['cameraFrame'] != -1 or
              row.get('cameraDriving') is not False or row.get('cameraStill') is not False):
            raise ValueError('invalid collector camera observation')
        if index == 0:
            if ack != 0 or owner != 0 or image is not True or detections != 0 or command != [0, 0, 90]:
                raise ValueError('invalid initial navigation observation')
            continue
        prev = journal[index - 1]; delta = tick - prev['totalSteps']
        if row['timeMs'] - prev['timeMs'] != 20 * delta:
            raise ValueError('protocol clock differs from simulator ticks')
        if ack == 1:
            valid = prev['owner'] == 0 and owner == 0 and image is True and delta == 10
        elif ack == 2:
            valid = (prev['owner'] == 0 and type(prev.get('rgbDetections')) is int and prev['rgbDetections'] > 0 and
                     owner == 0 and image is True and command == [0, 0, 90] and delta == 2)
        elif ack == 3:
            valid = (prev['owner'] == 0 and type(prev.get('rgbDetections')) is int and prev['rgbDetections'] > 0 and
                     owner == 1 and image is False and detections is None and command == [0, 0, 90] and delta == 2)
        elif ack in (4, 5):
            valid = (prev['ack'] in (3, 4) and owner == (1 if ack == 4 else 2) and image is False and
                     detections is None and (delta == 20 if ack == 4 else 0 <= delta <= 20))
        elif ack == 7:
            valid = (index == len(journal) - 1 and owner == 2 and image is False and detections is None and
                     command == [0, 0, 90] and delta == 0)
        else:
            valid = False
        if not valid:
            raise ValueError('invalid protocol ownership, timing or handoff transition')
    if journal[-1]['ack'] != 7:
        raise ValueError('missing final stop')


def trace_last_tick(path):
    last = None
    with open(path) as stream:
        for line in stream:
            if line.strip(): last = json.loads(line)
    if (not isinstance(last, dict) or type(last.get('totalSteps')) is not int or
            type(last.get('step')) is not int or last['step'] != last['totalSteps']):
        raise ValueError('missing or ambiguous final trace tick')
    return last['totalSteps']


def classify(result, actor, manipulation, journal, truth_navigation):
    validate_protocol(journal)
    path = truth_navigation.get('pathM') if isinstance(truth_navigation, dict) else None
    if type(path) not in (int, float) or not math.isfinite(path) or path < 0:
        raise ValueError('invalid post-run simulator-truth navigation path')
    if (type(result.get('handoff')) is not bool or type(result.get('collectorTerminal')) is not bool or
            type(actor.get('policyActions')) is not int or type(actor.get('nonzeroDriveActions')) is not int or
            actor['policyActions'] < 1 or not 0 <= actor['nonzeroDriveActions'] <= actor['policyActions'] or
            type(manipulation.get('traceMeetsManipulationCriteria')) is not bool or
            not isinstance(manipulation.get('captures'), list) or not isinstance(manipulation.get('releases'), list) or
            not isinstance(manipulation.get('settledAtEnd'), list) or not isinstance(manipulation.get('settledDeliveries'), dict) or
            type(manipulation.get('objects')) is not int or manipulation['objects'] != 1):
        raise ValueError('missing or invalid audited outcome fields')
    drives = [(i, row) for i, row in enumerate(journal) if row.get('ack') == 1]
    if len(drives) != actor['policyActions']:
        raise ValueError('policy action count differs from journal')
    for _, row in drives:
        command = row.get('driveCommand')
        if not isinstance(command, list) or len(command) != 3 or any(type(value) is not int for value in command):
            raise ValueError('invalid recorded policy drive')
    moving = [(i, row) for i, row in drives if row['driveCommand'][0] != 0 or row['driveCommand'][1] != 0]
    if len(moving) != actor['nonzeroDriveActions']:
        raise ValueError('nonzero policy drive count differs from journal')
    indexed_handoffs = [(i, row) for i, row in enumerate(journal) if row.get('ack') == 3]
    handoffs = [row for _, row in indexed_handoffs]
    if len(handoffs) != int(result['handoff']): raise ValueError('handoff status differs from journal')
    if indexed_handoffs and any(i >= indexed_handoffs[0][0] for i, _ in drives):
        raise ValueError('policy drive occurred after collector handoff')
    if (not journal or journal[-1].get('ack') != 7 or type(journal[-1].get('totalSteps')) is not int or
            journal[-1].get('step') != journal[-1]['totalSteps']):
        raise ValueError('missing or ambiguous final stop tick')
    final_tick = journal[-1]['totalSteps']
    polls = [(i, row) for i, row in enumerate(journal) if row.get('ack') in (4, 5)]
    terminals = [(i, row) for i, row in polls if row['ack'] == 5]
    if len(terminals) > 1 or bool(terminals) != result['collectorTerminal']:
        raise ValueError('collector terminal result differs from journal')
    if not handoffs and polls: raise ValueError('collector poll without handoff')
    if handoffs:
        handoff_index = indexed_handoffs[0][0]
        if not polls or any(i <= handoff_index for i, _ in polls) or (terminals and terminals[0] != polls[-1]):
            raise ValueError('invalid collector poll order')
        if [i for i, _ in polls] != list(range(handoff_index + 1, handoff_index + 1 + len(polls))):
            raise ValueError('unexpected response during collector ownership')
        if polls[-1][0] != len(journal) - 2 or polls[-1][1].get('totalSteps') != final_tick:
            raise ValueError('collector poll and final stop differ')
        prior = handoffs[0]
        for _, row in polls:
            tick = row.get('totalSteps'); previous_tick = prior.get('totalSteps')
            if (type(tick) is not int or type(previous_tick) is not int or row.get('step') != tick or
                    row.get('owner') != (2 if row['ack'] == 5 else 1) or
                    (row['ack'] == 4 and tick - previous_tick != 20) or
                    (row['ack'] == 5 and not 0 <= tick - previous_tick <= 20)):
                raise ValueError('invalid collector tick or owner')
            prior = row
    captures = manipulation['captures']; releases = manipulation['releases']; settled = manipulation['settledAtEnd']
    if any(not isinstance(item, dict) or not isinstance(item.get('object'), str) or
           type(item.get('step')) is not int or item['step'] < 0 for item in captures + releases):
        raise ValueError('invalid capture or release records')
    if any(type(item.get('overBox')) is not bool for item in releases): raise ValueError('invalid release evidence')
    if not all(isinstance(name, str) for name in settled): raise ValueError('invalid settled object names')
    if any(item['step'] > final_tick for item in captures + releases):
        raise ValueError('capture or release occurs after trace end')
    if not result['handoff']:
        if captures or releases or settled or manipulation['traceMeetsManipulationCriteria']:
            raise ValueError('manipulation recorded without collector handoff')
        if result['collectorTerminal'] or actor['policyActions'] != 90:
            raise ValueError('no-handoff run did not reach the fixed navigation limit')
        outcome = 'no_handoff_within_navigation_limit'
    else:
        tick = handoffs[0].get('totalSteps')
        if type(tick) is not int or tick < 0 or handoffs[0].get('step') != tick:
            raise ValueError('invalid or ambiguous handoff tick')
        if any(item['step'] <= tick for item in captures + releases):
            raise ValueError('manipulation precedes stopped handoff')
        if actor['nonzeroDriveActions'] == 0:
            outcome = 'no_nonzero_policy_drive'
        elif not captures:
            if releases or settled or manipulation['traceMeetsManipulationCriteria']:
                raise ValueError('release or delivery without capture')
            outcome = ('collector_terminal_without_capture' if result['collectorTerminal']
                       else 'collector_incomplete_without_capture')
        elif not manipulation['traceMeetsManipulationCriteria']:
            outcome = ('collector_terminal_without_settled_delivery' if result['collectorTerminal']
                       else 'collector_incomplete_after_capture')
        else:
            if len(settled) != 1 or manipulation.get('objects') != 1:
                raise ValueError('success requires the one target settled at end')
            name = settled[0]
            pairs = [(capture, release) for capture in captures for release in releases
                     if capture['object'] == release['object'] == name and capture['step'] < release['step'] and release['overBox']]
            settled_step = manipulation['settledDeliveries'].get(name)
            if (not pairs or type(settled_step) is not int or settled_step > final_tick or
                    not any(release['step'] < settled_step for _, release in pairs)):
                raise ValueError('settled target lacks earlier capture and release')
            outcome = ('hybrid_simulated_delivery' if path > 0
                       else 'simulated_delivery_without_observed_navigation_motion')
    motion = ('no_nonzero_command' if not moving else
              'nonzero_truth_path_recorded' if path > 0 else 'commanded_without_observed_truth_motion')
    return {'status': 'diagnostic_only', 'outcome': outcome, 'motionStatus': motion,
            'policyActions': actor['policyActions'], 'nonzeroPolicyDriveActions': actor['nonzeroDriveActions'],
            'handoff': result['handoff'], 'collectorTerminal': result['collectorTerminal'],
            'captures': captures, 'releases': releases, 'settledAtEnd': settled,
            'scope': 'one simulated trial; recorded nonzero policy-drive commands before handoff, heuristic collector afterward; actor input and inference are not independently authenticated, and command echoes do not prove movement or cause detection; physical robot success, held-out qualification and policy promotion are not established'}


def inspect(root):
    root = Path(root); trial = root / 'trial'; run = trial / 'run'; inputs = trial / 'inputs'
    launch = json.loads((root / 'launch.json').read_text())
    manifest = json.loads((trial / 'inputs.json').read_text()); result = json.loads((run / 'result.json').read_text())
    status = json.loads((root / 'monitor/supervisor-result.json').read_text())
    if (type(status.get('clientExit')) is not int or status['clientExit'] != 0 or status.get('signal') is not None or
            status.get('timedOut') is not False or status.get('remainingWorkersTerminated') is not False or
            type(status.get('processGroup')) is not int or status['processGroup'] <= 0):
        raise ValueError('trial supervisor incomplete or unclean')
    expected = {'caseSHA256': inputs / 'case.json', 'environmentSHA256': inputs / 'environment.bin',
                'simulatorSHA256': inputs / 'simulator', 'clientSHA256': inputs / 'client',
                'weightsSHA256': inputs / 'model/weights.bin', 'policySHA256': inputs / 'model/policy',
                'receiptSHA256': inputs / 'model/receipt.json', 'assetSHA256': hidden.ASSET}
    for field, path in expected.items():
        if manifest.get(field) != hidden.sha(path): raise ValueError(f'trial input differs: {field}')
    if (manifest['caseSHA256'] != hashlib.sha256(hidden.prepare_case().encode()).hexdigest() or
            manifest['environmentSHA256'] != hidden.sha(hidden.ENVIRONMENT) or
            manifest.get('navigationActionLimit') != 90 or manifest.get('collectorPollLimit') != 1499 or
            manifest.get('wallSeconds') != 300):
        raise ValueError('fixed training-selection case or limits differ')
    if (manifest['weightsSHA256'] != launch['weightsSHA256'] or
            manifest['policySHA256'] != launch['policySHA256'] or
            result.get('traceSHA256') != hidden.sha(run / 'trace.jsonl')):
        raise ValueError('model or simulator trace differs from launch')
    if hidden.supervisor.source_hashes(inputs / 'flex-source') != json.loads((trial / 'source-inputs.json').read_text()):
        raise ValueError('snapshotted trial source changed')
    if hidden.supervisor.source_hashes(inputs / 'build/flex/sim/library') != json.loads((trial / 'library-inputs.json').read_text()):
        raise ValueError('snapshotted simulator dependencies changed')
    hidden.supervisor.verify_worker(json.loads((trial / 'worker-inputs.json').read_text()))
    hidden.rescan.verify_model(inputs / 'model')
    pinned_audits = ((ROOT / 'flex/exploration/manipulation_audit.py', inputs / 'flex-source/exploration/manipulation_audit.py'),
                     (ROOT / 'flex/tests/sim-cases.py', inputs / 'flex-source/tests/sim-cases.py'))
    if any(hidden.sha(snapshot) != launch['sourcePins'].get(str(original)) for original, snapshot in pinned_audits):
        raise ValueError('snapshotted outcome auditor differs from launch')
    inputs_record = json.loads((run / 'inputs.json').read_text())
    for field in ('caseSHA256', 'environmentSHA256', 'simulatorSHA256', 'weightsSHA256', 'policySHA256', 'receiptSHA256'):
        if inputs_record.get(field) != manifest[field]: raise ValueError(f'client input differs: {field}')
    if inputs_record.get('robotAssetSHA256') != manifest['assetSHA256'] or inputs_record.get('stoppedRescanEnabled') is not False:
        raise ValueError('client asset or intervention differs')
    journal = [json.loads(line) for line in (run / 'physical-agent.jsonl').read_text().splitlines()]
    validate_protocol(journal)
    if trace_last_tick(run / 'trace.jsonl') != journal[-1]['totalSteps']:
        raise ValueError('trace does not end at final stop observation')
    actor = hidden.check_actor_inputs(run, result, journal)
    actor_ticks = [row['totalSteps'] for row in journal if row.get('ack') == 1]
    if not actor_ticks: raise ValueError('no recorded actor actions')
    movement = hidden.truth_navigation_path(run / 'trace.jsonl', journal[0]['totalSteps'], actor_ticks[-1])
    tool = inputs / 'flex-source/exploration/manipulation_audit.py'
    completed = subprocess.run([sys.executable, '-I', str(tool), str(inputs / 'case.json'), str(run / 'trace.jsonl')],
                               cwd=ROOT, check=True, capture_output=True, text=True, timeout=180)
    manipulation = json.loads(completed.stdout)
    if manipulation.get('caseSHA256') != manifest['caseSHA256']: raise ValueError('manipulation case differs')
    previous = json.loads((trial / 'audit.json').read_text())
    if previous.get('manipulation') != manipulation or any(previous['actor'].get(key) != value for key, value in actor.items()):
        raise ValueError('fresh audit disagrees with trial report')
    outcome = classify(result, actor, manipulation, journal, movement); outcome['truthNavigation'] = movement
    outcome['caseSHA256'] = manifest['caseSHA256']; outcome['traceSHA256'] = result['traceSHA256']
    return outcome


def audit(root):
    try: return inspect(root)
    except (OSError, ValueError, KeyError, TypeError, IndexError, RuntimeError, OverflowError, json.JSONDecodeError, subprocess.SubprocessError) as error:
        return {'status': 'censored', 'reason': str(error),
                'scope': 'incomplete or invalid evidence; no outcome, goal pass or physical claim'}


if __name__ == '__main__':
    if len(sys.argv) != 2: raise SystemExit('Expected one hybrid trial output directory')
    print(json.dumps(audit(sys.argv[1]), sort_keys=True, allow_nan=False))
