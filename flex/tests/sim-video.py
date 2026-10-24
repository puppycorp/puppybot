#!/usr/bin/env python3
"""Decode real MP4s and check timing, pixels, controller isolation and shutdown."""
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time

# Avoid tests/numbers.py shadowing the standard library imported by Pillow.
sys.path = [p for p in sys.path if Path(p).resolve() != Path(__file__).resolve().parent]
from PIL import Image, ImageChops, ImageStat

ROOT = Path(__file__).resolve().parents[2]
BINARY = Path(os.environ.get('PUPPYBOT_TEST_SIM', ROOT/'build/flex/puppybot-sim'))


def run(*args, env=None, status=0):
    result = subprocess.run([str(BINARY), *map(str, args)], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=45)
    assert result.returncode == status, result.stdout+result.stderr
    return result


def inspect(path):
    result = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-show_streams',
                             '-of', 'json', str(path)], capture_output=True, text=True, check=True)
    streams = json.loads(result.stdout)['streams']
    assert len(streams) == 1
    stream = streams[0]
    assert stream['codec_name'] == 'h264' and stream['pix_fmt'] == 'yuv420p'
    assert (stream['width'], stream['height']) == (1280, 800)
    subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-f', 'null', '-'], check=True)
    return stream


def pixels(video, image, frames):
    decoded = image.with_name(image.stem+'-decoded.png')
    subprocess.run(['ffmpeg', '-v', 'error', '-i', str(video), '-vf', fr'select=eq(n\,{frames-1})',
                    '-frames:v', '1', str(decoded)], check=True)
    with Image.open(image) as expected, Image.open(decoded) as actual:
        difference = ImageStat.Stat(ImageChops.difference(expected.convert('RGB'), actual.convert('RGB')))
        assert max(difference.mean) < 4, difference.mean


def interrupted(directory):
    video, trace = directory/'interrupted.mp4', directory/'interrupted.jsonl'
    with (directory/'interrupted.log').open('w') as output:
        child = subprocess.Popen([str(BINARY), '--hidden', '--realtime', '--steps', '5000',
            '--bind', '127.0.0.1:0', '--video', str(video), '--record', str(trace)],
            cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
        encoder = None
        try:
            deadline = time.monotonic()+10
            while not trace.exists() or trace.stat().st_size < 100000:
                assert child.poll() is None and time.monotonic() < deadline
                time.sleep(.02)
            children = Path(f'/proc/{child.pid}/task/{child.pid}/children').read_text().split()
            assert len(children) == 1
            encoder = int(children[0])
            child.send_signal(signal.SIGTERM)
            assert child.wait(timeout=10) == 0
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
        assert encoder is not None and not Path(f'/proc/{encoder}').exists(), 'encoder was not reaped'
    assert int(inspect(video)['nb_read_frames']) > 0


def resized(directory):
    # Exercise real window/FBO resizing without moving the controller or map.
    source = (ROOT/'flex/sim/main.flex').read_text().replace('fn main(argc, argv)', 'fn ps_application_main(argc, argv)')
    source = re.sub(r'^import "([^"]+)";', lambda m: 'import '+json.dumps(str(ROOT/'flex/sim'/m[1]))+';', source, flags=re.MULTILINE)
    source += r'''
fn main(argc, argv) {
    if !pl_init() { return 1; } h_environment(argc, argv);
    ps_device = render_open("Video resize check", 96, 64, GUI_HIDDEN | GUI_RESIZABLE); if !ps_device { return 2; }
    if !ps_video_open(load64(argv + 8)) { return 3; }
    let color = alloc(16); pb_zero(color, 16); pb_put32(color, 0x3f800000);
    render_gl(ps_device, "glClearBufferfv", 0x1800, 0, color, 0, 0, 0); if !ps_video_frame(2, 0) { return 4; }
    if !gui_resize(load64(ps_device), 144, 48) { return 5; }
    pb_zero(color, 16); pb_put32(color + 8, 0x3f800000);
    render_gl(ps_device, "glClearBufferfv", 0x1800, 0, color, 0, 0, 0); if !ps_video_frame(4, 1) { return 6; }
    let ok = ps_video_close(); render_close(ps_device); gui_quit(); return !ok;
}
'''
    entry, binary = directory/'resize.flex', directory/'resize'
    entry.write_text(source)
    compiler = os.environ.get('FLEXSCRIPT_COMPILER', str(ROOT/'build/flex/pup-compiler'))
    subprocess.run([compiler, str(entry), '-o', str(binary)], cwd=ROOT, check=True)
    video = directory/'resize.mp4'
    subprocess.run([str(binary), str(video)], cwd=ROOT, check=True, timeout=15)
    decoded = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(video), '-f', 'rawvideo',
                              '-pix_fmt', 'rgb24', '-'], capture_output=True, check=True).stdout
    assert len(decoded) == 2*96*64*3
    def pixel(frame, x, y):
        at = ((frame*64+y)*96+x)*3
        return tuple(decoded[at:at+3])
    assert pixel(0, 48, 32)[0] > 240
    assert pixel(1, 48, 32)[2] > 240
    assert max(pixel(1, 48, 4)) < 10 and max(pixel(1, 48, 60)) < 10
    print('Window resize: fixed output dimensions and letterboxing passed', flush=True)


