#!/usr/bin/env python3
"""Real loopback HTTP/WebSocket and Linux PTY STServo integration tests."""
import base64
import copy
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import select
import signal
import socket
import struct
import subprocess
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT/'build/flex/puppybot-runtime'
CHECKS = 0


def check(condition, message):
    global CHECKS
    if not condition:
        raise AssertionError(message)
    CHECKS += 1


def request(port, path, body=None, method=None):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
    payload = None if body is None else json.dumps(body)
    conn.request(method or ('GET' if body is None else 'POST'), path, payload, {'Content-Type': 'application/json'})
    response = conn.getresponse()
    data = response.read()
    status = response.status
    conn.close()
    return status, json.loads(data)


def raw_http(port, data):
    with socket.create_connection(('127.0.0.1', port), timeout=2) as sock:
        sock.sendall(data)
        result = b''
        while b'\r\n' not in result:
            result += sock.recv(4096)
        return int(result.split(b' ', 2)[1])


def wire(command, body=b''):
    return bytes([1, command])+struct.pack('<H', len(body))+body


class WebSocket:
    def __init__(self, port):
        self.sock = socket.create_connection(('127.0.0.1', port), timeout=2)
        key = base64.b64encode(os.urandom(16))
        self.sock.sendall(b'GET /ws HTTP/1.1\r\nHost: localhost\r\nUpgrade: WebSocket\r\nConnection: keep-alive, Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: '+key+b'\r\n\r\n')
        self.buffer = b''
        while b'\r\n\r\n' not in self.buffer:
            self.buffer += self.sock.recv(4096)
        header, self.buffer = self.buffer.split(b'\r\n\r\n', 1)
        check(header.startswith(b'HTTP/1.1 101 '), header)
        accept = base64.b64encode(hashlib.sha1(key+b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest())
        check(b'Sec-WebSocket-Accept: '+accept in header, 'independent handshake digest')

    def send(self, payload, opcode=2, fin=True, masked=True):
        n = len(payload)
        frame = bytes([(128 if fin else 0)|opcode, (128 if masked else 0)|(n if n < 126 else 126)])
        if n >= 126:
            frame += struct.pack('>H', n)
        if masked:
            key = os.urandom(4)
            frame += key+bytes(v ^ key[i % 4] for i, v in enumerate(payload))
        else:
            frame += payload
        self.sock.sendall(frame)

    def exact(self, n):
        while len(self.buffer) < n:
            data = self.sock.recv(4096)
            if not data:
                raise EOFError('websocket closed')
            self.buffer += data
        out, self.buffer = self.buffer[:n], self.buffer[n:]
        return out

    def receive(self):
        first, second = self.exact(2)
        check(not second & 128, 'server frames must be unmasked')
        n = second & 127
        if n == 126:
            n, = struct.unpack('>H', self.exact(2))
        elif n == 127:
            n, = struct.unpack('>Q', self.exact(8))
        return first & 15, self.exact(n)

    def binary(self, message):
        deadline = time.monotonic()+2
        while time.monotonic() < deadline:
            opcode, data = self.receive()
            if opcode == 2 and len(data) >= 3 and data[2] == message:
                return data
        raise AssertionError('expected protocol response')

    def barrier(self):
        self.send(wire(1))
        check(self.binary(1) == b'\1\0\1', 'protocol ping barrier')

    def close(self):
        self.sock.close()


class Runtime:
    def __init__(self, config, device=None):
        args = [str(BIN), '--bind', '127.0.0.1:0', '--config', str(config)]
        args += ['--servo-device', device] if device else ['--fake']
        self.process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        ready, _, _ = select.select([self.process.stdout], [], [], 5)
        if not ready:
            self.process.kill()
            raise AssertionError('runtime startup timeout')
        line = self.process.stdout.readline()
        found = re.search(r'port (\d+)', line)
        if not found:
            error = self.process.stderr.read() if self.process.poll() is not None else line
            self.process.kill()
            raise AssertionError(('runtime startup', line, error))
        self.port = int(found[1])

    def close(self):
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGTERM)
        self.process.wait(timeout=3)
        error = self.process.stderr.read()
        check(self.process.returncode == 0, ('runtime clean shutdown', self.process.returncode, error))
        self.process.stdout.close()
        self.process.stderr.close()


