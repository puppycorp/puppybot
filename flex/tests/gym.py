#!/usr/bin/env python3
"""Independent process-boundary, seeded-plant, artifact and Gym lifecycle checks."""
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import select
import signal
import subprocess
import tempfile
import time
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[2]
GYM = ROOT/'build/flex/puppybotgym'
FIRMWARE = ROOT/'build/flex/puppybot-firmware-sim'
CLI = ROOT/'build/flex/puppybot'
CHECKS = 0


def check(condition, message):
    global CHECKS
    if not condition:
        raise AssertionError(message)
    CHECKS += 1


def run(args, code=0):
    result = subprocess.run([str(GYM), *map(str, args)], cwd=ROOT, capture_output=True, timeout=10)
    check(result.returncode == code, (args, result.returncode, result.stdout, result.stderr))
    return result


def read(path):
    return json.loads(path.read_bytes())


def wait_file(path, predicate=lambda value: True):
    deadline = time.monotonic()+7
    while time.monotonic() < deadline:
        if path.exists():
            value = read(path)
            if predicate(value):
                return value
        time.sleep(.01)
    raise AssertionError(('artifact timeout', path))


def audit(directory):
    result = read(directory/'result.json')
    observations = [json.loads(line) for line in (directory/'observations.jsonl').read_bytes().splitlines()]
    commands = [json.loads(line) for line in (directory/'commands.jsonl').read_bytes().splitlines()]
    packets = [json.loads(line) for line in (directory/'serial.jsonl').read_bytes().splitlines()]
    check(len(observations) == result['step']+1, 'one actual telemetry observation per step')
    check(all(o['timeMs'] == i*20 and o['step'] == i for i, o in enumerate(observations)), 'deterministic time progression')
    check(result['serialPackets'] == len(packets), 'serial journal packet count')
    check(not result['articulatedPhysics'] and result['backend'] == 'servo-plant-v1', 'backend provenance is explicit')
    check(hashlib.sha256((directory/'firmware.elf').read_bytes()).digest() == hashlib.sha256(FIRMWARE.read_bytes()).digest(), 'exact executing firmware snapshot')
    check(hashlib.sha256((directory/'gym.elf').read_bytes()).digest() == hashlib.sha256(GYM.read_bytes()).digest(), 'exact executing case/policy snapshot')
    manifest = read(directory/'manifest.json')
    check(manifest['targets'] == result['targets'] and manifest['caseVersion'] == 1 and manifest['warmupSteps'] == 64, 'versioned case inputs retained')
    modes = set()
    speeds = {i: 0 for i in range(1, 5)}
    for packet in packets:
        tx = bytes.fromhex(packet['tx'])
        check(tx[:2] == b'\xff\xff' and tx[3]+4 == len(tx) and tx[-1] == (~sum(tx[2:-1]) & 255), 'wire packet length/checksum')
        rx = bytes.fromhex(packet['rx']) if packet['rx'] else b''
        if rx:
            check(rx[2] == tx[2] and rx[-1] == (~sum(rx[2:-1]) & 255), 'actual matching status reply')
        servo, instruction = tx[2], tx[4]
        if instruction == 3 and tx[5] == 33 and rx:
            modes.add(servo)
        if instruction == 3 and tx[5] == 41:
            check(servo in modes, 'speed writes follow acknowledged wheel mode')
            value = int.from_bytes(tx[11:13], 'little')
            speeds[servo] = -(value & 32767) if value & 32768 else value
    check(all(v == 0 for v in speeds.values()), 'shutdown acknowledged zero-speed output')
    for observation in observations:
        telemetry = bytes.fromhex(observation['telemetry'])
        check(telemetry[:4] == b'\1\0\7\4', 'production protocol v1 telemetry')
    check(len(commands) == 1 and bytes.fromhex(commands[0]['frame'])[:2] == b'\1\20', 'case uses normal goto-ticks wire command')
    if result['case'] == 'arm-reach' and result['passed']:
        for sample in observations[-25:]:
            check(all(abs(j['tick']-target) <= 8 and j['velocity'] == 0 and j['command'] == 0
                      for j, target in zip(sample['plant'], result['targets'])), 'independent settled-target acceptance')
    return result