def failures(directory):
    for fps in ('0', '51', '-1', 'abc'):
        run('--video', directory/'invalid.mp4', '--video-fps', fps, status=2)
    run('--video-fps', '25', status=2)
    run('--headless', '--steps', '1', '--video', directory/'invalid.mp4', status=2)
    assert not (directory/'invalid.mp4').exists()
    existing = directory/'existing.mp4'
    existing.write_bytes(b'preserved video')
    run('--hidden', '--steps', '1', '--bind', '127.0.0.1:0', '--video', existing, status=1)
    assert existing.read_bytes() == b'preserved video'
    run('--hidden', '--steps', '1', '--bind', '127.0.0.1:0', '--video', directory/'bad.avi', status=1)
    env = dict(os.environ, PATH=str(directory/'missing-tools'))
    run('--hidden', '--steps', '1', '--bind', '127.0.0.1:0', '--video', directory/'missing.mp4', env=env, status=1)
    assert not (directory/'missing.mp4').exists()
    tools = directory/'failed-tools'
    tools.mkdir()
    encoder = tools/'ffmpeg'
    encoder.write_text('#!/bin/sh\nexit 7\n')
    encoder.chmod(0o755)
    result = run('--hidden', '--steps', '50', '--bind', '127.0.0.1:0', '--video', directory/'failed.mp4',
                 env=dict(os.environ, PATH=str(tools)), status=1)
    assert 'Video recording:' in result.stderr and 'Video saved:' not in result.stderr


def main():
    with tempfile.TemporaryDirectory(prefix='sim-video-', dir=ROOT/'build/flex/sim') as temp:
        directory = Path(temp)
        for steps, fps in ((50, 25), (53, 17), (1, 50)):
            name = f'{steps}-{fps}'
            video, image = directory/(name+' with spaces.mp4'), directory/(name+'.png')
            trace = directory/(name+'.jsonl')
            run('--hidden', '--demo', '--steps', steps, '--bind', '127.0.0.1:0',
                '--video', video, '--video-fps', fps, '--capture', image, '--record', trace)
            stream = inspect(video)
            frames = math.ceil(steps*fps/50)
            assert int(stream['nb_read_frames']) == frames, (name, stream['nb_read_frames'], frames)
            assert stream['avg_frame_rate'] == f'{fps}/1'
            assert abs(float(stream['duration'])-frames/fps) < .00001
            pixels(video, image, frames)
            baseline = directory/(name+'-baseline.jsonl')
            run('--hidden', '--demo', '--steps', steps, '--bind', '127.0.0.1:0', '--record', baseline)
            actual = [json.loads(line) for line in trace.read_text().splitlines()]
            expected = [json.loads(line) for line in baseline.read_text().splitlines()]
            assert len(actual) == len(expected) == steps
            for a, b in zip(actual, expected):
                for field in ('controller', 'pose', 'ticks', 'gripper', 'physicsFault'):
                    assert a[field] == b[field], (name, field)
            print(f'{name}: frame count, timing, decoded pixels and controller isolation passed', flush=True)
        interrupted(directory)
        resized(directory)
        failures(directory)
    print('Video checks passed: H.264 MP4, orientation, partial frames, paths with spaces, SIGTERM finalization/reaping, CLI bounds, existing files and encoder failures')


if __name__ == '__main__':
    main()
