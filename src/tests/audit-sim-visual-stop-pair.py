#!/usr/bin/env python3
"""Audit a paired, bounded simulated visual-stop diagnostic after both runs.

Usage: audit-sim-visual-stop-pair.py PILOT_DIRECTORY
Simulator pose appears only here, after the actor/controller processes stop.
"""
import importlib.util
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('stop_audit', ROOT / 'flex/tests/audit-sim-visual-stop.py')
stop_audit = importlib.util.module_from_spec(spec); spec.loader.exec_module(stop_audit)


def load_hidden_auditor():
    spec = importlib.util.spec_from_file_location('hidden_audit', ROOT / 'flex/tests/run-physical-hidden-trial.py')
    hidden = importlib.util.module_from_spec(spec); spec.loader.exec_module(hidden)
    return hidden


def poses_in_window(path, start, end):
    poses = {}
    with path.open() as stream:
        for line in stream:
            row = json.loads(line); tick = row['totalSteps']; pose = row['pose']
            if (type(tick) is not int or tick < 0 or tick in poses or not isinstance(pose, list) or len(pose) != 3
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in pose)):
                raise ValueError('invalid simulator truth pose or tick')
            poses[tick] = pose
    try:
        segment = [poses[t] for t in range(start, end + 1)]
    except KeyError as error:
        raise ValueError('simulator trace misses a detector-window tick') from error
    first = segment[0]
    travel = max(math.dist(first[:2], p[:2]) for p in segment)
    turn = max(abs((p[2]-first[2]+math.pi) % (2*math.pi)-math.pi) for p in segment)
    return {'maximumDisplacementM': travel, 'maximumHeadingChangeRad': turn,
            'withinOneCmAndTwoDegrees': travel < .01 and turn < math.radians(2)}


