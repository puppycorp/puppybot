#!/usr/bin/env python3
"""One supervised CPU-only first-scan diagnostic; no renderer or robot policy."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
ARCHIVE = ROOT / 'build/flex/sim/levels-v2/pitch82/dock-survey-elevation-build-v1'
SOURCE = ROOT / 'build/flex/sim/reverse-frontier-v20/west-tight/map/episode-0'
OUTPUT = ROOT / 'build/flex/sim/barrier-real-worker-cpu-v1'
EXPECTED = {'input-369.json': '924ad3f6cf1d5dcfe9e99b8d7d62a3aa250ecd521adb7ef9edf18ea32c87cbe2',
            'rgb-0.bin': '6d33e84e2c27d88ccb486669c66b438ef24bdd90bb1d7ddc19cc12f673313b9b',
            'rgb-1.bin': 'a1dabd46ae6cb7018ae75beec595bb9ba31635e572442d15b4e8442d600429db'}
WORKER_SHA = '754d1b7f1f91637e6efaf267173e5cbff662179c8c5d61d8aa7c9e974d2fed24'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_inputs():
    for name, digest in EXPECTED.items():
        if sha(SOURCE / name) != digest: raise ValueError(f'input changed: {name}')
    if sha(ROOT / 'flex/vision/discovery.py') != WORKER_SHA: raise ValueError('worker source changed')
    request = json.loads((SOURCE / 'input-369.json').read_text())
    if request['frameId'] != 369 or not request['newScan'] or [Path(x['rgb']) for x in request['frames']] != [SOURCE / 'rgb-0.bin', SOURCE / 'rgb-1.bin']:
        raise ValueError('request identity differs')


def main():
    verify_inputs()
    transform = load('barrier_transform', HERE / 'transform.py')
    supervisor = load('barrier_supervisor', ROOT / 'flex/tests/run-physical-hidden-trial.py')
    OUTPUT.mkdir(parents=False, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='puppy-barrier-build-') as temp:
        temp = Path(temp); source = temp / 'source'; build = temp / 'build'
        shutil.copytree(ARCHIVE / 'source', source); shutil.copytree(ARCHIVE / 'build', build)
        library = build / 'flex/sim/library'; adapter = library / 'lib/f64.flex'
        adapter.write_text(transform.once(adapter.read_text(), f'import "{ARCHIVE / "source/core/words.flex"}";', f'import "{source / "core/words.flex"}";'))
        (library.parent / 'dependencies.flex').write_text(f'import "{library / "libs/render.flex"}";\nimport "{library / "libs/physics/physics.flex"}";\n')
        discovery, main = source / 'sim/discovery.flex', source / 'sim/main.flex'
        a, b = transform.transform(discovery.read_text(), main.read_text()); discovery.write_text(a)
        b = transform.once(b, 'fn main(argc, argv) {', 'fn simulator_main(argc, argv) {')
        main.write_text(b + '\n' + (HERE / 'real-worker-main.flex').read_text())
        binary = OUTPUT / 'driver'
        built = subprocess.run([str(ROOT / 'build/flex/control/compiler'), str(main), '-o', str(binary)], cwd=ROOT, capture_output=True, text=True, timeout=120)
        (OUTPUT / 'build.log').write_text(built.stdout + built.stderr)
        if built.returncode: raise RuntimeError('driver build failed')
    env = dict(os.environ, CUDA_VISIBLE_DEVICES='', OPENCV_OPENCL_RUNTIME='disabled',
               OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
    manifests = {name: sha(SOURCE / name) for name in EXPECTED}
    manifests.update(worker=WORKER_SHA, driver=sha(binary), wrapper=sha(HERE / 'delayed-worker.py'))
    (OUTPUT / 'inputs.json').write_text(json.dumps(manifests, indent=2, sort_keys=True) + '\n')
    runs = []
    for name, delay in (('fast', '0'), ('delayed', '1')):
        monitor = OUTPUT / name; monitor.mkdir(); target = monitor / 'map'
        command = ['/usr/bin/nice', '-n', '15', '/usr/bin/ionice', '-c', '3', str(binary),
                   str(HERE / 'delayed-worker.py'), str(SOURCE / 'input-369.json'), str(target), delay]
        status = supervisor.supervise(command, monitor, env, 30)
        if status['clientExit'] != 0 or status['timedOut'] or status['signal'] is not None or status['remainingWorkersTerminated']:
            raise RuntimeError(f'{name} censored; inspect {monitor}')
        record = json.loads((monitor / 'client.log').read_text())
        record['outputs'] = {key: sha(target / key) for key in ('safe.bin', 'observed.bin', 'observed-detail.bin', 'map.json')}
        record['supervisor'] = status; runs.append(record)
        verify_inputs()
        if sha(binary) != manifests['driver'] or sha(HERE / 'delayed-worker.py') != manifests['wrapper']:
            raise ValueError('driver or delay wrapper changed')
    if runs[0]['mapApplyTick'] != runs[1]['mapApplyTick'] or runs[0]['outputs'] != runs[1]['outputs']:
        raise ValueError('worker result or application tick differed')
    if runs[1]['workerWallMs'] <= runs[0]['workerWallMs'] + 700:
        raise ValueError('deliberate latency difference was not observed')
    result = {'scope': 'old captured first scan; direct simulator validation only; no dock replay, policy, renderer, or physical robot',
              'simulatedTime': 'worker latency omitted; not comparable to unbarriered simulated-time scoring', 'runs': runs}
    (OUTPUT / 'result.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__': main()
