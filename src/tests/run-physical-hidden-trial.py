#!/usr/bin/env python3
"""Supervise a hybrid simulator selection case with an initial detector miss.

Usage: python3 -I flex/tests/run-physical-hidden-trial.py --check
       python3 -I flex/tests/run-physical-hidden-trial.py NEW_OUTPUT_DIRECTORY

Requires the GPU to be otherwise idle. The case places the brick behind the
robot, and the audit requires an initial RGB frame without a detector output;
that miss alone does not prove geometric invisibility. It records whether a
subsequent handoff follows one or more policy actions. This temporal ordering
alone does not establish that policy motion caused the detection. The collector remains the existing
heuristic controller; audit simulator truth only after the run. No
physical-hardware claim is made.
"""
import argparse
import ctypes
import importlib.util
import json
import math
import os
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
RESCAN = PROJECT / 'flex/tests/run-physical-rescan-trial.py'
spec = importlib.util.spec_from_file_location('rescan_trial', RESCAN)
rescan = importlib.util.module_from_spec(spec); spec.loader.exec_module(rescan)
supervisor = rescan.supervisor
sha = rescan.sha
MODEL, ENVIRONMENT, ASSET = rescan.MODEL, rescan.ENVIRONMENT, rescan.ASSET
NAV_LIMIT, POLL_LIMIT, WALL_SECONDS = 90, 1499, 300


def prepare_case():
    case = json.loads((rescan.REFERENCE / 'case.json').read_text())
    if len(case['objects']) != 1:
        raise ValueError('expected the one-brick selection case')
    case['id'] = 'physical-hybrid-hidden-selection'
    case['objects'][0]['position'] = [-0.65, 0.15, 0.013]
    return json.dumps(case, indent=2) + '\n'