def audit(root):
    root = Path(root).absolute(); manifest = json.loads((root / 'inputs.json').read_text())
    if manifest.get('schema') != 'puppybot.sim-visual-stop-pair.v1':
        raise ValueError('invalid pair manifest')
    files = manifest.get('files'); paths = manifest.get('paths')
    if not isinstance(files, dict) or not isinstance(paths, dict):
        raise ValueError('missing pinned pair inputs')
    for key in ('client', 'simulator', 'case', 'environment', 'asset', 'model', 'config', 'runtime'):
        if not isinstance(paths.get(key), str) or not Path(paths[key]).is_absolute():
            raise ValueError('missing absolute pinned path: ' + key)
    model = Path(paths['model']); receipt = json.loads((model / 'receipt.json').read_text())
    kernels = receipt.get('kernels')
    if not isinstance(kernels, dict) or len(kernels) < 5 or any(not isinstance(k, str) or Path(k).name != k for k in kernels):
        raise ValueError('invalid model kernel receipt')
    required = [paths[k] for k in ('client', 'simulator', 'case', 'environment', 'asset', 'config', 'runtime')]
    required += [str(model / name) for name in ('receipt.json', 'weights.bin', 'policy')]
    required += [str(model / 'kernels' / name) for name in kernels]
    if any(name not in files for name in required):
        raise ValueError('missing required pair input pin')
    if (manifest.get('navigationLimit') != 90 or manifest.get('wallSecondsPerArm') != 300
            or files[str(model/'weights.bin')] != receipt.get('weightsSHA256')
            or files[str(model/'policy')] != receipt.get('binarySHA256')
            or any(files[str(model/'kernels'/name)] != value for name, value in kernels.items())):
        raise ValueError('model receipt or fixed limits differ')
    for name, digest in files.items():
        if not Path(name).is_absolute() or not isinstance(digest, str) or len(digest) != 64 or stop_audit.sha(Path(name)) != digest:
            raise ValueError('pair input changed: ' + name)
    runs = {}; environments = {}
    for arm in ('disabled', 'enabled'):
        base = root / arm; run = base / 'run'
        status = json.loads((base / 'monitor/supervisor-result.json').read_text())
        if status.get('clientExit') != 0 or status.get('timedOut') is not False or status.get('signal') is not None or status.get('remainingWorkersTerminated') is not False:
            raise ValueError(arm + ' run failed or required cleanup')
        command = json.loads((base / 'command.json').read_text())
        expected = [paths['client'], paths['simulator'], paths['model'], paths['case'], paths['environment'], str(run), '--allow-zero-contact']
        if command != expected: raise ValueError(arm + ' command differs from pinned inputs')
        env = json.loads((base / 'environment.json').read_text()); environments[arm] = env
        if not isinstance(env, dict) or env.get('PUPPYBOT_SIM_VISUAL_STOP') != ('1' if arm == 'enabled' else '0') or env.get('PUPPYBOT_PHYSICAL_NAV_LIMIT') != '90' or env.get('PUPPYBOT_PHYSICAL_POLL_LIMIT') != '1499' or env.get('SDL_VIDEODRIVER') != 'offscreen':
            raise ValueError(arm + ' environment differs from fixed experiment')
        result = json.loads((run / 'result.json').read_text()); inputs = json.loads((run / 'inputs.json').read_text())
        if result.get('visualStopEnabled') is not (arm == 'enabled') or result.get('stopCommandAcknowledged') is not True or result.get('handoff') is not False or result.get('traceSHA256') != stop_audit.sha(run / 'trace.jsonl'):
            raise ValueError(arm + ' invalid or incomplete simulation result')
        if result.get('stoppedRescanEnabled') is not False:
            raise ValueError('unexpected second recovery mode')
        runs[arm] = (run, result, inputs)
    left_env = dict(environments['disabled']); right_env = dict(environments['enabled'])
    left_env.pop('PUPPYBOT_SIM_VISUAL_STOP'); right_env.pop('PUPPYBOT_SIM_VISUAL_STOP')
    if left_env != right_env: raise ValueError('paired environments differ beyond the opt-in flag')
    a, ar, ai = runs['disabled']; b, br, bi = runs['enabled']
    expected_hashes = {'simulatorSHA256': files[paths['simulator']], 'caseSHA256': files[paths['case']],
                       'environmentSHA256': files[paths['environment']], 'weightsSHA256': files[str(model/'weights.bin')],
                       'policySHA256': files[str(model/'policy')], 'receiptSHA256': files[str(model/'receipt.json')],
                       'robotAssetSHA256': files[paths['asset']]}
    if any(ai.get(k) != v or bi.get(k) != v for k, v in expected_hashes.items()):
        raise ValueError('client declarations do not match pinned bytes')
    keys = ('simulatorSHA256','caseSHA256','environmentSHA256','weightsSHA256','policySHA256','receiptSHA256','robotAssetSHA256','cameraPitch','contactFeedback')
    if any(ai.get(k) is None or ai.get(k) != bi.get(k) for k in keys):
        raise ValueError('paired simulator/model/scene inputs differ')
    if br.get('visualStopReason') not in (2,3):
        raise ValueError('no visual stop was reported; retain run for inspection')
    checked = stop_audit.audit(b)
    if type(ar.get('policyActions')) is not int or type(br.get('policyActions')) is not int or ar['policyActions'] < br['policyActions'] or br['policyActions'] < 9:
        raise ValueError('baseline does not cover the enabled action prefix')
    hidden = load_hidden_auditor()
    with (a / 'physical-agent.jsonl').open() as stream: baseline_rows = [json.loads(line) for line in stream]
    with (b / 'physical-agent.jsonl').open() as stream: enabled_rows = [json.loads(line) for line in stream]
    hidden.check_actor_inputs(a, ar, baseline_rows)
    common = br['policyActions']; differences = []
    if baseline_rows[:common+1] != enabled_rows[:common+1]:
        differences.append('observation prefix differs')
    for seq in range(1, common+1):
        for extension in ('rgb', 'feedback', 'hidden', 'action'):
            name = f'actor-{seq}.{extension}'
            if (a/'actors'/name).read_bytes() != (b/'actors'/name).read_bytes():
                differences.append(name)
    truth = poses_in_window(b/'trace.jsonl', checked['startTick'], checked['endTick'])
    return {'status': 'diagnostic_only', 'comparedActorSteps': common, 'commonActorBytesMatch': not differences,
            'actorByteDifferences': differences, 'visualStop': checked, 'simulatorTruthAfterRun': truth,
            'baselinePolicyActions': ar['policyActions'], 'enabledPolicyActions': br['policyActions'],
            'scope': 'one paired simulator selection case; pose is used only after the run; an acknowledged simulated stop is not a physical-hardware safety result'}


if __name__ == '__main__':
    if len(sys.argv) != 2: raise SystemExit(__doc__)
    try: print(json.dumps(audit(Path(sys.argv[1])), sort_keys=True))
    except (OSError, KeyError, ValueError, TypeError) as error: raise SystemExit(f'Invalid simulated visual-stop pair: {error}')