def cli_cases(directory):
    native = {c['id'] for c in read(ROOT/'flex/sim/cases/catalog.json')['cases']}
    check({c['id'] for c in json.loads(run(['cases']).stdout)} == {'arm-reach', 'joint-stall'} | native, 'servo and native case catalog')
    a, b, c = [directory/name for name in ('seed42-a', 'seed42-b', 'seed43')]
    for path, seed in [(a, 42), (b, 42), (c, 43)]:
        run(['run', '--output', path, '--seed', seed])
        check(audit(path)['passed'], 'reachable seeded case passes')
    for leaf in ('commands.jsonl', 'observations.jsonl', 'serial.jsonl', 'result.json', 'config.json'):
        check((a/leaf).read_bytes() == (b/leaf).read_bytes(), ('same seed replays identical bytes', leaf))
    check(read(a/'result.json')['targets'] != read(c/'result.json')['targets'], 'seed changes the actual case')
    for seed in (0, 1, 2, 7, 99, 12345678, 4294967295):
        path = directory/f'seed-{seed}'
        run(['run', '--output', path, '--seed', seed])
        check(audit(path)['passed'], ('additional reachable seeded case', seed))
    before = {p.name: p.read_bytes() for p in a.iterdir()}
    run(['run', '--output', a], 2)
    check(before == {p.name: p.read_bytes() for p in a.iterdir()}, 'existing run is never overwritten')
    check(json.loads(run(['show', a]).stdout)['passed'], 'reopen saved result')
    check(run(['replay', a]).stdout == (a/'observations.jsonl').read_bytes(), 'replay saved observations')
    stalled = directory/'jammed'
    run(['run', '--case', 'joint-stall', '--output', stalled])
    result = audit(stalled)
    check(result['passed'] and result['fault'] == 'stall' and result['plant'][0]['tick'] == 2048, 'jam judged from firmware fault and independent encoder')
    limited = directory/'limited'
    run(['run', '--output', limited, '--steps', 10], 1)
    check(read(limited/'result.json')['status'] == 'failed', 'step limit cannot report success')
    broken = directory/'missing-firmware'
    run(['run', '--output', broken, '--firmware', directory/'missing'], 2)
    check(not (broken/'result.json').exists(), 'unbootable firmware cannot produce passing result')
    run(['run', '--case', 'invented', '--output', directory/'invalid'], 2)
    check(not (directory/'invalid').exists(), 'invalid case rejected before artifacts')
    paused = directory/'paused'
    process = subprocess.Popen([str(GYM), 'run', '--output', str(paused), '--paused', '--realtime'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        wait_file(paused/'progress.json', lambda p: p['status'] == 'paused')
        endpoint = read(paused/'endpoint.json')
        check(endpoint['firmwarePid'] != process.pid and Path(f"/proc/{endpoint['firmwarePid']}/exe").resolve() == paused/'firmware.elf', 'firmware executes in its own process')
        # The existing control CLI connects to the bot, independently of Gym.
        result = subprocess.run([str(CLI), '--url', endpoint['url'], 'ping'], capture_output=True, timeout=3)
        check(result.returncode == 0 and result.stdout == b'pong\n', 'normal control client reaches paused bot endpoint')
        result = subprocess.run([str(CLI), '--url', endpoint['url'], '--json', 'arm', 'state'], capture_output=True, timeout=3)
        check(result.returncode == 0 and len(json.loads(result.stdout)['joints']) == 4, 'paused bot publishes an initial snapshot without advancing time')
        state = paused.joinpath('progress.json').read_bytes()
        time.sleep(.08)
        check(paused.joinpath('progress.json').read_bytes() == state, 'pause freezes simulation time')
        run(['resume', paused])
        wait_file(paused/'progress.json', lambda p: p['step'] >= 25)
        run(['stop', paused])
        process.communicate(timeout=5)
        check(process.returncode == 130 and read(paused/'result.json')['status'] == 'cancelled', 'stop finalizes cancelled run')
        check(not Path(f"/proc/{endpoint['firmwarePid']}").exists(), 'firmware reaped after cancellation')
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()


class Manager:
    def __init__(self, directory, cwd=ROOT):
        self.process = subprocess.Popen([str(GYM), 'serve', '--bind', '127.0.0.1:0', '--data', str(directory), '--firmware', str(FIRMWARE)],
                                        cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        ready, _, _ = select.select([self.process.stdout], [], [], 5)
        check(bool(ready), 'Gym manager startup deadline')
        line = self.process.stdout.readline()
        match = re.search(r'port (\d+)', line)
        if not match:
            self.process.kill()
            raise AssertionError((line, self.process.stderr.read()))
        self.port = int(match[1])

    def request(self, path, body=None, status=200):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        conn.request('GET' if body is None else 'POST', path, None if body is None else json.dumps(body), {'Content-Type': 'application/json'})
        response = conn.getresponse()
        data = response.read()
        check(response.status == status, (path, response.status, data))
        conn.close()
        return data.decode() if path == '/' else json.loads(data)

    def wait(self, path, predicate):
        end = time.monotonic()+7
        while time.monotonic() < end:
            value = self.request(path)
            if predicate(value):
                return value
            time.sleep(.02)
        raise AssertionError(('manager progress deadline', path, value))

    def monolith(self, path, fields=None, status=200, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        conn.request('GET' if fields is None else 'POST', path, None if fields is None else urlencode(fields),
                     {'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json', **(headers or {})})
        response = conn.getresponse()
        data = response.read()
        check(response.status == status, ('Monolith', path, response.status, data))
        result = data, dict(response.getheaders())
        conn.close()
        return result

    def close(self, kill=False):
        self.process.kill() if kill else self.process.send_signal(signal.SIGTERM)
        self.process.communicate(timeout=5)
        check(self.process.returncode == (-9 if kill else 0), 'Gym manager shutdown')


def management(directory):
    # The built Monolith app needs neither source files nor loose UI assets.
    manager = Manager(directory, cwd=directory.parent)
    try:
        html, headers = manager.monolith('/')
        check(b'PuppyBotGym' in html and b'data-mkey="gym-app"' in html, 'Monolith server-rendered management view')
        token = re.search(rb'name="monolith-token" content="([a-f0-9]{32})"', html)[1].decode()
        check(b'<script defer src="/client.js">' in html and "script-src 'self'" in headers['Content-Security-Policy'], 'embedded Monolith adapter with external-only scripts')
        client, _ = manager.monolith('/client.js')
        check(b"new EventSource('/events')" in client, 'upstream Monolith SSE client')
        style, _ = manager.monolith('/style.css')
        check(b'.layout' in style, 'embedded Gym stylesheet')
        manager.monolith('/action', {'token': 'wrong', 'action': 'launch', 'case': 'arm-reach', 'seed': 99}, 403)
        manager.monolith('/action', {'token': token, 'action': 'launch', 'case': 'arm-reach', 'seed': 99}, 403, {'Origin': 'http://example.invalid'})
        manager.monolith('/action', {'token': token, 'action': 'launch', 'case': 'invented', 'seed': 99}, 422)
        manager.monolith('/action', {'token': token, 'action': 'launch', 'case': 'arm-reach', 'seed': '1.5'}, 422)
        check({c['id'] for c in manager.request('/api/gym/cases')} ==
              {c['id'] for c in json.loads(run(['cases']).stdout)}, 'HTTP and CLI case catalogs agree')
        check(manager.request('/api/gym/runs') == [], 'empty catalog')
        manager.request('/api/drive', {}, 404)
        manager.request('/api/gym/runs', {'case': 'invented', 'seed': 42}, 400)
        manager.request('/api/gym/runs', {'case': 'arm-reach', 'seed': -1}, 400)
        # Connect before mutation and verify the native compiled view patch.
        stream = http.client.HTTPConnection('127.0.0.1', manager.port, timeout=3)
        stream.request('GET', '/events')
        events = stream.getresponse()
        check(events.status == 200 and events.getheader('Content-Type') == 'text/event-stream', 'Monolith SSE transport')
        def event():
            data = None
            while True:
                line = events.readline()
                if line.startswith(b'data: '):
                    data = json.loads(line[6:])
                if line in (b'\n', b'\r\n', b''):
                    return data
        snapshot = event()
        check(snapshot['reset'] and snapshot['token'] == token and any(op.get('key') == 'gym-app' for op in snapshot['ops']), 'keyed initial snapshot')
        manager.monolith('/action', {'token': token, 'action': 'launch', 'case': 'arm-reach', 'seed': 99})
        patch = event()
        check(not patch['reset'] and any(op['op'] == 'insert' and op.get('key') == 'run-1' for op in patch['ops']), 'launch emits keyed run insertion over SSE')
        stream.close()
        run_meta = manager.request('/api/gym/runs')[0]
        path = '/api/gym/runs/'+str(run_meta['id'])
        manager.wait(path, lambda p: p['progress'] and p['progress']['step'] >= 25)
        manager.request(path+'/pause', {})
        p = manager.wait(path, lambda p: p['progress']['status'] == 'paused')
        frozen = p['progress']['timeMs']
        time.sleep(.1)
        check(manager.request(path)['progress']['timeMs'] == frozen, 'HTTP pause freezes worker clock')
        samples = manager.request(path+'/samples')
        check(0 < len(samples) <= 32 and samples[0]['step'] == 0, 'saved trace preview')
        manager.request(path+'/resume', {})
        manager.wait(path, lambda p: p['run']['status'] == 'passed')
        manager.request(path+'/stop', {}, 409)
        check(read(Path(run_meta['directory'])/'result.json')['passed'], 'managed worker saved accepted result')
        # Lock prevents a second manager from mutating the same catalog.
        run(['serve', '--bind', '127.0.0.1:0', '--data', directory], 1)
    finally:
        manager.close()
    manager = Manager(directory)
    try:
        check(manager.request('/api/gym/runs')[0]['status'] == 'passed', 'FlexDB history survives restart')
        meta = manager.request('/api/gym/runs', {'case': 'arm-reach', 'seed': 7})
        path = '/api/gym/runs/'+str(meta['id'])
        state = manager.wait(path, lambda p: p['endpoint'] is not None)
        child = state['endpoint']['firmwarePid']
        worker = int(Path(f'/proc/{child}/status').read_text().split('PPid:\t')[1].splitlines()[0])
        manager.close(kill=True)
        time.sleep(.1)
        check(not Path(f'/proc/{child}/exe').exists() and not Path(f'/proc/{worker}/exe').exists(), 'manager crash does not leave live workers or firmware')
        manager = None
    finally:
        if manager:
            manager.close()
    manager = Manager(directory)
    try:
        records = manager.request('/api/gym/runs')
        check(records[-1]['status'] in ('interrupted', 'passed'), 'crash recovery marks unfinished rollout explicitly')
        meta = manager.request('/api/gym/runs', {'case': 'arm-reach', 'seed': 12})
        manager.wait('/api/gym/runs/'+str(meta['id']), lambda p: p['endpoint'] is not None)
    finally:
        manager.close()
    check(read(Path(meta['directory'])/'result.json')['status'] == 'cancelled', 'graceful manager shutdown finalizes active rollout')


def main():
    with tempfile.TemporaryDirectory(prefix='gym-test-', dir=ROOT/'build/flex') as temporary:
        directory = Path(temporary)
        cli_cases(directory)
        management(directory/'manager')
    print(f'PuppyBotGym: {CHECKS} simulation/process/artifact/management checks passed')


if __name__ == '__main__':
    main()
