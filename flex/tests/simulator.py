#!/usr/bin/env python3
"""Independent process/PTY protocol tests for the source-launched simulator."""
import hashlib
import json
import os
from pathlib import Path
import re
import select
import shlex
import shutil
import signal
import struct
import subprocess
import tempfile
import time

from runtime import ROOT, Runtime, check, request, wait_for, wait_online
from dashboard import Dashboard
import runtime

BIN = ROOT/'build/flex/puppybot-simulator'
COMPILER = os.environ.get('FLEXSCRIPT_COMPILER') or shutil.which('flexscript') or str(ROOT.parent/'flexscript/build/flex')
ENV = {key: value for key, value in os.environ.items() if not key.startswith('PUPPYBOT_')}


class Simulator:
    def __init__(self, config=ROOT/'puppybot.json', source=False, options=()):
        args = [COMPILER, 'run', str(ROOT/'simulator.flex')] if source else [str(BIN)]
        if config is not None:
            args += ['--config', str(config)]
        args += list(options)
        self.process = subprocess.Popen(args, cwd=ROOT, env=ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        ready, _, _ = select.select([self.process.stdout], [], [], 5)
        if not ready:
            self.process.kill(); self.process.communicate()
            raise AssertionError('simulator startup timeout')
        line = self.process.stdout.readline()
        found = re.search(r'listening on (/dev/pts/\d+)', line)
        if not found:
            self.process.kill(); _, error = self.process.communicate()
            raise AssertionError(('simulator startup', line, error))
        self.path = found[1]

    def close(self):
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGTERM)
        _, error = self.process.communicate(timeout=5)
        check(self.process.returncode == 0, ('simulator graceful shutdown', error))


def packet(servo, instruction, params=b''):
    data = bytes([255, 255, servo, len(params)+2, instruction])+params
    return data+bytes([~sum(data[2:]) & 255])


class Serial:
    def __init__(self, path):
        self.fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        self.pending = b''

    def write(self, data):
        count = os.write(self.fd, data)
        check(count == len(data), 'test request completely written')

    def read(self, timeout=1):
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            if len(self.pending) >= 4:
                size = self.pending[3]+4
                if len(self.pending) >= size:
                    out, self.pending = self.pending[:size], self.pending[size:]
                    check(out[:2] == b'\xff\xff' and out[-1] == ~sum(out[2:-1]) & 255, 'independent STServo reply checksum')
                    return out
            ready, _, _ = select.select([self.fd], [], [], max(0, deadline-time.monotonic()))
            if ready:
                self.pending += os.read(self.fd, 4096)
        raise TimeoutError('simulator status timeout')

    def close(self):
        os.close(self.fd)


def raw_protocol():
    sim = Simulator(source=True, config=None)
    serial = Serial(sim.path)
    try:
        check(Path(sim.path).stat().st_uid == os.getuid(), 'PTY owned by current user without uucp permissions')
        check(Path(os.readlink(f'/proc/{sim.process.pid}/exe').removesuffix(' (deleted)')) == BIN, 'source launcher execs native simulator')
        serial.write(packet(1, 1)); check(serial.read() == packet(1, 0), 'servo ping ACK')
        read = packet(1, 2, bytes([56, 8]))
        serial.write(read[:2]); time.sleep(.005); serial.write(read[2:5]); time.sleep(.005); serial.write(read[5:])
        feedback = serial.read(); expected = json.loads((ROOT/'puppybot.json').read_text())['arm']['joints'][0]['reference_tick']
        check(struct.unpack('<H', feedback[5:7])[0] == expected, 'root calibration encoder initialization')
        check(feedback[11:13] == bytes([120, 25]), 'voltage/temperature register layout')
        serial.write(packet(1, 2, bytes([63, 1]))); check(serial.read()[5:-1] == bytes([25]), 'single temperature register read')
        serial.write(packet(1, 3, bytes([33, 1]))+packet(1, 2, bytes([33, 1])))
        check(serial.read() == packet(1, 0), 'wheel-mode ACK')
        check(serial.read()[5:-1] == b'\1', 'coalesced mode read')
        serial.write(b'garbage'+bytes(read[:-1])+bytes([read[-1]^1])+read)
        check(len(serial.read()) == 14, 'bad checksum and garbage resynchronize without replies')
        serial.write(read[:4]); time.sleep(.08)
        serial.write(read[:3]); time.sleep(.005); serial.write(read[3:]); check(len(serial.read()) == 14, 'partial timeout permits a new fragmented frame')
        serial.close(); serial = Serial(sim.path)
        serial.write(packet(1, 1)); check(serial.read() == packet(1, 0), 'same simulator accepts a new controller connection')
        # Initial source VM limits were five seconds. The daemon must outlive them.
        time.sleep(5.2)
        check(sim.process.poll() is None, 'source simulator survives VM deadline')
        serial.write(packet(1, 1)); check(serial.read() == packet(1, 0), 'long-running native serial session')
    finally:
        serial.close(); sim.close()
    check(not Path(sim.path).exists(), 'PTY removed when simulator exits')