def wait_online(port):
    for _ in range(100):
        status, state = request(port, '/api/state')
        if status == 200 and all(j['online'] for j in state['arm']['joints']):
            return state
        time.sleep(.01)
    raise AssertionError('servo feedback never became online')


def fake_runtime(directory):
    config = directory/'calibration.json'
    runtime = Runtime(config)
    port = runtime.port
    sockets = []
    try:
        state = wait_online(port)
        check(state['schema'] == 'puppybot.runtime.state.v1' and state['mode'] == 'fake', 'runtime state schema')
        status, config_state = request(port, '/api/config.json')
        check(status == 200 and config_state['config']['drive']['steering_servo_id'] == 5, 'safe separate fake steering')
        check(request(port, '/api/arm/speed', {'speed': -1})[0] == 400, 'invalid API speed')
        check(request(port, '/api/arm/goto-angles', {'yawDeg': 1e300, 'shoulderDeg': 90, 'elbowDeg': 90, 'wristDeg': 90})[0] == 400, 'huge joint angles rejected without wrapping loop')
        check(request(port, '/api/arm/coordinates/move', {'xMm': 50, 'yMm': 0, 'zMm': 100, 'toolPhiDeg': 1e300})[0] == 400, 'huge tool pitch rejected without wrapping loop')
        check(request(port, '/api/arm/speed', {'speed': 123})[1]['state']['ui']['armSpeed'] == 123, 'API arm speed')
        check(request(port, '/api/drive', {'action': 'forward'})[1]['state']['drive']['leftSpeed'] == 35, 'API drive forward')
        time.sleep(.62)
        check(request(port, '/api/state')[1]['drive']['active'], 'REST held drive survives wire watchdog')
        check(not request(port, '/api/drive/stop', {})[1]['state']['drive']['active'], 'API drive stop')
        check(request(port, '/api/arm/nope', {})[0] == 404, 'unknown API command')
        check(request(port, '/api/arm/stop', {}, 'PUT')[0] == 405, 'API method guard')
        check(request(port, '/api/sim/captures/screenshot', {})[0] == 409, 'fake bus never pretends to implement physics captures')
        check(request(port, '/api/autonomy/state')[1]['schema'] == 'puppybot.runtime.autonomy-observation.v1', 'restricted observation schema')
        first = WebSocket(port); second = WebSocket(port); sockets += [first, second]
        first.send(wire(25)); response = first.binary(8)
        check(response == bytes([1, 0, 8, 1, 5, 1, 2, 3, 4]), 'config v1 response')
        first.send(b'ping', 1); check(first.receive() == (1, b'pong'), 'historical text ping')
        first.send(wire(33, b'\1\1')); frame = first.binary(7)
        check(frame[:4] == b'\1\0\7\4' and len(frame) >= 151, 'telemetry target extension')
        second.barrier(); second.sock.settimeout(.08)
        try:
            second.receive()
        except socket.timeout:
            pass
        else:
            raise AssertionError('subscription leaked across clients')
        second.sock.settimeout(2)
        first.send(wire(33, b'\1\0')); first.barrier()
        second.send(wire(1)[:2], fin=False); second.send(b'between', 9); second.send(wire(1)[2:], opcode=0)
        check(second.receive() == (10, b'between'), 'control frame between data fragments')
        check(second.binary(1) == b'\1\0\1', 'fragmented protocol frame')
        second.send(wire(27, struct.pack('<bb', 70, -100))); second.barrier()
        drive = request(port, '/api/state')[1]['drive']
        check(drive['leftSpeed'] == 70 and drive['steeringAngleDeg'] == 45, 'wire command reaches shared controller')
        time.sleep(.6)
        check(not request(port, '/api/state')[1]['drive']['active'], 'wire drive timeout is not refreshed')
        second.send(wire(13, struct.pack('<BbH', 0, 1, 300))); second.barrier()
        time.sleep(.1)
        check(request(port, '/api/state')[1]['arm']['joints'][0]['tick'] > 2048, 'fake bus integrates real wheel writes')
        time.sleep(1.1)
        check(request(port, '/api/state')[1]['arm']['joints'][0]['speed'] == 0, 'free-spin command deadman')
        check(request(port, '/api/arm/clear-faults', {})[0] == 200, 'API clear fault')
        check(request(port, '/api/arm/joints/0/spin', {'direction': 1})[0] == 200, 'server-held joint jog')
        time.sleep(1.1)
        check(request(port, '/api/state')[1]['arm']['joints'][0]['speed'] != 0, 'REST held joint jog refreshes')
        check(request(port, '/api/arm/joints/0/stop', {})[0] == 200, 'release server-held jog')
        check(request(port, '/api/arm/joints/0/limits', {'minTick': 100, 'maxTick': 3900})[0] == 200, 'edit soft limits')
        check(request(port, '/api/arm/joints/0/reference', {'angleDeg': 42.25})[0] == 200, 'calibrate observed reference')
        check(request(port, '/api/arm/coordinate-calibration/flip-left', {})[0] == 200, 'coordinate sign calibration')
        check(request(port, '/api/arm/coordinate-calibration/rotate-base', {})[0] == 200, 'coordinate yaw calibration')
        check(request(port, '/api/config.json')[1]['dirty'], 'calibration dirty tracking')
        check(request(port, '/api/calibration/save', {})[0] == 200, 'atomic calibration save')
        persisted = json.loads(config.read_text())
        check(persisted['coordinate']['left_sign'] == -1 and persisted['coordinate']['base_yaw_offset_deg'] == 90, 'saved coordinate calibration')
        check(persisted['arm']['joints'][0]['tick_min'] == 100 and abs(persisted['arm']['joints'][0]['reference_angle_deg'] - 42.25) < 1e-12, 'saved joint calibration')
        check(not request(port, '/api/config.json')[1]['dirty'], 'save clears dirty only after success')
        check(not list(directory.glob('*.tmp.*')), 'no leftover temporary calibration files')
        check(raw_http(port, b'GET / HTTP/1.1\r\nHost: a\r\nHost: b\r\n\r\n') == 400, 'duplicate Host rejected')
        check(raw_http(port, b'POST /api/arm/stop HTTP/1.1\r\nHost: a\r\nContent-Length: 8193\r\n\r\n') == 413, 'oversized body rejected')
        check(raw_http(port, b'POST /api/arm/stop HTTP/1.1\r\nHost: a\r\nTransfer-Encoding: chunked\r\n\r\n') == 501, 'unsupported transfer framing rejected')
        slow = socket.create_connection(('127.0.0.1', port)); sockets.append(slow); slow.sendall(b'GET / HTTP/1.1\r\nHost: ')
        before = request(port, '/api/state')[1]['timeMs']; time.sleep(.08)
        check(request(port, '/api/state')[1]['timeMs'] > before + 50, 'partial HTTP client does not stall controller clock')
        for payload, opcode, masked, expected in [(wire(1), 2, False, 1002), (b'\xff', 1, True, 1007), (b'x'*2049, 2, True, 1009)]:
            ws = WebSocket(port); ws.send(payload, opcode, masked=masked); kind, body = ws.receive(); ws.close()
            check(kind == 8 and struct.unpack('>H', body[:2])[0] == expected, 'WebSocket protocol error close code')
        for _ in range(30):
            check(request(port, '/health')[0] == 200, 'listener remains healthy after connection churn')
    finally:
        for sock in sockets:
            sock.close()
        runtime.close()
    restarted = Runtime(config)
    try:
        wait_online(restarted.port)
        actual = request(restarted.port, '/api/config.json')[1]['config']
        check(actual == persisted, 'saved calibration survives restart')
        state = request(restarted.port, '/api/state')[1]
        check(abs(state['arm']['joints'][0]['angleDeg'] - 42.25) < 1e-4, 'restarted reference maps feedback correctly')
    finally:
        restarted.close()
    return persisted


