#!/usr/bin/env python3
"""Bounded real-simulator relay; direct GPU launch is deliberately disabled."""
import json
import os
import signal
import socket
import struct
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RGB_BYTES = 640 * 480 * 3
MARKER = 'FAULT_TEST_SIM_STOP_ZERO'


def read_exact(sock, size):
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk: raise EOFError('short protocol stream')
        data.extend(chunk)
    return bytes(data)


def stop_process(process):
    if process is None: return
    if process.poll() is None:
        try: os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError: pass
        try: process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            process.wait(timeout=3)


def response(peer, sequence):
    header = read_exact(peer, 32)
    size, image_bytes, actual, contact = struct.unpack('<4q', header)
    if not 0 < size <= 65536 or image_bytes != RGB_BYTES or actual != sequence or contact not in (0, 1):
        raise ValueError('invalid simulator header')
    body = read_exact(peer, size); image = read_exact(peer, image_bytes)
    state = json.loads(body)
    return header, body, image, state


def run_arm(output, simulator_argv, probe, mode, env):
    """Run an arm under an external GPU, disk and absolute-deadline monitor.

    The relay modifies only the fault arm's second drive response header,
    after consuming the complete actual response. Simulator and probe remain
    separate processes. A missing input, timeout or marker censors the arm.
    """
    if mode not in ('control', 'fault'): raise ValueError('invalid mode')
    output = Path(output).absolute()
    if output.exists() or output.is_symlink(): raise FileExistsError('preserve existing arm')
    output.mkdir(); probe_socket, client_socket = socket.socketpair()
    sim_socket, child_socket = socket.socketpair()
    probe_socket.settimeout(30); sim_socket.settimeout(90)
    sim = client = None
    try:
        with (output / 'simulator.log').open('wb') as sim_log, (output / 'probe.log').open('wb') as client_log:
            argv = list(map(str, simulator_argv)) + ['--agent-fd', str(child_socket.fileno())]
            sim = subprocess.Popen(argv, cwd=ROOT, env=env, pass_fds=(child_socket.fileno(),),
                                   stdout=sim_log, stderr=subprocess.STDOUT, start_new_session=True)
            child_socket.close()
            argv = [str(probe), str(client_socket.fileno()), str(sim.pid), str(output), mode]
            client = subprocess.Popen(argv, cwd=ROOT, env=env, pass_fds=(client_socket.fileno(),),
                                      stdout=client_log, stderr=subprocess.STDOUT, start_new_session=True)
            client_socket.close(); requests = []; states = []
            for expected_sequence, expected_command in ((1, 1), (2, 2), (3, 2), (4, 3)):
                raw = read_exact(probe_socket, 64)
                command, sequence, steering, speed, hold, _, task, _ = struct.unpack('<8q', raw)
                if (command, sequence) != (expected_command, expected_sequence):
                    raise ValueError('unexpected probe command or sequence')
                requests.append({'command': command, 'sequence': sequence, 'steering': steering,
                                 'speed': speed, 'hold': hold, 'task': task})
                sim_socket.sendall(raw)
                if command == 3: break
                header, body, image, state = response(sim_socket, sequence)
                drive = state.get('controller', {}).get('drive', {})
                states.append({'step': state.get('totalSteps'), 'drive': drive,
                               'sequence': sequence})
                if mode == 'fault' and sequence == 3:
                    # The actual response was completely drained. Only the
                    # client-facing header is altered; no partial body follows.
                    size, image_bytes, _, contact = struct.unpack('<4q', header)
                    probe_socket.sendall(struct.pack('<4q', size, image_bytes, sequence + 1, contact))
                else:
                    probe_socket.sendall(header + body + image)
            client_code = client.wait(timeout=30); sim_code = sim.wait(timeout=30)
        log = (output / 'simulator.log').read_text(errors='replace')
        client_text = (output / 'probe.log').read_text(errors='replace')
        if sim_code != 0 or log.count(MARKER) != 1 or 'FAULT_TEST_SIM_STOP_NONZERO' in log:
            raise ValueError('simulator did not report zeroed command-3 stop')
        if mode == 'control' and client_code != 0: raise ValueError('control probe failed')
        if mode == 'fault' and (client_code == 0 or 'invalid simulator response' not in client_text or
                                'stop unverified' not in client_text):
            raise ValueError('fault was not reported by probe')
        if len(states) != 3 or not states[1]['drive'].get('leftSpeed') or not states[1]['drive'].get('rightSpeed'):
            raise ValueError('validated first drive was not nonzero')
        result = {'mode': mode, 'requests': requests, 'states': states, 'probeExit': client_code,
                  'simulatorExit': sim_code, 'simulatorStopZeroMarker': True,
                  'alteredHeaderSequence': 4 if mode == 'fault' else None,
                  'scope': 'instrumented virtual simulator and local relay; not a physical stop or execution attestation'}
        (output / 'result.json').write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
        return result
    finally:
        probe_socket.close(); sim_socket.close(); client_socket.close(); child_socket.close()
        stop_process(client); stop_process(sim)