def connected_controller(directory):
    state_path = directory/'simulator-state.json'
    sim = Simulator(source=True, options=['--state', str(state_path)])
    controller = Runtime(ROOT/'puppybot.json', sim.path)
    try:
        initial = wait_online(controller.port)
        check(initial['mode'] == 'hardware' and initial['control']['state'] == 'monitor', 'separate runtime exercises guarded serial adapter')
        check(all(row['fresh'] and row['temperatureC'] == 25 for row in initial['control']['temperatures']), 'simulated sensors satisfy real feedback checks')
        ui = Dashboard(controller.port)
        check(ui.action('jog', 11, lease=10)[0] == 409, 'simulator controller requires explicit enable')
        check(ui.action('enable')[0] == 200, 'dashboard enables normal runtime on virtual bus')
        original_tick = initial['arm']['joints'][0]['tick']
        check(ui.action('jog', 11, lease=11)[0] == 200, 'dashboard jog crosses process/serial boundary')
        for _ in range(6):
            time.sleep(.12)
            check(ui.action('renew', 11, lease=11)[0] == 200, 'held dashboard jog renews through PTY')
        wait_for(lambda: request(controller.port, '/api/state')[1]['arm']['joints'][0]['tick'] != original_tick, 'simulated encoder did not advance')
        wait_for(lambda: state_path.exists() and json.loads(state_path.read_text())['joints'][0]['velocity'] > 0, 'independent simulator state never moved')
        check(ui.action('release', 11, lease=11)[0] == 200, 'dashboard release')
        wait_for(lambda: json.loads(state_path.read_text())['joints'][0]['command'] == 0, 'stop command did not reach simulator')
        wait_for(lambda: json.loads(state_path.read_text())['joints'][0]['velocity'] == 0, 'simulated acceleration model never settled')
        check(ui.action('renew', 11, lease=11)[0] == 409, 'released hold stays revoked')
        check(ui.action('jog', 11, lease=12)[0] == 200, 'abandoned hold starts')
        wait_for(lambda: json.loads(state_path.read_text())['joints'][0]['command'] > 0, 'abandoned hold never reached serial bus')
        wait_for(lambda: json.loads(state_path.read_text())['joints'][0]['command'] == 0, 'abandoned hold never expired')
        controller.close(); controller = Runtime(ROOT/'puppybot.json', sim.path)
        check(wait_online(controller.port)['control']['state'] == 'monitor', 'controller restart uses same live bus and requires enable again')
        sim.close()
        wait_for(lambda: not all(joint['online'] for joint in request(controller.port, '/api/state')[1]['arm']['joints']), 'simulator exit did not invalidate feedback')
        check(request(controller.port, '/api/arm/joints/0/spin', {'direction': 1})[0] == 409, 'simulator disconnect cannot enable motion')
    finally:
        controller.close()
        if sim.process.poll() is None:
            sim.close()