def check_actor_inputs(run, result, journal):
    keys = {'schema', 'sequence', 'step', 'timeMs', 'owner', 'ack', 'imageValid', 'rgbDetections',
            'driveCommand', 'jointTicks', 'totalSteps', 'cameraFrame', 'cameraDriving', 'cameraStill'}
    if not journal or any(set(row) != keys or row['schema'] != 'puppybot.physical-agent.v1' for row in journal):
        raise ValueError('unexpected observation schema or potentially privileged fields')
    if [r['sequence'] for r in journal] != list(range(1, len(journal) + 1)):
        raise ValueError('missing or replayed observation sequence')
    first = journal[0]
    if first['ack'] != 0 or first['owner'] != 0 or not first['imageValid'] or first['rgbDetections'] != 0:
        raise ValueError('initial camera frame contained a detector output')
    for row in journal:
        if row['owner'] == 0:
            if (not row['imageValid'] or row['cameraFrame'] != row['totalSteps'] or not row['cameraDriving'] or
                    not row['cameraStill'] or row['jointTicks'] != first['jointTicks'] or
                    not isinstance(row['rgbDetections'], int) or row['rgbDetections'] < 0):
                raise ValueError('stale navigation camera or changing arm')
        elif row['imageValid']:
            raise ValueError('collector-owned response exposed a camera image')
    actions = [(i, r) for i, r in enumerate(journal) if r['ack'] == 1]
    if len(actions) != result['policyActions'] or not actions:
        raise ValueError('policy action count missing or inconsistent')
    actors = run / 'actors'; expected = set(); previous_action = bytes(8); moving = 0
    for i, row in actions:
        if i == 0:
            raise ValueError('action has no preceding observation')
        prior = journal[i - 1]
        if prior['owner'] != 0 or not prior['imageValid']:
            raise ValueError('actor ran without a navigation image')
        stem = f"actor-{prior['sequence']}"
        expected.update(stem + suffix for suffix in ('.rgb', '.feedback', '.hidden', '.action'))
        image = (actors / (stem + '.rgb')).read_bytes()
        feedback = (actors / (stem + '.feedback')).read_bytes()
        hidden = (actors / (stem + '.hidden')).read_bytes()
        action = (actors / (stem + '.action')).read_bytes()
        if len(image) != 21168 or len(feedback) != 28 or len(hidden) != 512 or len(action) != 8:
            raise ValueError('invalid recorded actor input or action size')
        if i == actions[0][0] and hidden != bytes(512):
            raise ValueError('first recorded recurrent state is not zero')
        if feedback[:8] != previous_action:
            raise ValueError('recorded previous action differs')
        drive = prior['driveCommand']
        expected_feedback = struct.pack('<5f', drive[0] / 100, drive[1] / 100, (drive[2] - 90) / 45, 0, 0)
        if feedback[8:] != expected_feedback:
            raise ValueError('recorded own-drive/contact feedback differs from observation')
        steering, speed = struct.unpack('<2f', action)
        if not all(math.isfinite(v) and abs(v) <= 1 for v in (steering, speed)) or not all(math.isfinite(v) for v in struct.unpack('<128f', hidden)):
            raise ValueError('invalid policy action or recurrent state')
        s, v = round(steering * 1000), round(speed * 1000)
        throttle = math.trunc(v * 60 / 1000) if abs(v) >= 80 else 0
        expected_drive = [throttle, throttle, 90 + math.trunc(math.trunc(s / 10) * 45 / 100)]
        if row['driveCommand'] != expected_drive or row['totalSteps'] != prior['totalSteps'] + 10:
            raise ValueError('action drive echo or simulator tick count differs')
        moving += int(throttle != 0)
        previous_action = action
    if {p.name for p in actors.iterdir()} != expected:
        raise ValueError('unexpected/missing actor decision artifacts')
    handoffs = [i for i, row in enumerate(journal) if row['ack'] == 3]
    if bool(handoffs) != result['handoff'] or len(handoffs) > 1:
        raise ValueError('handoff result disagrees with observations')
    if handoffs:
        i = handoffs[0]
        if i == 0 or journal[i - 1]['rgbDetections'] <= 0 or not any(j < i for j, _ in actions):
            raise ValueError('handoff was not preceded by learned action and camera detection')
        if journal[i]['driveCommand'] != [0, 0, 90] or journal[i]['totalSteps'] != journal[i - 1]['totalSteps'] + 2:
            raise ValueError('handoff stop/timing was not acknowledged')
    if journal[-1]['ack'] != 7 or journal[-1]['owner'] != 2 or journal[-1]['driveCommand'] != [0, 0, 90]:
        raise ValueError('simulated final stop not acknowledged')
    if not result['stopCommandAcknowledged'] or result['outcome'] != 'unverified':
        raise ValueError('client result claims an unverified outcome')
    return {'initialDetection': 0, 'policyActions': len(actions), 'nonzeroDriveActions': moving,
            'handoffAfterPolicy': bool(handoffs),
            'causalAttribution': 'unproven',
            'recordingScope': 'sizes, own feedback and drive echoes checked; raw camera-to-actor resize and actor runtime execution not independently replayed'}


def truth_navigation_path(trace, start_tick, end_tick):
    # Simulator pose is used only after the run to audit physical motion, never
    # as an actor input or as a substitute for a physical pickup event.
    if type(start_tick) is not int or type(end_tick) is not int or start_tick < 0 or end_tick < start_tick:
        raise ValueError('invalid navigation tick range')
    first, last, previous, previous_tick, path = None, None, None, None, 0.0
    with trace.open() as stream:
        for line in stream:
            state = json.loads(line); tick = state['totalSteps']
            if type(tick) is not int or tick < 0:
                raise ValueError('invalid simulator tick')
            if tick < start_tick:
                continue
            if tick > end_tick:
                break
            if previous_tick is not None and tick != previous_tick + 1:
                raise ValueError('navigation trace has missing or duplicate steps')
            pose = state['pose']
            if not isinstance(pose, list) or len(pose) != 3 or not all(type(v) in (int, float) and math.isfinite(v) for v in pose):
                raise ValueError('invalid simulator pose')
            if tick == start_tick:
                first = pose
            if previous is not None:
                path += math.dist(previous[:2], pose[:2])
            previous = pose
            previous_tick = tick
            if tick == end_tick:
                last = pose
    if first is None or last is None:
        raise ValueError('trace lacks navigation start/end poses')
    return {'pathM': path, 'netDisplacementM': math.dist(first[:2], last[:2]),
            'scope': 'post-run simulator-truth audit only'}