class ServoEmulator:
    def __init__(self, config):
        self.master, slave = os.openpty()
        self.path = os.ttyname(slave)
        self.slave = slave
        self.stop = threading.Event()
        self.positions = {j['servo_id']: j['reference_tick'] for j in config['arm']['joints']}
        self.positions[config['drive']['steering_servo_id']] = 1535
        self.modes = {i: 0 for i in self.positions}
        self.speeds = {i: 0 for i in self.positions}
        self.writes = []
        self.drop = set()
        self.error = None
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        pending = b''
        try:
            while not self.stop.is_set():
                readable, _, _ = select.select([self.master], [], [], .01)
                if not readable:
                    continue
                pending += os.read(self.master, 4096)
                while len(pending) >= 4:
                    start = pending.find(b'\xff\xff')
                    if start < 0:
                        pending = pending[-1:]
                        break
                    pending = pending[start:]
                    if len(pending) < 4:
                        break
                    size = pending[3] + 4
                    if len(pending) < size:
                        break
                    packet, pending = pending[:size], pending[size:]
                    check(packet[-1] == (~sum(packet[2:-1]) & 255), 'actual PTY request checksum')
                    servo, instruction, params = packet[2], packet[4], packet[5:-1]
                    self.writes.append(packet)
                    if servo not in self.positions or servo in self.drop:
                        continue
                    data = b''
                    if instruction == 2:
                        check(params == bytes([56, 2]), 'actual PTY position register read')
                        data = struct.pack('<H', self.positions[servo])
                    elif instruction == 3:
                        if params[0] == 33:
                            self.modes[servo] = params[1]
                        elif params[0] == 41:
                            value, = struct.unpack('<H', params[6:8])
                            if self.modes[servo]:
                                self.speeds[servo] = -(value & 32767) if value & 32768 else value
                            else:
                                self.positions[servo], = struct.unpack('<H', params[2:4])
                    reply = bytes([255, 255, servo, len(data)+2, 0])+data
                    reply += bytes([~sum(reply[2:]) & 255])
                    os.write(self.master, reply[:2]); time.sleep(.0002)
                    os.write(self.master, reply[2:3]); time.sleep(.0002)
                    os.write(self.master, reply[3:])
        except (OSError, ValueError):
            if not self.stop.is_set():
                self.error = 'PTY unexpectedly closed'
        except BaseException as error:
            self.error = error

    def close(self):
        self.stop.set()
        self.thread.join(timeout=1)
        os.close(self.master)
        os.close(self.slave)
        check(self.error is None, self.error)