def audit(control, fault):
    a = json.loads((Path(control) / 'result.json').read_text())
    b = json.loads((Path(fault) / 'result.json').read_text())
    if a['mode'] != 'control' or b['mode'] != 'fault': raise ValueError('arm modes differ')
    prefix = [
        {'command': 1, 'sequence': 1, 'steering': 0, 'speed': 0, 'hold': 10, 'task': 3},
        {'command': 2, 'sequence': 2, 'steering': 0, 'speed': 500, 'hold': 10, 'task': 3},
        {'command': 2, 'sequence': 3, 'steering': 0, 'speed': 500, 'hold': 10, 'task': 3},
    ]
    for path, item in ((Path(control), a), (Path(fault), b)):
        sim_log = (path / 'simulator.log').read_text(errors='replace')
        probe_log = (path / 'probe.log').read_text(errors='replace')
        stop = {'command': 3, 'sequence': 4, 'steering': 0, 'speed': 0,
                'hold': 10 if item['mode'] == 'control' else 0,
                'task': 3 if item['mode'] == 'control' else 0}
        if item.get('requests') != prefix + [stop]:
            raise ValueError('saved request sequence or drive command differs')
        states = item.get('states')
        if (not isinstance(states, list) or len(states) != 3 or
                any(type(state.get('step')) is not int or state.get('sequence') != index + 1
                    for index, state in enumerate(states)) or
                any(states[index]['step'] != states[0]['step'] + 10 * index for index in (1, 2))):
            raise ValueError('saved simulator response sequence or timing differs')
        for state in states[1:]:
            drive = state.get('drive', {})
            if (drive.get('leftSpeed'), drive.get('rightSpeed'), drive.get('steeringAngleDeg')) != (30, 30, 90):
                raise ValueError('saved drive echo does not match nonzero requested motion')
        if (sim_log.count(MARKER) != 1 or 'FAULT_TEST_SIM_STOP_NONZERO' in sim_log or
                item['simulatorExit'] != 0 or item['simulatorStopZeroMarker'] is not True):
            raise ValueError('saved simulator stop evidence differs')
        if item['mode'] == 'fault' and (item['probeExit'] == 0 or
                item['alteredHeaderSequence'] != 4 or 'invalid simulator response' not in probe_log or
                'stop unverified' not in probe_log): raise ValueError('saved fault evidence differs')
        if item['mode'] == 'control' and (item['probeExit'] != 0 or item['alteredHeaderSequence'] is not None):
            raise ValueError('saved control evidence differs')
    # The ordinary ve_command stop retains task/hold fields, whereas the
    # failure hook zeroes them. Compare the reset and drive requests only.
    if (a['requests'][:3] != b['requests'][:3] or a['states'][:2] != b['states'][:2] or
            (a['requests'][-1]['command'], a['requests'][-1]['sequence']) != (3, 4) or
            (b['requests'][-1]['command'], b['requests'][-1]['sequence']) != (3, 4)):
        raise ValueError('common protocol prefix differs')
    for name in ('decisions.jsonl',):
        left = (Path(control) / name).read_bytes().splitlines()
        right = (Path(fault) / name).read_bytes().splitlines()
        if len(left) != 2 or len(right) != 1 or left[:1] != right:
            raise ValueError('validated decision prefix differs')
        for index, raw in enumerate(left):
            decision = json.loads(raw)
            if (decision.get('sequence') != index + 2 or decision.get('step') != a['states'][index + 1]['step'] or
                    decision.get('action') != [0, 0.5] or
                    decision.get('state', {}).get('controller', {}).get('drive') != a['states'][index + 1]['drive']):
                raise ValueError('saved decision does not match simulator drive response')
    return {'status': 'diagnostic_only', 'nonzeroDrive': a['states'][1]['drive'],
            'faultStopSequence': b['requests'][-1]['sequence'], 'simulatorStopZeroMarker': True,
            'scope': 'matched local records; no physical stopping or neural-policy claim'}


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and resource supervision.')