def supervise(command, output, env, wall_seconds=WALL_SECONDS):
    libc = ctypes.CDLL(None, use_errno=True); previous_subreaper = ctypes.c_int()
    if libc.prctl(37, ctypes.byref(previous_subreaper), 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), 'cannot read child subreaper state')
    if libc.prctl(36, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), 'cannot supervise orphaned workers')
    signals = []
    def interrupted(signum, _frame):
        # Never raise during spawn or cleanup: the spawned process may have
        # its own session and must be collected even if a signal arrives.
        signals.append(signum)
    status = {'clientExit': None, 'timedOut': False, 'remainingWorkersTerminated': False,
              'signal': None}; start = time.monotonic()
    handlers = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    try:
        with (output / 'client.log').open('w') as log:
            process = None
            try:
                if not signals:
                    process = subprocess.Popen(command, cwd=PROJECT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                    status['processGroup'] = process.pid
                while process is not None and process.poll() is None:
                    if signals:
                        break
                    if time.monotonic() - start >= wall_seconds:
                        status['timedOut'] = True
                        break
                    time.sleep(.05)
            finally:
                if process is not None and process.poll() is None:
                    try: os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError: pass
                    try: process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        try: os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                        process.wait()
                if process is not None:
                    status['clientExit'] = process.returncode
                status['remainingWorkersTerminated'] = supervisor.cleanup_descendants()
                status['wallSeconds'] = round(time.monotonic() - start, 3)
                if signals: status['signal'] = signals[0]
                (output / 'supervisor-result.json').write_text(json.dumps(status, indent=2) + '\n')
    finally:
        if libc.prctl(36, previous_subreaper.value, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), 'cannot restore child subreaper state')
        for sig, handler in handlers.items(): signal.signal(sig, handler)
    return status