def serial_runtime(directory, config):
    path = directory/'serial.json'
    config['drive']['steering_servo_id'] = 5
    path.write_text(json.dumps(config))
    emulator = ServoEmulator(config)
    runtime = Runtime(path, emulator.path)
    ws = None
    try:
        state = wait_online(runtime.port)
        check(state['mode'] == 'hardware', 'PTY exercises the actual hardware adapter')
        ws = WebSocket(runtime.port)
        ws.send(wire(27, struct.pack('<bb', 50, 100))); ws.barrier()
        time.sleep(.12)
        check(any(p[2] == 5 and p[4] == 3 and p[5] == 41 for p in emulator.writes), 'actual steering position packet sent to ID 5')
        check(not any(p[2] == 1 and p[4] == 3 and p[5] == 41 and p[11:13] == struct.pack('<H', 2400) for p in emulator.writes), 'steering never writes the arm yaw servo')
        ws.send(wire(13, struct.pack('<BbH', 0, 1, 300))); ws.barrier(); time.sleep(.08)
        check(emulator.modes[1] == 1 and emulator.speeds[1] > 0, 'mode acknowledgement gates actual wheel write')
        emulator.drop.add(1)
        start = time.monotonic(); status, _ = request(runtime.port, '/api/state')
        check(status == 200 and time.monotonic()-start < .5, 'serial response timeout does not block network loop')
        time.sleep(.3)
        state = request(runtime.port, '/api/state')[1]
        check(not state['arm']['joints'][0]['online'] and state['arm']['joints'][0]['speed'] == 0, 'serial feedback loss stops controller output')
        emulator.drop.clear()
        wait_online(runtime.port)
        request(runtime.port, '/api/arm/clear-faults', {})
        ws.send(wire(13, struct.pack('<BbH', 0, 1, 300))); ws.barrier(); time.sleep(.05)
    finally:
        if ws:
            ws.close()
        runtime.close()
        check(all(speed == 0 for servo, speed in emulator.speeds.items() if servo != 5), 'SIGTERM sends acknowledged zero wheel speeds')
        emulator.close()


