#!/usr/bin/env python3
"""Send bounded serial commands to the Flexscript ESP32 firmware (stdlib only)."""
import argparse
import binascii
import fcntl
import json
import os
import select
import shlex
import struct
import termios
import time


def envelope(kind, payload=b''):
    if len(payload) > 256:
        raise ValueError('payload exceeds 256 bytes')
    body = struct.pack('<BBH', 1, kind, len(payload)) + payload
    return b'PB' + body + struct.pack('<H', binascii.crc_hqx(body, 65535))


class Parser:
    def __init__(self):
        self.buffer = bytearray()
        self.last = 0

    def feed(self, data):
        now = time.monotonic()
        if now-self.last > .1:
            self.buffer.clear()
        self.last = now
        self.buffer.extend(data)
        rows = []
        while len(self.buffer) >= 2:
            if self.buffer[:2] != b'PB':
                del self.buffer[0]
                continue
            if len(self.buffer) < 6:
                break
            version, kind, size = struct.unpack_from('<BBH', self.buffer, 2)
            if version != 1 or size > 256:
                del self.buffer[0]
                continue
            if len(self.buffer) < size+8:
                break
            frame = bytes(self.buffer[:size+8])
            del self.buffer[:size+8]
            if binascii.crc_hqx(frame[2:-2], 65535) == struct.unpack_from('<H', frame, len(frame)-2)[0]:
                rows.append((kind, frame[6:-2]))
        return rows


def decode(kind, payload):
    row = dict(kind=kind, hex=payload.hex())
    if kind == 6 and len(payload) in (48, 80):
        keys = ('cycles', 'cycleUs', 'maxCycleUs', 'overruns', 'busErrors', 'serialErrors',
                'droppedFrames', 'deadmanMs', 'servoBaud', 'periodUs', 'uptimeMs')
        row.update(zip(keys, struct.unpack_from('<11I', payload, 4)))
        row['state'] = ('monitor', 'enabled', 'stopping')[payload[0]]
        if len(payload) == 80:
            row['temperatureInterlock'] = ('none', 'unavailable', 'stale', 'over_temperature')[payload[1]]
            temperatures = []
            for offset in range(48, 80, 8):
                valid, value = payload[offset:offset+2]
                age = struct.unpack_from('<I', payload, offset+4)[0]
                temperatures.append(dict(temperatureC=value if valid else None,
                                         ageMs=None if age == 0xffffffff else age,
                                         fresh=bool(valid and age <= 250)))
            row['temperatures'] = temperatures
    if kind == 7 and len(payload) == 4:
        row['error'] = struct.unpack('<i', payload)[0]
    return row


def command(name, raw=None):
    if name == 'status':
        return envelope(5), (6, 7)
    if name in ('enable', 'disable'):
        return envelope(4, bytes([name == 'enable'])), (6, 7)
    if name == 'ping':
        return envelope(1, b'\x01\x01\x00\x00'), (2, 7)
    if name == 'stop':
        return envelope(1, b'\x01\x0f\x00\x00'), (6, 7)
    if name == 'state':
        return envelope(1, b'\x01\x21\x02\x00\x01\x01'), (3, 7)
    return envelope(1, bytes.fromhex(raw)), (2, 7, 8)


def transact(fd, name, raw, timeout):
    request, expected = command(name, raw)
    deadline = time.monotonic()+timeout
    at = 0
    while at < len(request):
        remaining = deadline-time.monotonic()
        if remaining <= 0 or not select.select([], [fd], [], remaining)[1]:
            raise TimeoutError('serial write timed out')
        try:
            at += os.write(fd, request[at:])
        except BlockingIOError:
            pass
    receiver = Parser()
    while time.monotonic() < deadline:
        if not select.select([fd], [], [], max(0, deadline-time.monotonic()))[0]:
            break
        data = os.read(fd, 4096)
        for kind, payload in receiver.feed(data):
            if kind in expected:
                return decode(kind, payload)
    raise TimeoutError('no matching firmware response')


def console(fd, timeout):
    names = ('ping', 'status', 'state', 'enable', 'disable', 'stop', 'raw')
    print('Commands: ping, status, state, enable, disable, stop, raw HEX, quit')
    try:
        while True:
            try:
                fields = shlex.split(input('puppybot> '))
            except EOFError:
                break
            if not fields:
                continue
            if fields == ['quit']:
                break
            if fields[0] not in names or (fields[0] == 'raw' and len(fields) < 2):
                print('Unknown command or missing raw frame')
                continue
            print(json.dumps(transact(fd, fields[0], ''.join(fields[1:]), timeout)))
    finally:
        row = transact(fd, 'disable', None, timeout)
        end = time.monotonic()+timeout
        while row.get('state') == 'stopping' and time.monotonic() < end:
            row = transact(fd, 'status', None, timeout)
        if row.get('state') != 'monitor':
            raise TimeoutError('firmware did not finish disabling outputs')
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True, help='explicit /dev/serial/by-id/... or PTY')
    parser.add_argument('--timeout', type=float, default=3)
    parser.add_argument('command', choices=('ping', 'status', 'state', 'enable', 'disable', 'stop', 'raw', 'console'))
    parser.add_argument('hex', nargs='?')
    args = parser.parse_args()
    if args.command == 'raw' and args.hex is None:
        parser.error('raw requires a hexadecimal v1 command frame')
    if args.timeout <= 0:
        parser.error('timeout must be positive')
    # Neither DTR nor RTS is toggled. Opening the console must not deliberately
    # reset the board; a board/driver with HUPCL may still reset on last close.
    fd = os.open(args.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    original = termios.tcgetattr(fd)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        mode = list(original)
        mode[0] = mode[1] = mode[3] = 0
        mode[2] = termios.CLOCAL | termios.CREAD | termios.CS8
        mode[4] = mode[5] = termios.B115200
        mode[6] = list(mode[6]); mode[6][termios.VMIN] = mode[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, mode)
        termios.tcflush(fd, termios.TCIFLUSH)
        if args.command == 'console':
            return console(fd, args.timeout)
        row = transact(fd, args.command, args.hex, args.timeout)
        print(json.dumps(row))
        return 1 if row['kind'] == 7 else 0
    finally:
        termios.tcsetattr(fd, termios.TCSANOW, original)
        os.close(fd)


if __name__ == '__main__':
    raise SystemExit(main())