def run_trial(output):
    output.mkdir(parents=False, exist_ok=False)
    inputs = output / 'inputs'; inputs.mkdir()
    (inputs / 'case.json').write_text(prepare_case()); shutil.copy2(ENVIRONMENT, inputs / 'environment.bin')
    rescan.verify_model(MODEL); shutil.copytree(MODEL, inputs / 'model'); rescan.verify_model(inputs / 'model')
    sources, libraries, compiler_hash = rescan.build_snapshot(inputs)
    env = os.environ.copy(); env.pop('DISPLAY', None); env.pop('WAYLAND_DISPLAY', None)
    env.pop('PUPPYBOT_PHYSICAL_GUARDED_RESCAN', None)
    env.update(SDL_VIDEODRIVER='offscreen', LD_LIBRARY_PATH=str(PROJECT / 'build/flex/rocm-runtime'),
               PUPPYBOT_PHYSICAL_NAV_LIMIT=str(NAV_LIMIT), PUPPYBOT_PHYSICAL_POLL_LIMIT=str(POLL_LIMIT))
    worker = supervisor.worker_snapshot(env)
    manifest = {'caseSHA256': sha(inputs / 'case.json'), 'environmentSHA256': sha(inputs / 'environment.bin'),
                'simulatorSHA256': sha(inputs / 'simulator'), 'clientSHA256': sha(inputs / 'client'),
                'weightsSHA256': sha(inputs / 'model/weights.bin'), 'policySHA256': sha(inputs / 'model/policy'),
                'receiptSHA256': sha(inputs / 'model/receipt.json'), 'assetSHA256': sha(ASSET),
                'compilerSHA256': compiler_hash, 'navigationActionLimit': NAV_LIMIT, 'collectorPollLimit': POLL_LIMIT,
                'wallSeconds': WALL_SECONDS, 'scope': 'training-selection case; shared asset checked before/after; host runtime only partly captured'}
    (output / 'inputs.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (output / 'source-inputs.json').write_text(json.dumps(sources, indent=2) + '\n')
    (output / 'library-inputs.json').write_text(json.dumps(libraries, indent=2) + '\n')
    (output / 'worker-inputs.json').write_text(json.dumps(worker, indent=2) + '\n')
    command = [str(inputs / 'client'), str(inputs / 'simulator'), str(inputs / 'model'), str(inputs / 'case.json'),
               str(inputs / 'environment.bin'), str(output / 'run'), '--allow-zero-contact']
    status = supervise(command, output, env)
    if status['signal'] is not None or status['timedOut'] or status['clientExit'] != 0 or status['remainingWorkersTerminated']:
        raise RuntimeError(f'trial failed or required cleanup; inspect {output}')
    if (sha(ASSET) != manifest['assetSHA256'] or sha(inputs / 'simulator') != manifest['simulatorSHA256'] or
            sha(inputs / 'client') != manifest['clientSHA256'] or sha(inputs / 'case.json') != manifest['caseSHA256'] or
            sha(inputs / 'environment.bin') != manifest['environmentSHA256'] or supervisor.source_hashes(inputs / 'flex-source') != sources or
            supervisor.source_hashes(inputs / 'build/flex/sim/library') != libraries):
        raise RuntimeError('shared asset or archived inputs changed')
    launch = shutil.which('python3', path=env.get('PATH'))
    if not launch or Path(launch).absolute() != Path(worker['launchPath']) or Path(launch).resolve() != Path(worker['executable']):
        raise RuntimeError('mapping worker interpreter path changed')
    supervisor.verify_worker(worker); rescan.verify_model(inputs / 'model')
    result = json.loads((output / 'run/result.json').read_text())
    client_inputs = json.loads((output / 'run/inputs.json').read_text())
    for key in ('simulatorSHA256', 'caseSHA256', 'environmentSHA256', 'weightsSHA256', 'policySHA256', 'receiptSHA256'):
        if client_inputs[key] != manifest[key]:
            raise ValueError(f'client provenance mismatch: {key}')
    if (client_inputs['robotAssetSHA256'] != manifest['assetSHA256'] or client_inputs['stoppedRescanEnabled']
            or result['traceSHA256'] != sha(output / 'run/trace.jsonl')):
        raise ValueError('unexpected rescan option or trace hash mismatch')
    journal = [json.loads(line) for line in (output / 'run/physical-agent.jsonl').read_text().splitlines()]
    actor = check_actor_inputs(output / 'run', result, journal)
    action_ticks = [row['totalSteps'] for row in journal if row['ack'] == 1]
    actor['truthNavigation'] = truth_navigation_path(output / 'run/trace.jsonl', journal[0]['totalSteps'], action_ticks[-1])
    auditor = inputs / 'flex-source/exploration/manipulation_audit.py'
    completed = subprocess.run([sys.executable, '-I', str(auditor), str(inputs / 'case.json'), str(output / 'run/trace.jsonl')],
                               cwd=PROJECT, capture_output=True, text=True, timeout=60)
    (output / 'audit.log').write_text(completed.stderr)
    if completed.returncode:
        raise RuntimeError('trace audit failed; inspect retained audit.log')
    manipulation = json.loads(completed.stdout)
    if manipulation['caseSHA256'] != manifest['caseSHA256']:
        raise ValueError('audit case hash mismatch')
    if supervisor.source_hashes(inputs / 'flex-source') != sources:
        raise RuntimeError('archived source changed during audit')
    report = {'status': 'diagnostic_only', 'actor': actor, 'clientResult': result, 'manipulation': manipulation,
              'scope': 'one training-selection hybrid simulator case; heuristic collector, not real hardware or learned end-to-end fetch'}
    (output / 'audit.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true'); parser.add_argument('output', nargs='?')
    args = parser.parse_args()
    if args.check == bool(args.output): parser.error('choose --check or one new output directory')
    rescan.verify_model(MODEL)
    if args.check:
        with tempfile.TemporaryDirectory(prefix='puppy-hidden-build-') as tmp:
            inputs = Path(tmp); sources, libraries, compiler_hash = rescan.build_snapshot(inputs)
            print(json.dumps({'status': 'ready', 'simulatorSHA256': sha(inputs / 'simulator'),
                              'clientSHA256': sha(inputs / 'client'), 'compilerSHA256': compiler_hash,
                              'sourceFiles': len(sources), 'libraryFiles': len(libraries), 'wallSeconds': WALL_SECONDS,
                              'note': 'preflight only; no GPU run started'}, indent=2))
        return
    run_trial(Path(args.output).resolve())


if __name__ == '__main__':
    main()
