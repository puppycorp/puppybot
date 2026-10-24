#!/usr/bin/env python3
"""Device-free wire oracle plus actual linked Xtensa firmware in Espressif QEMU."""
import argparse
import binascii
import importlib.util
import json
import os
from pathlib import Path
import select
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'build/flex/esp32'
spec = importlib.util.spec_from_file_location('esp32_command', ROOT/'flex/scripts/esp32-command.py')
wire = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wire)


def serial_oracle(compiler):
    binary = OUT/'serial-probe'
    subprocess.run([str(compiler), str(ROOT/'flex/tests/esp32-serial.flex'), '-o', str(binary)], check=True)
    stream, expected = [], []
    now = 0

    def feed(data):
        stream.extend(struct.pack('<QQ', now, byte) for byte in data)

    for size in range(257):
        frame = wire.envelope(size % 255, bytes((index*73+size) % 256 for index in range(size)))
        feed(b'boot noise\x00PP')
        feed(frame)
        expected.append((1, frame))
        now += 1
    frame = wire.envelope(1, b'\x01\x01\0\0')
    feed(frame[:-1]+bytes([frame[-1] ^ 1])); expected.append((-74, b''))
    feed(b'PB\x02'); expected.append((-71, b''))
    feed(b'PB\x01\x01\x01\x01'); expected.append((-90, b''))
    feed(frame[:7]); now += 101; feed(frame[7:]); feed(frame); expected.append((1, frame))
    result = subprocess.run([str(binary)], input=b''.join(stream), capture_output=True, check=True)
    actual, offset = [], 0
    while offset < len(result.stdout):
        code, size = struct.unpack_from('<qQ', result.stdout, offset)
        offset += 16
        actual.append((code, result.stdout[offset:offset+size])); offset += size
    assert actual == expected, (len(actual), len(expected))
    assert binascii.crc_hqx(b'123456789', 65535) == 0x29b1
    return len(expected)


