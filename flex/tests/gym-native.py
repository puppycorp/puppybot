#!/usr/bin/env python3
"""Exercise real camera simulation through Gym, including saved browser playback."""
import argparse
import hashlib
import http.client
import importlib.util
import json
from pathlib import Path
import signal
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
GYM = ROOT/'build/flex/puppybotgym'
SIM = ROOT/'build/flex/puppybot-sim'
CASE = 'discover-house-blocks-into-box'
spec = importlib.util.spec_from_file_location('gym_checks', Path(__file__).with_name('gym.py'))
gym = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gym)


def read(path):
    return json.loads(path.read_bytes())


def wait(path, predicate):
    deadline = time.monotonic()+20
    while time.monotonic() < deadline:
        if path.exists():
            value = read(path)
            if predicate(value):
                return value
        time.sleep(.02)
    raise AssertionError(('artifact deadline', path))


def run(*args, code=0):
    result = subprocess.run([str(GYM), *map(str, args)], cwd=ROOT, capture_output=True, timeout=20)
    assert result.returncode == code, (result.returncode, result.stdout, result.stderr)
    return result


def video(path, step):
    result = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-show_streams',
                             '-of', 'json', str(path)], capture_output=True, check=True)
    stream, = json.loads(result.stdout)['streams']
    assert stream['codec_name'] == 'h264' and stream['r_frame_rate'] == '5/1'
    assert int(stream['nb_read_frames']) == max(1, (step+9)//10)
    subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-f', 'null', '-'], check=True)


def lifecycle(directory):
    bounded = directory/'bounded'
    run('run', '--case', CASE, '--steps', 120, '--simulator', SIM, '--output', bounded, code=1)
    result = read(bounded/'result.json')
    assert result['step'] == 120 and result['timeMs'] == 2400
    assert result['status'] == 'failed' and not result['passed']
    assert result['recordingReady']
    assert result['backend'] == 'flexscript-kinematic-contact-v1'
    assert result['contactPhysics'] and not result['articulatedPhysics']
    assert hashlib.sha256((bounded/'simulator.elf').read_bytes()).digest() == hashlib.sha256(SIM.read_bytes()).digest()
    trace = [json.loads(line) for line in (bounded/'simulation.jsonl').read_bytes().splitlines()]
    assert len(trace) == 120 and trace[-1]['step'] == 120
    assert all(not row['physicsFault'] and not row['vehicle']['queryFault'] for row in trace)
    assert trace[0]['discovery']['suppliedMap'] is False and trace[0]['discovery']['freeCells'] == 0
    assert trace[0]['localization']['pose'] == [0, 0, 0]
    samples = [json.loads(line) for line in run('replay', bounded).stdout.splitlines()]
    assert [sample['step'] for sample in samples] == [0, 25, 50, 75, 100]
    before = (bounded/'result.json').read_bytes()
    run('run', '--case', CASE, '--steps', 120, '--simulator', SIM, '--output', bounded, code=2)
    assert (bounded/'result.json').read_bytes() == before
    video(bounded/'mission.mp4', 120)
    assert (bounded/'outcome.png').read_bytes().startswith(b'\x89PNG')
    layout = directory/'layout'
    subprocess.run(['python3', str(ROOT/'flex/scripts/generate-layout.py'), '--seed', '401',
                    '--rooms', '2', '--output', str(layout)], cwd=ROOT, check=True, timeout=20)
    generated = directory/'generated'
    run('run', '--case-file', layout/'case.json', '--environment', layout/'environment.bin',
        '--steps', 120, '--simulator', SIM, '--output', generated, code=1)
    generated_result = read(generated/'result.json')
    assert generated_result['case'] == read(layout/'case.json')['id']
    assert generated_result['step'] == 120 and not generated_result['passed']
    assert read(generated/'manifest.json')['environment'] == str(layout/'environment.bin')
    paused = directory/'paused'
    with (directory/'paused.log').open('wb') as log:
        child = subprocess.Popen([str(GYM), 'run', '--case', CASE, '--steps', '10000',
            '--paused', '--simulator', str(SIM), '--output', str(paused)], cwd=ROOT, stdout=log, stderr=log)
        try:
            state = wait(paused/'progress.json', lambda p: p['status'] == 'paused')
            assert state['step'] == 0
            assert not state['recordingReady']
            frozen = (paused/'progress.json').read_bytes()
            time.sleep(.1)
            assert (paused/'progress.json').read_bytes() == frozen
            run('resume', paused)
            wait(paused/'progress.json', lambda p: p['step'] >= 50)
            run('pause', paused)
            state = wait(paused/'progress.json', lambda p: p['status'] == 'paused')
            frozen = (paused/'progress.json').read_bytes()
            size = (paused/'simulation.jsonl').stat().st_size
            time.sleep(.1)
            assert (paused/'progress.json').read_bytes() == frozen
            assert (paused/'simulation.jsonl').stat().st_size == size
            run('stop', paused)
            assert child.wait(timeout=10) == 130
            result = read(paused/'result.json')
            assert result['status'] == 'cancelled' and not result['passed']
            assert result['step'] == state['step']
            video(paused/'mission.mp4', result['step'])
            assert (paused/'outcome.png').read_bytes().startswith(b'\x89PNG')
        finally:
            if child.poll() is None:
                child.send_signal(signal.SIGTERM)
                child.wait(timeout=10)


def artifact(manager, identifier, leaf, headers=None, expected=200):
    connection = http.client.HTTPConnection('127.0.0.1', manager.port, timeout=10)
    connection.request('GET', f'/api/gym/runs/{identifier}/artifacts/{leaf}', headers=headers or {})
    response = connection.getresponse()
    data = response.read()
    assert response.status == expected, (response.status, data[:100])
    fields = dict(response.getheaders())
    connection.close()
    return data, fields


def managed(directory):
    # Start with the ordinary launcher to exercise its source build/display path.
    manager = gym.Manager(directory)
    try:
        cases = manager.request('/api/gym/cases')
        assert {c['id'] for c in cases} == {'arm-reach', 'joint-stall'} | {c['id'] for c in read(ROOT/'flex/sim/cases/catalog.json')['cases']}
        meta = manager.request('/api/gym/runs', dict(case=CASE, seed=123))
        identifier = meta['id']
        path = '/api/gym/runs/'+str(identifier)
        manager.wait(path, lambda p: p['progress'] and p['progress']['step'] >= 25)
        manager.request(path+'/pause', {})
        manager.wait(path, lambda p: p['progress']['status'] == 'paused')
        manager.request(path+'/resume', {})
        manager.request(path+'/stop', {})
        manager.wait(path, lambda p: p['run']['status'] == 'cancelled')
        folder = Path(meta['directory'])
        samples = manager.request(path+'/samples')
        assert 0 < len(samples) <= 32 and samples[0]['step'] == 0
        movie = (folder/'mission.mp4').read_bytes()
        data, headers = artifact(manager, identifier, 'mission.mp4', {'Range': 'bytes=0-63'}, 206)
        assert data == movie[:64] and headers['Content-Range'] == f'bytes 0-63/{len(movie)}'
        assert artifact(manager, identifier, 'mission.mp4')[0] == movie
        assert artifact(manager, identifier, 'outcome.png')[0] == (folder/'outcome.png').read_bytes()
        artifact(manager, identifier, '../manifest.json', expected=404)
        artifact(manager, identifier, 'mission.mp4', {'Range': 'bytes=999999999-'}, 400)
        artifact(manager, identifier, 'mission.mp4', {'Range': 'bytes=0-1,4-5'}, 400)
        html, headers = manager.monolith('/')
        assert b'mission-video' in html and b'BRICKS DELIVERED' in html
        assert b'0 / 6' in html and b'None' in html
        assert "media-src 'self'" in headers['Content-Security-Policy']
        assert "img-src 'self'" in headers['Content-Security-Policy']
        pid = read(folder/'endpoint.json')['simulatorPid']
        assert not Path(f'/proc/{pid}').exists()
    finally:
        manager.close()
    manager = gym.Manager(directory)
    try:
        assert manager.request('/api/gym/runs')[0]['status'] == 'cancelled'
        assert artifact(manager, identifier, 'mission.mp4')[0] == movie
    finally:
        manager.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    directory = args.output.resolve()
    lifecycle(directory)
    managed(directory/'manager')
    (directory/'audit.json').write_text(json.dumps(dict(passed=True, realNativeCameraRollouts=True,
        boundedRunIncomplete=True, fullMissionVerified=False, pauseResumeStop=True,
        videoDecoded=True, browserArtifactRanges=True, retainedHistory=True), indent=2)+'\n')
    print('Native Gym passed: actual camera/physics rollouts, cold unknown map, bounded failure, pause/resume/stop, video decoding/ranges, saved trace and history')


if __name__ == '__main__':
    main()
