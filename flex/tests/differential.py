#!/usr/bin/env python3
"""Compare real Rust core behavior with the native Flexscript port."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import random
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[2]
MASK = (1 << 64) - 1


def word(value):
    if isinstance(value, float):
        return struct.unpack('<Q', struct.pack('<d', value))[0]
    return value & MASK


class Cases:
    def __init__(self):
        self.records = []

    def add(self, label, op, *args):
        self.records.append((label, op, [word(v) for v in args]))

    def snapshot(self, label):
        self.add(label, 9)
        self.add(label + " mode", 25)

    def command(self, label, now, cmd, *args):
        self.add(label, 1, now, cmd, *(list(args) + [0] * (5 - len(args))))
        self.snapshot(label + ' state')

    def reset(self, label, ticks=(2048, 530, 3565, 1783), now=0):
        self.add(label, 0, now)
        for i, tick in enumerate(ticks):
            self.add(label + f' feedback {i}', 2, now, i, tick)
        self.snapshot(label + ' initialized')

    def wire(self, label, now, cmd, body=b'', declared=None, suffix=b''):
        frame = bytes([1, cmd]) + struct.pack('<H', len(body) if declared is None else declared) + body + suffix
        self.add(label, 8, now, *frame)
        self.snapshot(label + ' state')

    def configure(self, label, joints, now=0):
        self.add(label, 11, now, *(v for j in joints for v in j))
        self.snapshot(label + ' config')


def cases():
    c = Cases()
    rng = random.Random(0x5055505059)
    # Independent numerical operations use the original Rust/libm implementations.
    for i in range(800):
        angles = [rng.uniform(-math.pi, math.pi) for _ in range(4)]
        c.add(f'FK {i}', 17, *angles)
        c.add(f'chain {i}', 26, *angles)
        c.add(f'tool backoff {i}', 27, rng.uniform(-300, 300), rng.uniform(-300, 300), rng.uniform(-100, 300), rng.uniform(-math.pi, math.pi))
        c.add(f'IK branches {i}', 16, rng.uniform(-350, 350), rng.uniform(-350, 350), rng.uniform(-100, 400), rng.uniform(-math.pi, math.pi))
    for x in [-1.0, -0.5, -0.0, 0.0, 0.5, 1.0]:
        c.add(f'FK boundary {x}', 17, x, x, x, x)
    for i in range(1500):
        raw = rng.getrandbits(32)
        c.add(f'f32 decode {raw:x}', 18, raw)
        raw = rng.getrandbits(64)
        c.add(f'f32 encode {raw:x}', 19, raw)
    for value in [0.0, -0.0, 1.0, -1.0, 2**-149, 2**-150, 2**-126, 3.4028234663852886e38, math.inf, -math.inf]:
        c.add(f'f32 boundary {value}', 19, float(value))
    config = [0]*56
    config[0] = 1
    serial = b'PB-DEV-0001'.ljust(32, b'\0')
    config[1:5] = struct.unpack('<4Q', serial)
    config[5:11] = [1, 2, 1, 90, 45, 500]
    config[16:23] = [1, 1, 1, 0, 1, 1, 1]
    for i, (lo, hi, ref, angle, sign) in enumerate([(0, 4095, 2048, 0.0, 1), (100, 1000, 530, math.pi/2, -1), (2200, 3600, 3565, 0.0, -1), (500, 3000, 1783, 0.0, 1)]):
        config[24+i*8:32+i*8] = [i+1, lo, hi, ref, angle, sign, 1, 1]
    c.add('default config validation', 24, *config)
    for slot, values in {0: [0, 2], 1: [0, 127, 255, 0x41420041], 5: [0, 2], 6: [0, 1],
                         7: [0, 255], 9: [0], 16: [0, 2], 17: [0], 18: [0], 19: [math.inf, math.nan],
                         20: [0], 21: [0], 22: [0], 24: [0, 254], 25: [-1, 4095, 4096],
                         26: [-1, 0, 4096], 28: [math.nan, math.inf], 29: [0, 2], 30: [0, 2], 32: [1]}.items():
        for value in values:
            changed = config.copy(); changed[slot] = value
            c.add(f'invalid config slot {slot}/{value}', 24, *changed)
    empty = config.copy(); empty[1:5] = [0]*4; c.add('empty config serial', 24, *empty)
    c.reset('defaults')
    for command, args in [(1, [300]), (2, [0, 1]), (3, [0]), (4, []), (5, [2100, 600, 3500, 1800]),
                          (6, [0.1, 1.3, 0.2, -0.1]), (7, [100.0, 100.0, 100.0, -math.pi/2]),
                          (8, [0, 1.0, 0.0, 0.0]), (9, [0, 1.0, 0.0, 0.0]),
                          (10, [1, 1.0, 0.0, 0.0, 20.0]), (11, []), (12, []), (13, [1, 600]),
                          (14, [1, 0.9]), (15, [1, 530, math.pi/2]), (16, [2, 1.2, 300]),
                          (17, [0, 3500, 300]), (18, [0, False]), (19, [-1]), (20, [11, 12, 13, 14])]:
        c.reset(f'command {command}')
        c.command(f'command {command}', 10, command, *args)
        c.add(f'command {command} update', 3, 20)
        c.snapshot(f'command {command} updated')
    # Invalid commands must retain the original failure and mutation semantics.
    for command, args in [(2, [4, 1]), (3, [255]), (13, [9, 100]), (14, [4, 1.0]),
                          (15, [0, -1, 0.0]), (15, [0, 4096, 0.0]), (15, [0, 2000, math.inf]),
                          (17, [0, 100, 100]), (20, [0, 2, 3, 4]), (20, [254, 2, 3, 4]),
                          (9, [0, 0.0, 0.0, 0.0]), (9, [0, math.inf, 0.0, 0.0]),
                          (10, [0, 1.0, 0.0, 0.0, -1.0]), (10, [0, 1.0, 0.0, 0.0, math.nan]),
                          (19, [4]), (7, [900.0, 0.0, 0.0, -math.pi/2])]:
        c.reset('invalid')
        c.command(f'invalid {command} {args}', 10, command, *args)
    c.add('without feedback', 0, 0)
    for cmd in [8, 9, 12, 13, 14, 16]:
        args = {8: [0, 1.0, 0.0, 0.0], 9: [0, 1.0, 0.0, 0.0], 12: [], 13: [1, 600], 14: [1, 1.0], 16: [2, 1.0, 300]}[cmd]
        c.command(f'missing feedback {cmd}', 10, cmd, *args)
    # Original packet construction, including all byte values and max payload.
    for i in range(100):
        n = rng.randrange(245)
        c.add(f'servo packet {i}', 15, rng.randrange(256), rng.randrange(256), *(rng.randrange(256) for _ in range(n)))
    bodies = {
        1: b'', 2: bytes([1, 0, 216]), 3: b'\x02', 4: b'', 9: bytes([2, 1, 4]),
        12: struct.pack('<H', 300), 13: struct.pack('<BbH', 1, -1, 300), 14: b'\x01', 15: b'',
        16: struct.pack('<Hiiii', 300, 2048, 530, 3565, 1783),
        17: struct.pack('<Hffff', 300, 0, 90, 0, 0), 18: struct.pack('<Hffff', 300, 100, 100, 100, -90),
        19: struct.pack('<H', 300), 20: struct.pack('<BHi', 1, 300, 600), 21: struct.pack('<Bii', 0, 3500, 300),
        22: bytes([0, 0]), 23: struct.pack('<HBfff', 300, 0, 1, 2, 3), 24: b'\xff', 25: b'',
        26: bytes([1, 5, 11, 12, 13, 14]), 27: struct.pack('<bb', 60, -50), 28: b'',
        29: struct.pack('<BhH', 1, 90, 300), 30: struct.pack('<ffffH', 100, 100, 100, -90, 300),
        31: b'', 32: struct.pack('<BHH', 2, 90, 1000), 33: bytes([1, 1]),
        34: struct.pack('<Bffff', 0, 1, 0, 0, 20), 35: b'',
    }
    for cmd in range(256):
        c.reset(f'wire {cmd}')
        body = bodies.get(cmd, b'')
        c.wire(f'wire {cmd}', 10, cmd, body)
        c.add(f'wire {cmd} update', 3, 20)
        c.snapshot(f'wire {cmd} updated')
        for size in range(len(body)):
            c.wire(f'truncated command {cmd}/{size}', 10, cmd, body[:size])
        c.wire(f'declared overflow {cmd}', 10, cmd, body, declared=len(body)+1)
        c.wire(f'trailing ignored {cmd}', 10, cmd, body, suffix=b'extra')
    for body in [bytes([1, 5, 254, 2, 3, 4]), bytes([1, 5, 0, 2, 3, 4]), bytes([2, 5, 1, 2, 3, 4])]:
        c.wire('invalid protocol config', 10, 26, body)
    for raw in [0x7f800000, 0xff800000, 0x7fc01234, 0xffc01234, 0x7f801234]:
        for cmd in [18, 23, 30, 34]:
            base = bytearray(bodies[cmd])
            offsets = {17: [2, 6, 10, 14], 18: [2, 6, 10, 14], 23: [3, 7, 11], 30: [0, 4, 8, 12], 34: [1, 5, 9, 13]}[cmd]
            for offset in offsets:
                body = base.copy(); body[offset:offset+4] = struct.pack('<I', raw)
                c.reset('nonfinite wire')
                c.wire(f'nonfinite wire {cmd}/{offset}/{raw:x}', 10, cmd, body)
    for i in range(100):
        c.add(f'truncated envelope {i}', 8, 10, *(rng.randrange(256) for _ in range(i % 4)))
    # Random drive inputs exercise signed bytes, percent clamps, and the 500 ms watchdog.
    for i in range(200):
        c.reset('drive')
        c.wire(f'drive {i}', 10, 27, bytes([rng.randrange(256), rng.randrange(256)]))
        for now in [0, 509, 510, 1000]:
            c.add(f'drive timeout {i}/{now}', 10, now)
            c.snapshot(f'drive timeout state {i}/{now}')
    # Wrapped ranges, target following and servo acknowledgement history.
    for trial in range(80):
        c.reset(f'tracking {trial}')
        for j in range(4):
            lo, hi = rng.sample(range(4096), 2)
            c.command(f'limits {trial}/{j}', 0, 17, j, lo, hi)
        c.command('speed', 0, 1, rng.randrange(1, 2000))
        c.command('targets', 0, 5, *(rng.randrange(-4096, 8192) for _ in range(4)))
        ticks = [2048, 530, 3565, 1783]
        for step in range(12):
            now = step*20
            for j in range(4):
                ticks[j] = (ticks[j] + rng.randrange(-40, 41)) % 4096
                c.add('feedback', 2, now, j, ticks[j])
            c.add(f'tracking update {trial}/{step}', 3, now)
            c.snapshot(f'tracking state {trial}/{step}')
            for j in range(4):
                c.add('speed acknowledgement', 6, now, j, j+1, rng.randrange(-500, 501), rng.randrange(2))
    # Explicit safety cases exercise boundaries at/before/after each timeout.
    for action in ['feedback-loss', 'stale', 'overtemp', 'stall-target', 'stall-jog', 'deadman', 'disabled-limits']:
        c.reset(action)
        c.command(action+' speed', 0, 1, 300)
        if action in ['stall-target', 'feedback-loss', 'stale', 'overtemp']:
            c.command(action+' target', 0, 5, 2400, 800, 3000, 2000)
        else:
            c.command(action+' jog', 0, 2, 0, 1)
        if action == 'feedback-loss':
            c.add(action, 4, 0)
        if action == 'overtemp':
            c.add(action, 5, 0, 1, 81)
        if action == 'disabled-limits':
            c.command(action, 0, 18, 0, 0)
        for now in [0, 20, 199, 200, 201, 250, 251, 349, 350, 351, 499, 500, 501, 999, 1000, 1001, 1249, 1250, 1251]:
            if action != 'stale':
                for j in range(4):
                    if action != 'feedback-loss' or j:
                        c.add(action+' refresh', 2, now, j, [2048, 530, 3565, 1783][j])
            c.add(action+f' update {now}', 3, now)
            c.snapshot(action+f' state {now}')
        c.command(action+' clear selected', 1300, 19, 0)
        c.command(action+' clear all', 1300, 19, -1)
    # Broad calibrated profiles make Cartesian paths reachable in all frames.
    profile = [[i+1, 0, 4095, 2048, 0.0, 1, 1, 0] for i in range(4)]
    for frame in [0, 1, 2]:
        for direction in [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (-1.0, 0.0, 0.0)]:
            c.configure('Cartesian', profile)
            for j, tick in enumerate([2048, 2800, 2400, 3000]):
                c.add('Cartesian feedback', 2, 0, j, tick)
            c.command('relative Cartesian', 0, 8, frame, *[v*2 for v in direction])
            c.command('Cartesian stop', 0, 4)
            c.command('start Cartesian jog', 0, 10, frame, *direction, 50.0)
            for step in range(1, 16):
                for j, tick in enumerate([2048, 2800, 2400, 3000]):
                    c.add('jog feedback', 2, step*20, j, tick)
                c.add(f'jog update {frame}/{direction}/{step}', 3, step*20)
                c.snapshot(f'jog state {frame}/{direction}/{step}')
            c.command('stop Cartesian jog', 320, 11)
    c.reset('wheel recovery')
    for now in [0, 999, 1000, 1999, 2000]:
        for index in range(4):
            c.add('begin wheel', 12, now, index, index+1, 0)
            c.add('wheel mode failure', 7, index, index+1, 1, 0)
            c.add('wheel ready', 13, index, index+1)
            c.add('wheel mode success', 7, index, index+1, 1, 1)
            c.add('wheel ready after', 13, index, index+1)
    c.add('initial wheel setup', 14)
    c.add('initial wheel setup once', 14)
    for trial in range(20):
        c.add('fake cycle reset', 0, 0)
        for j, tick in enumerate([2048, 530, 3565, 1783, 1500]):
            c.add('fake servo setup', 20, j+1, tick)
        c.add('separate steering', 23, 104, 5, 0, 0, 0, 0)
        for step in range(40):
            now = step*20
            if step == 4:
                c.add('queue wheel jog', 23, 1, 350, 0, 0, 0, 0)
                c.add('queue wheel jog', 23, 2, 0, 1, 0, 0, 0)
                c.add('queue drive', 23, 101, 45, -50, 0, 0, 0)
            if step == 15:
                c.add('queue target', 23, 5, 2400, 700, 3400, 2100, 0)
            if step == 32:
                c.add('queue stop', 23, 4, 0, 0, 0, 0, 0)
                c.add('queue drive stop', 23, 103, 0, 0, 0, 0, 0)
            if trial % 4 == 0 and step in [8, 20]:
                c.add('fake read failure toggle', 21, 1, 4, step == 8)
            if trial % 4 == 1 and step in [8, 20]:
                c.add('fake write failure toggle', 21, 2, 5, step == 8)
            if trial % 4 == 2 and step in [0, 20]:
                c.add('fake initial mode failure toggle', 21, 3, 5, step == 0)
            if step:
                for j, tick in enumerate([2048, 530, 3565, 1783]):
                    c.add('fake moving feedback', 21, j+1, 2, (tick + step*(j+1)) % 4096)
            c.add(f'fake serialized cycle {trial}/{step}', 22, now)
            c.snapshot(f'fake serialized state {trial}/{step}')
    c.add('bounded intent queue', 0, 0)
    for i in range(18):
        c.add(f'queue capacity {i}', 23, 1, i, 0, 0, 0, 0)
    return c.records


def decode(data):
    words = struct.unpack('<' + 'Q'*(len(data)//8), data)
    records = []
    at = 0
    while at < len(words):
        n = words[at]
        if at + 1 + n > len(words):
            raise AssertionError('truncated output record')
        records.append(words[at+1:at+1+n])
        at += n+1
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', default=os.environ.get('FLEXSCRIPT_COMPILER', str(ROOT.parent/'flexscript/build/flex')))
    parser.add_argument('--no-build', action='store_true')
    parser.add_argument('--lowering-mode', choices=['hardware', 'reference'], default='hardware')
    args = parser.parse_args()
    manifest = json.loads((ROOT/'flex/vendor/manifest.json').read_text())
    for original, expected_hash in manifest['files'].items():
        snapshot = ROOT/'flex/vendor'/Path(original).name
        if hashlib.sha256(snapshot.read_bytes()).hexdigest() != expected_hash:
            raise AssertionError(f'vendor snapshot changed without updating its manifest: {snapshot}')
    work = ROOT/'build/flex'
    work.mkdir(parents=True, exist_ok=True)
    probe = work/('probe-' + args.lowering_mode)
    oracle = work/'oracle/debug/puppybot-flex-oracle'
    if not args.no_build:
        subprocess.run([args.compiler, '--lowering-mode', args.lowering_mode, str(ROOT/'flex/tests/probe.flex'), '-o', str(probe)], check=True)
        subprocess.run(['cargo', 'build', '--locked', '--offline', '--manifest-path', str(ROOT/'flex/tests/oracle/Cargo.toml'), '--target-dir', str(work/'oracle')], check=True)
    records = cases()
    payload = b''.join(struct.pack('<'+'Q'*(len(a)+2), op, len(a), *a) for _, op, a in records)
    expected = subprocess.run([str(oracle)], input=payload, capture_output=True, check=True, timeout=120)
    actual = subprocess.run([str(probe)], input=payload, capture_output=True, check=True, timeout=120)
    lhs, rhs = decode(expected.stdout), decode(actual.stdout)
    if len(lhs) != len(records) or len(rhs) != len(records):
        raise AssertionError(f'expected {len(records)} records; received Rust {len(lhs)}, Flexscript {len(rhs)}')
    failures = []
    for i, ((label, op, _), rust, flex) in enumerate(zip(records, lhs, rhs)):
        if rust != flex:
            diffs = [(j, hex(x), hex(y)) for j, (x, y) in enumerate(zip(rust, flex)) if x != y]
            failures.append({'record': i, 'label': label, 'operation': op, 'lengths': [len(rust), len(flex)], 'differences': diffs[:8]})
    report = {'loweringMode': args.lowering_mode, 'records': len(records), 'comparedWords': sum(map(len, lhs)), 'failures': len(failures), 'firstFailures': failures[:15],
              'rustOutputSha256': hashlib.sha256(expected.stdout).hexdigest(), 'flexOutputSha256': hashlib.sha256(actual.stdout).hexdigest()}
    report['sourceSha256'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in sorted((ROOT/'puppybot/core/src').rglob('*.rs'))}
    report['compilerSha256'] = hashlib.sha256(Path(args.compiler).read_bytes()).hexdigest()
    (work/('differential-' + args.lowering_mode + '.json')).write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'sourceSha256'}, indent=2))
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