def uart_checks(compiler):
    binary = OUT/'uart-probe'
    subprocess.run([str(compiler), str(ROOT/'flex/tests/esp32-uart.flex'), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)


def temperature_checks(compiler):
    subprocess.run([sys.executable, str(ROOT/'flex/scripts/prepare-esp32.py')], check=True)
    binary = OUT/'temperature-probe'
    for mode in ('hardware', 'reference'):
        subprocess.run([str(compiler), '--lowering-mode', mode,
                        str(ROOT/'flex/tests/esp32-temperature.flex'), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


def host_tool_checks():
    master, slave = os.openpty()
    process = subprocess.Popen([sys.executable, str(ROOT/'flex/scripts/esp32-command.py'),
                                '--port', os.ttyname(slave), 'console'],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    received, errors = [], []

    def peer():
        parser, enabled = wire.Parser(), 0
        try:
            while process.poll() is None:
                if not select.select([master], [], [], .1)[0]:
                    continue
                for kind, payload in parser.feed(os.read(master, 4096)):
                    received.append((kind, payload))
                    if kind == 1 and payload[1] == 1:
                        response = wire.envelope(2, b'\x01\x00\x01')
                    elif kind == 1 and payload[1] == 13:
                        response = wire.envelope(8, b'\x0d\x02')
                    else:
                        if kind == 4:
                            enabled = payload[0]
                        status = bytearray(48); status[0] = enabled
                        response = wire.envelope(6, status)
                    for offset in range(0, len(response), 3):
                        os.write(master, response[offset:offset+3])
        except Exception as error:
            errors.append(error)

    worker = threading.Thread(target=peer)
    worker.start()
    try:
        output, error = process.communicate(b'ping\nenable\nraw 010d04000001c800\nstop\nquit\n', timeout=10)
        assert process.returncode == 0, error.decode()
        assert b'"kind": 8' in output and b'"state": "enabled"' in output, output
        assert received[-1] == (4, b'\0'), received
    finally:
        if process.poll() is None:
            process.terminate(); process.communicate(timeout=5)
        worker.join(timeout=2)
        os.close(master); os.close(slave)
    assert not errors, errors


class Board:
    def __init__(self, qemu, directory):
        self.root = Path(directory)
        self.flash = self.root/'flash.bin'
        data = bytearray(b'\xff'*4194304)
        image = (OUT/'puppybot.bin').read_bytes()
        data[4096:4096+len(image)] = image
        self.flash.write_bytes(data)
        self.flash_hash = bytes(data)
        self.uart_path = str(self.root/'servo.sock')
        command = [str(qemu), '-M', 'esp32', '-display', 'none', '-monitor', 'none',
                   '-serial', 'stdio', '-serial', 'null', '-chardev',
                   f'socket,id=servo,path={self.uart_path},server=on,wait=off', '-serial', 'chardev:servo',
                   '-drive', f'file={self.flash},if=mtd,format=raw', '-nic', 'none', '-no-reboot']
        self.error_file = (self.root/'stderr.log').open('wb')
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.error_file)
        self.servo = socket.socket(socket.AF_UNIX)
        deadline = time.monotonic()+5
        while True:
            try:
                self.servo.connect(self.uart_path)
                break
            except (FileNotFoundError, ConnectionRefusedError):
                if time.monotonic() >= deadline or self.process.poll() is not None:
                    self.process.terminate(); self.process.communicate(timeout=5)
                    self.error_file.close(); self.servo.close()
                    raise AssertionError('QEMU UART did not start')
                time.sleep(.02)
            except OSError:
                self.process.terminate(); self.process.communicate(timeout=5)
                self.error_file.close(); self.servo.close()
                raise
        self.servo.setblocking(False)
        self.parser = wire.Parser()
        self.rx = bytearray()
        self.uart = bytearray()
        self.rows = []
        self.packets = []
        self.positions = [3538, 518, 2553, 2791]
        self.temperatures = [25]*4
        self.speeds = [0]*4
        self.reply = True
        self.corrupt = False
        self.wrong_id = False

    def pump(self, duration=.02):
        end = time.monotonic()+duration
        while time.monotonic() < end:
            assert self.process.poll() is None, 'firmware emulator exited'
            ready, _, _ = select.select([self.process.stdout, self.servo], [], [], max(0, end-time.monotonic()))
            if self.process.stdout in ready:
                data = os.read(self.process.stdout.fileno(), 4096)
                self.uart.extend(data)
                self.rows.extend(self.parser.feed(data))
            if self.servo in ready:
                self.rx.extend(self.servo.recv(4096))
                while len(self.rx) >= 4:
                    assert self.rx[:2] == b'\xff\xff', self.rx
                    size = self.rx[3]+4
                    if len(self.rx) < size:
                        break
                    packet = bytes(self.rx[:size]); del self.rx[:size]
                    assert sum(packet[2:]) & 255 == 255, packet.hex()
                    self.packets.append(packet)
                    servo_id, instruction = packet[2], packet[4]
                    assert servo_id in (1, 2, 3, 4, 5)
                    payload = b''
                    if instruction == 2:
                        assert packet[5:7] == b'\x38\x08', packet.hex()
                        payload = struct.pack('<H', self.positions[servo_id-1])
                        temperature = self.temperatures[servo_id-1]
                        if temperature is not None:
                            payload += bytes([0, 0, 0, 0, 120, temperature])
                    elif instruction == 3 and packet[5] == 41:
                        speed = struct.unpack_from('<H', packet, 11)[0]
                        self.speeds[servo_id-1] = -(speed & 32767) if speed & 32768 else speed
                    if self.reply:
                        response_id = servo_id
                        if self.wrong_id:
                            response_id = servo_id % 4 + 1
                        body = bytes([response_id, len(payload)+2, 0])+payload
                        reply = b'\xff\xff'+body+bytes([(~sum(body)) & 255])
                        if self.corrupt:
                            reply = reply[:-1]+bytes([reply[-1] ^ 1])
                        self.servo.sendall(reply)

    def wait(self, predicate, timeout=5):
        end = time.monotonic()+timeout
        while not predicate():
            assert time.monotonic() < end, ('firmware timed out', self.uart[-300:], self.rows[-3:])
            self.pump()

    def request(self, kind, payload=b'', expected=(6, 7)):
        self.pump()
        self.rows.clear()
        self.process.stdin.write(wire.envelope(kind, payload)); self.process.stdin.flush()
        self.wait(lambda: any(k in expected for k, _ in self.rows))
        return next((k, p) for k, p in self.rows if k in expected)

    def status(self):
        kind, payload = self.request(5)
        assert kind == 6 and len(payload) == 80
        return wire.decode(kind, payload)

    def close(self):
        self.process.terminate()
        self.process.communicate(timeout=5)
        self.error_file.close()
        self.servo.close()
        (OUT/'qemu.uart').write_bytes(self.uart)
        assert self.flash.read_bytes() == self.flash_hash


def thermal_cases(board):
    jog = b'\x01\x0d\x04\0\0\x01\xc8\0'
    assert board.request(1, jog, (8, 7))[0] == 8
    board.wait(lambda: board.speeds[0] > 0)
    # The threshold is strictly above80C. A different hot joint also inhibits
    # the whole arm, so coordinated motion cannot continue through a fault.
    board.temperatures[2] = 80
    board.wait(lambda: board.status()['temperatures'][2]['temperatureC'] == 80)
    assert board.status()['state'] == 'enabled' and board.speeds[0] > 0
    board.temperatures[2] = 81
    board.wait(lambda: board.speeds[0] == 0)
    board.wait(lambda: board.status()['state'] == 'monitor')
    status = board.status()
    assert status['temperatureInterlock'] == 'over_temperature'
    assert status['temperatures'][2]['temperatureC'] == 81
    assert board.request(4, b'\1')[0] == 7
    board.temperatures[2] = 25
    board.wait(lambda: board.status()['temperatures'][2]['temperatureC'] == 25)
    assert board.status()['state'] == 'monitor'
    assert board.request(1, jog, (8, 7))[0] == 7, 'cooling resumed motion without enable'
    assert board.request(4, b'\1')[0] == 6
    assert board.status()['temperatureInterlock'] == 'none'
    assert board.request(1, jog, (8, 7))[0] == 8
    board.wait(lambda: board.speeds[0] > 0)
    # A plausible position-only status has no temperature; never treat its
    # missing bytes as zero degrees or retain a valid old sample.
    board.temperatures[1] = None
    board.wait(lambda: board.speeds[0] == 0)
    board.wait(lambda: board.status()['state'] == 'monitor')
    status = board.status()
    assert status['temperatureInterlock'] == 'unavailable'
    assert status['temperatures'][1]['temperatureC'] is None and not status['temperatures'][1]['fresh']
    assert board.request(4, b'\1')[0] == 7
    board.temperatures[1] = 25
    board.wait(lambda: board.status()['temperatures'][1]['fresh'])
    assert board.status()['state'] == 'monitor'
    assert board.request(4, b'\1')[0] == 6


def qemu_checks(qemu):
    with tempfile.TemporaryDirectory(prefix='puppybot-esp32-') as directory:
        board = Board(qemu, directory)
        try:
            board.wait(lambda: any(kind == 6 for kind, _ in board.rows))
            assert b'SPI_FAST_FLASH_BOOT' in board.uart and b'entry 0x4008' in board.uart
            board.wait(lambda: len(board.packets) >= 8)
            assert all(packet[4] == 2 for packet in board.packets), 'boot wrote to servo registers'
            status = board.status()
            assert status['state'] == 'monitor' and status['servoBaud'] == 1000000 and status['deadmanMs'] == 500
            assert all(row['temperatureC'] == 25 and row['fresh'] for row in status['temperatures'])
            kind, payload = board.request(1, b'\x01\x01\0\0', (2, 7))
            assert kind == 2 and payload == b'\x01\x00\x01'
            assert board.request(1, b'\x01\x0d\x04\0\0\x01\xc8\0')[0] == 7, 'motion accepted before enable'
            assert board.request(4, b'\x01')[0] == 6
            board.wait(lambda: any(packet[4] == 3 for packet in board.packets))
            assert board.status()['state'] == 'enabled'
            kind, telemetry = board.request(1, b'\x01\x21\x02\0\x01\x01', (3, 7))
            assert kind == 3 and telemetry[:4] == b'\x01\x00\x07\x04'
            profile = json.loads((ROOT/'puppybot.json').read_text())
            offset = 4
            for index, joint in enumerate(profile['arm']['joints']):
                assert telemetry[offset] == joint['servo_id']
                assert struct.unpack_from('<i', telemetry, offset+2)[0] == board.positions[index]
                assert struct.unpack_from('<ii', telemetry, offset+12) == (joint['tick_min'], joint['tick_max'])
                assert abs(struct.unpack_from('<f', telemetry, offset+20)[0]-90) < .001
                offset += 25+telemetry[offset+24]
            # V1 jog yaw + at200 ticks/s; the hardware peer never moves its
            # encoder, so command expiry must stop it before stall detection.
            jog_start = board.status()['uptimeMs']
            board.process.stdin.write(wire.envelope(1, b'\x01\x0d\x04\0\0\x01\xc8\0')); board.process.stdin.flush()
            board.wait(lambda: board.speeds[0] > 0)
            board.wait(lambda: board.speeds[0] == 0)
            # The existing telemetry exports joint faults, not arm-level
            # deadman reasons. Check the emitted zero speed against MCU time.
            assert 450 <= board.status()['uptimeMs']-jog_start <= 650
            jog = b'\x01\x0d\x04\0\0\x01\xc8\0'
            assert board.request(1, jog, (8, 7))[0] == 8
            board.wait(lambda: board.speeds[0] > 0)
            stop_start = board.status()['uptimeMs']
            assert board.request(1, b'\x01\x0f\0\0')[0] == 6
            board.wait(lambda: board.speeds[0] == 0)
            assert board.status()['uptimeMs']-stop_start < 150
            assert board.request(1, jog, (8, 7))[0] == 8
            board.wait(lambda: board.speeds[0] > 0)
            assert board.request(4, b'\0')[0] == 6
            board.wait(lambda: board.speeds[0] == 0)
            board.wait(lambda: board.status()['state'] == 'monitor')
            assert board.request(4, b'\1')[0] == 6
            # A fragmented host frame survives ordinary gaps; a truncated frame
            # expires and cannot hide the next complete command.
            ping = wire.envelope(1, b'\x01\x01\0\0')
            board.rows.clear()
            for chunk in (ping[:3], ping[3:7], ping[7:]):
                board.process.stdin.write(chunk); board.process.stdin.flush(); board.pump(.01)
            board.wait(lambda: any(kind == 2 for kind, _ in board.rows))
            board.process.stdin.write(ping[:7]); board.process.stdin.flush(); board.pump(.5)
            assert board.request(1, b'\x01\x01\0\0', (2, 7))[0] == 2
            bad = ping[:-1]+bytes([ping[-1] ^ 1])
            board.process.stdin.write(bad); board.process.stdin.flush()
            assert board.status()['serialErrors'] >= 1
            thermal_cases(board)
            # A wrong-ID status cannot extend the transaction's original50ms
            # deadline indefinitely. Missing/corrupt servos cannot block USB.
            board.wrong_id = True; board.pump(.2)
            board.wrong_id = False; board.corrupt = True; board.pump(.1)
            board.corrupt = False; board.reply = False; board.pump(.3)
            assert board.status()['busErrors'] > 0
            assert board.request(4, b'\x01')[0] == 7, 'enable accepted stale feedback'
            assert board.request(4, b'\x00')[0] == 6
            board.wait(lambda: board.status()['state'] == 'monitor')
            boundary = len(board.packets); board.pump(.2)
            assert all(packet[4] == 2 for packet in board.packets[boundary:]), 'disabled firmware wrote servo registers'
            report = dict(boot=True, actualXtensa=True, physicalHardware=False, flashUnchanged=True,
                          uartPackets=len(board.packets), status=board.status(),
                          checks=['ROM/XIP boot', 'physical calibration', 'read-only boot', 'ping/telemetry',
                                  'enable gate', 'motion command expiry', 'fragments/CRC/timeout',
                                  'combined temperature/position', '80/81C threshold', 'hot/missing temperature stops',
                                  'fresh cooling plus explicit enable', 'wrong ID/malformed/missing servo',
                                  'responsive USB', 'stop/disarm'])
            (OUT/'qemu-report.json').write_text(json.dumps(report, indent=2)+'\n')
            return report
        finally:
            board.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', type=Path, default=Path(os.environ.get('FLEXSCRIPT_COMPILER', ROOT.parent/'flexscript/build/flex')))
    parser.add_argument('--qemu', type=Path)
    args = parser.parse_args()
    count = serial_oracle(args.compiler)
    uart_checks(args.compiler)
    temperature_checks(args.compiler)
    host_tool_checks()
    print(f'ESP32 serial: {count} independent CRC/framing/bounds/timeout cases passed')
    print('ESP32 UART: pin routes, clock/baud, FIFO bounds, RX error/reset and interrupt preservation passed')
    print('ESP32 host tool: real PTY console, fragmented replies, commands and exit-disable passed')
    print('ESP32 temperature: combined reads, malformed/failed replies, 80/81C and 250/251ms bounds, stop/enable/recovery passed')
    if args.qemu:
        report = qemu_checks(args.qemu)
        print('ESP32 linked firmware ROM boot, real Xtensa controller/UART2, servo faults and serial control passed')
        print(json.dumps(report['status']))


if __name__ == '__main__':
    main()