def faults(directory):
    hot = Simulator(options=['--temperature', '81'])
    controller = Runtime(ROOT/'puppybot.json', hot.path)
    try:
        state = wait_online(controller.port)
        check(state['control']['temperatures'][0]['temperatureC'] == 81, 'synthetic hot feedback')
        check(request(controller.port, '/api/control/enable', {})[0] == 409, 'hot virtual servo blocks real controller enable')
        check(request(controller.port, '/api/state')[1]['control']['temperatureInterlock'] == 'over_temperature', 'temperature interlock provenance')
    finally:
        controller.close(); hot.close()
    jam = Simulator(options=['--jam', '0'])
    controller = Runtime(ROOT/'puppybot.json', jam.path)
    try:
        state = wait_online(controller.port)
        tick = state['arm']['joints'][0]['tick']
        ui = Dashboard(controller.port); check(ui.action('enable')[0] == 200, 'jammed feedback permits explicit enable')
        check(ui.action('jog', 11, lease=20)[0] == 200, 'jam case command')
        deadline = time.monotonic()+3
        fault = None
        while time.monotonic() < deadline and fault != 'stall':
            time.sleep(.1)
            # Even a duplicate start for the same hold must preserve its timer.
            ui.action('jog' if int(time.monotonic()*10) % 2 else 'renew', 11, lease=20)
            row = request(controller.port, '/api/state')[1]['arm']['joints'][0]
            check(row['tick'] == tick, 'jam holds independent encoder constant')
            fault = row['fault']
        check(fault == 'stall', 'real controller detects simulated jam')
        check(ui.action('renew', 11, lease=20)[0] == 409, 'held button cannot revive a stalled joint')
        check(request(controller.port, '/api/state')[1]['arm']['joints'][0]['fault'] == 'stall', 'stall fault remains latched after renewal rejection')
        ui.action('stop')
    finally:
        controller.close(); jam.close()


def boundaries(directory):
    for options in [['--jam', '4'], ['--temperature', '256'], ['--ticks', '0'], ['--config', str(directory/'missing.json')]]:
        result = subprocess.run([str(BIN), *options], cwd=ROOT, env=ENV, capture_output=True, timeout=3)
        check(result.returncode == 2, 'invalid simulator configuration rejected')
    alias = directory/'calibration-alias.json'
    alias.symlink_to(ROOT/'puppybot.json')
    result = subprocess.run([str(BIN), '--state', str(alias)], cwd=ROOT, env=ENV, capture_output=True, text=True, timeout=3)
    check(result.returncode == 2 and 'must not overwrite' in result.stderr, 'state output cannot overwrite calibration even through an alias')
    before = hashlib.sha256(BIN.read_bytes()).digest()
    result = subprocess.run([COMPILER, 'run', str(ROOT/'simulator.flex')], cwd=ROOT,
                            env=dict(ENV, FLEXSCRIPT_COMPILER='/usr/bin/false'), capture_output=True, text=True, timeout=5)
    check(result.returncode == 1 and 'native compilation failed' in result.stderr, 'simulator source never starts stale executable on build failure')
    check(hashlib.sha256(BIN.read_bytes()).digest() == before, 'failed simulator build preserves artifact')
    config_path = directory/"calibration with ' quote.json"
    config_path.write_bytes((ROOT/'puppybot.json').read_bytes())
    result = subprocess.run([str(BIN), '--config', str(config_path), '--ticks', '1'], cwd=ROOT, env=ENV, capture_output=True, text=True, timeout=3)
    check(result.returncode == 0, 'finite simulator session exits cleanly')
    command = next(line.strip() for line in result.stdout.splitlines() if line.startswith('  flexscript'))
    check(shlex.split(command)[-1] == str(config_path), 'printed connection command safely quotes configuration path')


def main():
    with tempfile.TemporaryDirectory(prefix='puppybot-simulator-') as temporary:
        directory = Path(temporary)
        raw_protocol()
        connected_controller(directory)
        faults(directory)
        boundaries(directory)
    print(f'Standalone simulator: {runtime.CHECKS} source/process/PTY/controller checks passed')


if __name__ == '__main__':
    main()
