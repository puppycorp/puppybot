#!/usr/bin/env python3
"""Independent wire fixtures and live runtime checks for the native CLI."""
import base64
import hashlib
import json
from pathlib import Path
import signal
import socket
import struct
import subprocess
import tempfile
import threading
import time

from runtime import ROOT, Runtime, request, wait_online, wire

BIN = ROOT/'build/flex/puppybot'
CHECKS = 0


def check(condition, message):
    global CHECKS
    if not condition:
        raise AssertionError(message)
    CHECKS += 1


def execute(port, args, code=0):
    result = subprocess.run([str(BIN), '--url', f'ws://127.0.0.1:{port}/ws',
                             '--timeout-ms', '500', *args], capture_output=True, timeout=4)
    check(result.returncode == code, (args, result.returncode, result.stdout, result.stderr))
    return result


def arm_state():
    # One independent joint fixture, including the optional target extension.
    joint = struct.pack('<BBiihii fB', 7, 11, 1024, 1100, -123, 100, 3000, 90.25, 0)
    return b'\1\0\7\1'+joint+b'\1'+struct.pack('<fff', 1, -2, 3.5)+b'\1\1'+struct.pack('<f', 91.5)+b'\1'+struct.pack('<fff', 4, 5, 6)


class Fixture:
    def __init__(self, failure=None):
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen()
        self.listener.settimeout(3)
        self.port = self.listener.getsockname()[1]
        self.failure = failure
        self.commands = []
        self.error = None
        self.pong = False
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def exact(self, n):
        while len(self.buffer) < n:
            data = self.sock.recv(4096)
            if not data:
                raise EOFError()
            self.buffer += data
        out, self.buffer = self.buffer[:n], self.buffer[n:]
        return out

    def frame(self, opcode, data, fin=True):
        n = len(data)
        header = bytes([(128 if fin else 0)|opcode, n if n < 126 else 126])
        if n >= 126:
            header += struct.pack('>H', n)
        self.sock.sendall(header+data)

    def run(self):
        try:
            self.sock, _ = self.listener.accept()
            self.sock.settimeout(3)
            self.buffer = b''
            while b'\r\n\r\n' not in self.buffer:
                self.buffer += self.sock.recv(4096)
            header, self.buffer = self.buffer.split(b'\r\n\r\n', 1)
            key = next(line.split(b':', 1)[1].strip() for line in header.split(b'\r\n') if line.lower().startswith(b'sec-websocket-key:'))
            check(len(base64.b64decode(key, validate=True)) == 16, 'random client handshake nonce')
            accept = base64.b64encode(hashlib.sha1(key+b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest())
            if self.failure == 'handshake':
                accept = b'x'*28
            self.sock.sendall(b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: '+accept+b'\r\n\r\n')
            if self.failure == 'handshake':
                return
            while True:
                first, second = self.exact(2)
                check(bool(second & 128), 'client masks every frame')
                n = second & 127
                if n == 126:
                    n, = struct.unpack('>H', self.exact(2))
                key = self.exact(4)
                data = bytes(v ^ key[i % 4] for i, v in enumerate(self.exact(n)))
                opcode = first & 15
                if opcode == 10:
                    check(data == b'probe', 'client echoes WebSocket ping')
                    self.pong = True
                    continue
                if opcode == 1:
                    check(data == b'ping', 'historical text ping command')
                    self.frame(1, b'pong')
                    continue
                check(opcode == 2 and len(data) >= 4, 'binary protocol request')
                check(data[0] == 1 and len(data) == 4+struct.unpack_from('<H', data, 2)[0], 'protocol v1 length')
                self.commands.append(data)
                if self.failure == 'timeout':
                    continue
                if self.failure == 'masked':
                    self.sock.sendall(b'\x82\x83abcd'+bytes(v ^ b'abcd'[i % 4] for i, v in enumerate(b'\1\0\1')))
                    continue
                response = None
                if data[1] == 1:
                    response = b'\1\0\1'
                elif data[1] in (25, 26):
                    response = b'\1\0\10\1\5\1\2\3\4'
                elif data[1] == 33:
                    response = b'\1\0\7\4' if self.failure == 'telemetry' else arm_state()
                if response is not None:
                    # Exercise fragmented replies with interleaved control frames.
                    self.frame(2, response[:2], False)
                    self.frame(9, b'probe')
                    self.frame(0, response[2:])
        except EOFError:
            pass
        except BaseException as error:
            self.error = error
        finally:
            if hasattr(self, 'sock'):
                self.sock.close()

    def close(self):
        self.thread.join(timeout=4)
        self.listener.close()
        check(not self.thread.is_alive(), 'fixture terminated')
        if self.error:
            raise self.error


def command_fixtures():
    cases = [
        (['ping'], [wire(1)]),
        (['ws-ping'], []),
        (['config', 'get'], [wire(25)]),
        (['config', 'set', '--steering-servo-id', '5', '--arm-servo-ids', '1,2,3,4'], [wire(26, b'\1\5\1\2\3\4')]),
        (['drive', 'steer', '--throttle', '-100', '--steering', '127'], [wire(27, struct.pack('<bb', -100, 127))]),
        (['drive', 'stop'], [wire(28)]),
        (['arm', 'state'], [wire(33, b'\1\1')]),
        (['arm', 'stop'], [wire(31)]),
        (['arm', 'stop', '--joint', '3'], [wire(14, b'\3')]),
        (['arm', 'jog', '--joint', '2', '--direction', '-1', '--speed', '456', '--duration-ms', '1'], [wire(13, struct.pack('<BbH', 2, -1, 456)), wire(1), wire(14, b'\2')]),
        (['arm', 'hold', '--speed', '321'], [wire(19, struct.pack('<H', 321))]),
        (['arm', 'goto-ticks', '-1', '2147483647', '-2147483648', '4096'], [wire(16, struct.pack('<Hiiii', 300, -1, 2147483647, -2147483648, 4096))]),
        (['arm', 'goto-angles', '10.25', '-20', '30', '-40.5'], [wire(17, struct.pack('<Hffff', 300, 10.25, -20, 30, -40.5))]),
        (['arm', 'goto-coords', '1', '2', '3', '4'], [wire(18, struct.pack('<Hffff', 300, 1, 2, 3, 4))]),
        (['arm', 'move-tcp', '--frame', 'yaw-flat', '--forward', '2.5', '--back', '1', '--right', '3', '--up', '4'], [wire(23, struct.pack('<HBfff', 300, 2, 1.5, -3, 4))]),
        (['arm', 'tcp-jog', 'start', '--frame', 'tool', '--left', '1', '--speed', '120', '--duration-ms', '1'], [wire(12, struct.pack('<H', 120)), wire(34, struct.pack('<Bffff', 1, 0, 1, 0, 120)), wire(1), wire(35)]),
        (['arm', 'tcp-jog', 'stop'], [wire(35)]),
        (['arm', 'set-joint-tick', '--joint', '1', '--tick', '-345'], [wire(20, struct.pack('<BHi', 1, 300, -345))]),
        (['arm', 'clear-faults'], [wire(24, b'\xff')]),
        (['arm', 'clear-faults', '--joint', '0'], [wire(24, b'\0')]),
        (['arm', 'servo-set', '--servo-id', '253', '--angle-deg', '300', '--duration-ms', '50'], [wire(32, struct.pack('<BHH', 253, 300, 50))]),
    ]
    for args, expected in cases:
        fixture = Fixture()
        try:
            result = execute(fixture.port, ['--json', *args])
            output = json.loads(result.stdout)
            if args == ['arm', 'state']:
                check(output['joints'][0]['speed'] == -123 and output['joints'][0]['target_angle_deg'] == 91.5, 'independent telemetry fields')
                check(output['coords_mm'] == [1, -2, 3.5] and output['target_coords_mm'] == [4, 5, 6], 'independent telemetry coordinates')
            elif args == ['config', 'get']:
                check(output == {'steering_servo_id': 5, 'arm_servo_ids': [1, 2, 3, 4]}, 'config JSON')
        finally:
            fixture.close()
        response_commands = (1, 25, 26, 33)
        wanted = expected if not expected or expected[-1][1] in response_commands else expected+[wire(1)]
        check(fixture.commands == wanted, (args, fixture.commands, wanted))
    for failure, args in [('handshake', ['ping']), ('masked', ['ping']), ('timeout', ['ping']), ('telemetry', ['arm', 'state'])]:
        fixture = Fixture(failure)
        try:
            check(bool(execute(fixture.port, args, 1).stderr), ('error reported', failure))
        finally:
            fixture.close()


def invalid_arguments():
    cases = [[], ['arm'], ['arm', 'jog'], ['arm', 'jog', '--joint', '4', '--direction', '1'],
             ['drive', 'steer', '--throttle', '128', '--steering', '0'],
             ['arm', 'goto-ticks', '1', '2', '3', '2147483648'],
             ['arm', 'goto-angles', 'nan', '1', '2', '3'],
             ['arm', 'goto-coords', '1e40', '1', '2', '3'],
             ['arm', 'move-tcp', '--forward', '3e38', '--back', '-3e38'],
             ['arm', 'hold', '--speed', '-32768'], ['arm', 'tcp-jog', 'start'],
             ['config', 'set', '--arm-servo-ids', '1,2,3,4,'],
             ['ping', '--nonsense'], ['ping', '--url'], ['ping', '--json', '--json'],
             ['arm', 'move-tcp', '--frame', 'tool', '--frame', 'base'],
             ['arm', 'hold', '--speed', '1', '--speed', '2'], ['ping', '--timeout-ms', '0']]
    for args in cases:
        result = subprocess.run([str(BIN), *args], capture_output=True, timeout=2)
        check(result.returncode == 2, ('invalid arguments', args, result.returncode, result.stderr))


def live_runtime(directory):
    runtime = Runtime(directory/'cli.json')
    try:
        wait_online(runtime.port)
        check(execute(runtime.port, ['ping']).stdout == b'pong\n', 'live protocol ping')
        check(execute(runtime.port, ['ws-ping']).stdout == b'pong\n', 'live text ping')
        check(len(json.loads(execute(runtime.port, ['--json', 'arm', 'state']).stdout)['joints']) == 4, 'live arm telemetry')
        execute(runtime.port, ['drive', 'steer', '--throttle', '50', '--steering', '10'])
        check(request(runtime.port, '/api/state')[1]['drive']['active'], 'CLI to HTTP controller state')
        execute(runtime.port, ['drive', 'stop'])
        check(not request(runtime.port, '/api/state')[1]['drive']['active'], 'CLI drive stop barrier')
        process = subprocess.Popen([str(BIN), '--url', f'ws://127.0.0.1:{runtime.port}/ws',
                                    'arm', 'jog', '--joint', '0', '--direction', '1', '--duration-ms', '5000'],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            for _ in range(100):
                if request(runtime.port, '/api/state')[1]['arm']['joints'][0]['speed']:
                    break
                time.sleep(.005)
            else:
                raise AssertionError('timed CLI jog never started')
            process.send_signal(signal.SIGINT)
            out, err = process.communicate(timeout=3)
            check(process.returncode == 130, ('timed CLI interrupt', out, err, process.returncode))
            check(request(runtime.port, '/api/state')[1]['arm']['joints'][0]['speed'] == 0, 'interrupt sends joint stop')
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
    finally:
        runtime.close()


def main():
    invalid_arguments()
    command_fixtures()
    with tempfile.TemporaryDirectory(prefix='cli-test-', dir=ROOT/'build/flex') as temporary:
        live_runtime(Path(temporary))
    print(f'Native CLI: {CHECKS} wire/argument/loopback checks passed')


if __name__ == '__main__':
    main()
