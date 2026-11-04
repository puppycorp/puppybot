#!/usr/bin/env python3
"""Audit terminal failure and subsequent stop in a recorded simulator run.

Usage: audit.py RUN_DIRECTORY
This is an additional diagnostic, not a trial monitor or delivery verifier.
"""
import hashlib
import json
import sys
from pathlib import Path


SCHEMA = 'puppybot.physical-agent.v1'


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON field')
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError('non-finite JSON value: ' + value)


def parse(text):
    return json.loads(text, object_pairs_hook=unique_object, parse_constant=reject_constant)


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(part)
    return h.hexdigest()


def json_rows(path):
    with path.open(encoding='utf-8') as stream:
        return [parse(line) for line in stream]


def nonnegative_integer(value):
    return type(value) is int and value >= 0


def bounded_reason(value):
    return isinstance(value, str) and '\0' not in value and 1 <= len(value.encode('utf-8')) <= 128


def verify_response(row, ack):
    if not isinstance(row, dict) or row.get('schema') != SCHEMA or any(
        not nonnegative_integer(row.get(key)) for key in ('sequence', 'step', 'totalSteps', 'timeMs', 'owner', 'ack')
    ):
        raise ValueError('invalid physical-agent response')
    if row['ack'] != ack or row['owner'] != 2 or row['step'] != row['totalSteps']:
        raise ValueError('invalid terminal/stop acknowledgment')
    if (row.get('driveCommand') != [0, 0, 90] or
            not isinstance(row['driveCommand'], list) or
            any(type(x) is not int for x in row['driveCommand'])):
        raise ValueError('terminal/stop response is not zero drive')
    if (row.get('imageValid') is not False or 'rgbDetections' not in row or row.get('rgbDetections') is not None or
            row.get('cameraFrame') != -1 or row.get('cameraDriving') is not False or
            row.get('cameraStill') is not False):
        raise ValueError('invalid terminal camera fields')


def verify_intent(row, sequence, command):
    if (not isinstance(row, dict) or set(row) != {'sequence', 'command', 'steering', 'speed', 'hold'} or
            any(type(value) is not int for value in row.values()) or
            row['sequence'] != sequence or row['command'] != command or row['steering'] != 0 or row['speed'] != 0):
        raise ValueError('invalid final command intent')
    if (command == 3 and row['hold'] != 0) or (command == 7 and not 1 <= row['hold'] <= 20):
        raise ValueError('invalid final command duration')


def trace_at(path, step):
    matched = None; previous = -1
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            row = parse(line)
            if not isinstance(row, dict) or not nonnegative_integer(row.get('step')) or row['step'] <= previous:
                raise ValueError('invalid trace order')
            previous = row['step']
            if row['step'] == step:
                matched = row
    if matched is None or previous != step:
        raise ValueError('terminal step is not the trace endpoint')
    return matched


def audit(run):
    run = Path(run)
    files = {name: run / name for name in ('physical-agent.jsonl', 'search-requests.jsonl', 'trace.jsonl', 'result.json')}
    before = {name: digest(path) for name, path in files.items()}
    journal = json_rows(files['physical-agent.jsonl']); intents = json_rows(files['search-requests.jsonl'])
    result = parse(files['result.json'].read_text(encoding='utf-8'))
    if not isinstance(result, dict) or len(journal) < 3 or len(intents) != len(journal):
        raise ValueError('missing protocol evidence')
    for index, (row, intent) in enumerate(zip(journal, intents), 1):
        if (not isinstance(row, dict) or type(row.get('sequence')) is not int or row['sequence'] != index or
                not isinstance(intent, dict) or type(intent.get('sequence')) is not int or intent['sequence'] != index):
            raise ValueError('protocol sequence differs')
    if any(row.get('ack') in (5, 7) or 'collectorFailure' in row for row in journal[:-2]):
        raise ValueError('earlier terminal, stop, or failure detail')
    terminal, stopped = journal[-2:]; prev = journal[-3]
    verify_response(terminal, 5); verify_response(stopped, 7)
    verify_intent(intents[-2], terminal['sequence'], 7); verify_intent(intents[-1], stopped['sequence'], 3)
    if (not isinstance(prev, dict) or prev.get('schema') != SCHEMA or
            type(prev.get('owner')) is not int or prev['owner'] != 1 or
            type(prev.get('ack')) is not int or prev['ack'] not in (3, 4, 8) or
            not nonnegative_integer(prev.get('step')) or not nonnegative_integer(prev.get('totalSteps')) or
            prev['step'] != prev['totalSteps'] or not nonnegative_integer(prev.get('timeMs'))):
        raise ValueError('collector was not previously active')
    delta = terminal['step'] - prev['step']
    if (not 0 <= delta <= intents[-2]['hold'] or terminal['timeMs'] - prev['timeMs'] != 20 * delta or
            stopped['step'] != terminal['step'] or stopped['timeMs'] != terminal['timeMs']):
        raise ValueError('terminal/stop time differs')
    reason = terminal.get('collectorFailure')
    if not bounded_reason(reason) or 'collectorFailure' in stopped:
        raise ValueError('invalid terminal failure detail')
    if (result.get('collectorTerminal') is not True or result.get('stopCommandAcknowledged') is not True or
            result.get('outcome') != 'unverified' or result.get('collectorFailure') != reason or
            'collectorFailureReportInvalid' in result or result.get('traceSHA256') != before['trace.jsonl']):
        raise ValueError('result does not preserve terminal failure and stop')
    snapshot = trace_at(files['trace.jsonl'], terminal['step'])
    case = snapshot.get('case')
    if (snapshot.get('schema') != 'puppybot.sim.v1' or
            not nonnegative_integer(snapshot.get('totalSteps')) or snapshot['totalSteps'] != terminal['step'] or
            not nonnegative_integer(snapshot.get('timeMs')) or snapshot['timeMs'] != terminal['timeMs'] or not isinstance(case, dict) or
            case.get('phase') != 'failed' or case.get('passed') is not False or case.get('reason') != reason):
        raise ValueError('terminal failure contradicts simulator trace')
    after = {name: digest(path) for name, path in files.items()}
    if before != after:
        raise ValueError('run evidence changed during audit')
    return {'schema': 'puppybot.sim-terminal-failure-audit.v1', 'status': 'consistent_simulator_failure_report',
            'terminalSequence': terminal['sequence'], 'terminalStep': terminal['step'], 'failure': reason,
            'stopSequence': stopped['sequence'], 'evidenceSHA256': before,
            'scope': 'saved local protocol and simulator trace only; no execution attestation, physical braking or delivery claim'}


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    try:
        print(json.dumps(audit(sys.argv[1]), indent=2, sort_keys=True))
    except (OSError, ValueError, TypeError, UnicodeError) as error:
        raise SystemExit('Invalid terminal failure evidence: ' + str(error))