def serial_reconnect(directory, config):
    config_path = directory/'reconnect.json'
    config_path.write_text(json.dumps(config))
    device = directory/'selected-servo-bus'
    emulator = ServoEmulator(config)
    device.symlink_to(emulator.path)
    runtime = Runtime(config_path, str(device))
    ws = None
    try:
        wait_online(runtime.port)
        check(request(runtime.port, '/api/arm/joints/0/spin', {'direction': 1})[0] == 200, 'held motion before serial disconnect')
        time.sleep(.05)
        device.unlink()
        emulator.close()
        emulator = None
        for _ in range(100):
            state = request(runtime.port, '/api/state')[1]
            if not any(j['online'] for j in state['arm']['joints']):
                break
            time.sleep(.01)
        else:
            raise AssertionError('serial disconnect never observed')
        check(request(runtime.port, '/api/drive', {'action': 'forward'})[0] == 409, 'disconnected REST rejects movement')
        ws = WebSocket(runtime.port)
        ws.send(wire(27, struct.pack('<bb', 100, 0)))
        ws.send(wire(13, struct.pack('<BbH', 0, 1, 300)))
        ws.barrier()
        check(not request(runtime.port, '/api/state')[1]['drive']['active'], 'disconnected wire ignores movement')
        emulator = ServoEmulator(config)
        device.symlink_to(emulator.path)
        state = wait_online(runtime.port)
        time.sleep(.25)
        check(all(speed == 0 for speed in emulator.speeds.values()), 'reconnect never resumes held or offline motion')
        check(state['arm']['mode'] == 'Idle', 'reconnect clears arm target mode')
        request(runtime.port, '/api/arm/clear-faults', {})
        ws.send(wire(13, struct.pack('<BbH', 0, 1, 300))); ws.barrier()
        time.sleep(.05)
        check(emulator.modes[1] == 1 and emulator.speeds[1] > 0, 'new command works after reconnect and mode acknowledgement')
    finally:
        if ws:
            ws.close()
        runtime.close()
        if emulator:
            emulator.close()


def config_boundaries(directory, config):
    cases = [('version', lambda c: c.update(version=2)),
             ('serial', lambda c: c.update(serial='x'*33)),
             ('duplicate ID', lambda c: c['arm']['joints'][1].update(servo_id=c['arm']['joints'][0]['servo_id'])),
             ('conflicting alias', lambda c: c['arm']['joints'][0].update(soft_tick_min=c['arm']['joints'][0]['tick_min']+1)),
             ('reference angle', lambda c: c['arm']['joints'][0].update(reference_angle_deg=1e300)),
             ('negative timeout', lambda c: c['drive'].update(command_timeout_ms=-1))]
    path = directory/'boundary.json'
    for name, mutate in cases:
        candidate = copy.deepcopy(config)
        mutate(candidate)
        path.write_text(json.dumps(candidate))
        result = subprocess.run([str(BIN), '--fake', '--config', str(path), '--bind', '127.0.0.1:0', '--ticks', '1'],
                                capture_output=True, timeout=2)
        check(result.returncode == 2, ('invalid configuration rejected', name, result.returncode, result.stderr))
    candidate = copy.deepcopy(config)
    candidate['drive']['command_timeout_ms'] = 2**64-1
    candidate['coordinate']['base_yaw_offset_deg'] = 1e300
    path.write_text(json.dumps(candidate))
    runtime = Runtime(path)
    ws = None
    try:
        status, state = request(runtime.port, '/api/config.json')
        check(status == 200 and state['config']['drive']['command_timeout_ms'] == 2**64-1, 'unsigned timeout JSON round trip')
        result = request(runtime.port, '/api/arm/coordinate-calibration/rotate-base', {})
        check(result[0] == 200, 'huge finite base offset rotation finishes')
        offset = request(runtime.port, '/api/config.json')[1]['config']['coordinate']['base_yaw_offset_deg']
        check(offset == (1e300+90) % 360, 'base rotation matches independent floating remainder')
        ws = WebSocket(runtime.port)
        ws.send(wire(27, struct.pack('<bb', 50, 0))); ws.barrier()
        time.sleep(.03)
        check(request(runtime.port, '/api/state')[1]['drive']['active'], 'u64 maximum timeout does not expire as signed negative')
        ws.send(wire(18, struct.pack('<Hffff', 200, 50, 0, 100, 1e30))); ws.barrier()
        check(request(runtime.port, '/health')[0] == 200, 'huge wire tool pitch cannot stall the runtime')
    finally:
        if ws:
            ws.close()
        runtime.close()


def main():
    with tempfile.TemporaryDirectory(prefix='runtime-test-', dir=ROOT/'build/flex') as temporary:
        directory = Path(temporary)
        config = fake_runtime(directory)
        serial_runtime(directory, config)
        serial_reconnect(directory, config)
        config_boundaries(directory, config)
    print(f'Native runtime: {CHECKS} loopback/PTY checks passed')


if __name__ == '__main__':
    main()
