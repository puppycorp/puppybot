#!/usr/bin/env python3
"""Package the heading pair and freeze its matched selection plan.

Usage: heading-epoch8-selection.py package|plan|verify

Preparation only: this script never evaluates a policy. Both outputs are new,
and the shared pitch82 lock is held throughout. The recorded selection scenes
are training layouts, not an independent held-out set.
The generic epoch-8 packager's CLI takes a different lock for nested heading
models; call its library only through this wrapper.
"""
import importlib.util
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[4]
S = PROJECT / 'datasets/visual-control/chase-v1/levels'
P = PROJECT / 'build/flex/sim/levels-v2/pitch82'
OUTPUT = P / 'search-dagger-heading'
MODELS = OUTPUT / 'models'
PACKAGE = MODELS / 'heading-epoch8-pair'
PLAN = MODELS / 'heading-epoch8-selection-plan.json'
SELECTION_ROOT = OUTPUT / 'selection-epoch8'
LOCK = P / '.l4-matched.lock'
SCENES = PROJECT / 'build/flex/sim/expanded-rooms-v1/scenes'
SEED = 7800000
GAMES = 32


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


training = load('heading_training', S / 'run-heading-training.py')
package = load('epoch8_package', S / 'package-matched-epoch8.py')
training_receipt = load('full_training_receipt', S / 'heading-full-training-receipt.py')
base = training.base


def selection_design():
    tasks = []
    for level in range(6):
        two_room = level >= 4
        rows = []
        for index in range(GAMES):
            layout = 13 + 2 * (index % 3) if two_room else 12 + index % 6
            variant = index % 16
            rows.append({'index': index, 'seed': SEED + index, 'layout': layout,
                         'variant': variant, 'scene': str(SCENES / str(layout) / str(variant))})
        tasks.append({'name': 'standard' if level == 0 else f'L{level}', 'level': level,
                      'levelArgs': [] if level == 0 else ['--level', str(level)],
                      'twoRoom': two_room, 'horizon': 300, 'gamesPerArm': GAMES, 'rows': rows})
    return tasks


def clean_status(path):
    status = json.loads(path.read_text())
    if (type(status.get('clientExit')) is not int or status['clientExit'] != 0 or
            'signal' not in status or status['signal'] is not None or status.get('timedOut') is not False or
            status.get('remainingWorkersTerminated') is not False or
            type(status.get('processGroup')) is not int or status['processGroup'] <= 0):
        raise ValueError(f'unclean full-training supervisor: {path}')


def verify_training():
    """Recheck current training and input artifacts; not execution attestation."""
    training_receipt.verify()
    training.collection_receipt.verify()
    build = json.loads((training.builder.BUILD / 'inputs.json').read_text())
    training.builder.verify(training.builder.BUILD, build)
    training.small.verify_small_pilot()
    paired = training.builder.verify_ready()
    training.resource.verify_ready(paired)
    report = json.loads((MODELS / 'training-report.json').read_text())
    if report.get('status') != 'training_diagnostic_only':
        raise ValueError('completed matched training report required')
    if training.sources() != json.loads((MODELS / 'inputs.json').read_text()):
        raise ValueError('full-training inputs changed')
    if (report.get('pairReadySHA256') != base.sha(OUTPUT / 'pair-ready.json') or
            report.get('smallPilotSHA256') != base.sha(training.small.RESULT / 'comparison.json')):
        raise ValueError('training report provenance differs')
    parent = base.sha(training.small.PARENT / 'weights.bin')
    for arm in ('control', 'treatment'):
        data = OUTPUT / f'aggregate-{arm}'
        model = MODELS / f'{arm}-s0'
        clean_status(MODELS / f'monitor-{arm}' / 'supervisor-result.json')
        training.verify_full_receipt(model, base.sha(data / 'data.bin'), base.sha(data / 'map.bin'), parent)
        expected = {'weightsSHA256': base.sha(model / 'weights.bin'),
                    'receiptSHA256': base.sha(model / 'receipt.json'),
                    'dataExtents': training.small.extent_numbers(model / 'data.bin')}
        if report.get('arms', {}).get(arm) != expected:
            raise ValueError(f'full-training report differs: {arm}')
        package.source_info(model)
    matched = base.training.audit(training.small.PARENT, MODELS / 'control-s0', MODELS / 'treatment-s0')
    if report.get('matchedArtifacts') != matched or training.builder.verify_ready() != paired:
        raise ValueError('matched training or paired input audit differs')
    training.resource.verify_ready(paired)
    training.collection_receipt.verify()
    training_receipt.verify()
    return {'trainingReportSHA256': base.sha(MODELS / 'training-report.json'),
            'monitoredTrainingSHA256': base.sha(training_receipt.MONITORED / 'completion.json'),
            'collectionReceiptSHA256': base.sha(training.collection_receipt.MONITORED / 'completion.json'),
            'pairReadySHA256': base.sha(OUTPUT / 'pair-ready.json')}


def plan_inputs(tasks):
    files = [Path(__file__), S / 'package-matched-epoch8.py', S / 'audit-selection.py',
             S / 'heading-selection-audit.py', S / 'heading-selection-runner-audit.py',
             S / 'heading-selection-metrics.py', S / 'search-loops-odometry.py',
             S / 'run-heading-selection-v1.py', S / 'heading-selection-receipt.py',
             S / 'heading-full-training-receipt.py', PROJECT / 'flex/tests/monitored-heading-full-training.py',
             PROJECT / 'flex/tests/monitored-heading-selection.py', S / 'qualify-selection.py', S / 'audit-heldout.py',
             PROJECT / 'datasets/visual-control/chase-v1/evaluate.sh',
             PROJECT / 'build/flex/control/control', PROJECT / 'build/flex/control/simulator',
             PROJECT / 'build/flex/rocm-runtime/libamdhip64.so', PROJECT / 'build/flex/sim/puppybot.bin',
             PROJECT / 'puppybot.json', PACKAGE / 'manifest.json']
    for arm in ('control', 'treatment'):
        model = PACKAGE / arm
        files.extend(model / name for name in ('weights.bin', 'policy', 'receipt.json', 'training-receipt.json'))
        files.extend(sorted((model / 'kernels').iterdir()))
    for task in tasks:
        for row in task['rows']:
            scene = Path(row['scene'])
            layout = json.loads((scene / 'layout.json').read_text())
            if (layout.get('layoutId') != row['layout'] or layout.get('fit') is not True or
                    layout.get('startRoom') != 0 or layout.get('reservedHeldOut') is True):
                raise ValueError(f'scene is not an authorized training layout: {scene}')
            files.extend(scene / name for name in ('case.json', 'environment.bin', 'layout.json'))
    return {str(path): base.sha(path) for path in sorted(set(files))}


def make_plan(provenance):
    package.verify(MODELS / 'control-s0', MODELS / 'treatment-s0', PACKAGE)
    tasks = selection_design()
    return {'schema': 'puppybot.heading-fixed-selection-plan.v1', 'status': 'selection_plan_only',
            'arms': {arm: str(PACKAGE / arm) for arm in ('control', 'treatment')},
            'selectionRoot': str(SELECTION_ROOT),
            'training': provenance, 'tasks': tasks, 'files': plan_inputs(tasks),
            'execution': {'selectionSeed': SEED, 'parts': 4, 'horizon': 300, 'cameraPitchDegrees': 82,
                          'fullRecording': False, 'fetch': True,
                          'pairing': 'same seed, scene, start and brick placement; compare both fixed epoch-8 arms',
                          'audit': 'heading-selection-audit.py; strict paired trace and score checks for all six tasks'},
            'scope': 'training-layout comparison plan only; no teacher arm; camera/config/invocation require a separately reviewed executor; no preregistered winner or promotion rule, no held-out qualification; GPU runtime and actor inputs are not independently attested; source ancestry is incomplete'}


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ('package', 'plan', 'verify'):
        raise SystemExit(__doc__)
    with base.acquire_lock(LOCK):
        provenance = verify_training()
        mode = sys.argv[1]
        if mode == 'package':
            package.create(MODELS / 'control-s0', MODELS / 'treatment-s0', PACKAGE)
            if verify_training() != provenance:
                raise ValueError('training provenance changed while packaging')
            package.verify(MODELS / 'control-s0', MODELS / 'treatment-s0', PACKAGE)
            print(json.dumps({'status': 'fixed_epoch_package_only', 'package': str(PACKAGE)}))
        elif mode == 'plan':
            if PLAN.exists() or PLAN.is_symlink():
                raise ValueError('selection plan already exists; retain it')
            if SELECTION_ROOT.exists() or SELECTION_ROOT.is_symlink():
                raise ValueError('selection output exists; cannot register a plan after play')
            plan = make_plan(provenance)
            if verify_training() != provenance or make_plan(provenance) != plan:
                raise ValueError('training provenance or selection inputs changed while planning')
            training.builder.pair.publish_new(PLAN, plan)
            print(json.dumps({'status': plan['status'], 'tasks': len(plan['tasks']), 'plan': str(PLAN)}))
        else:
            plan = json.loads(PLAN.read_text())
            if plan != make_plan(provenance):
                raise ValueError('selection plan or registered inputs changed')
            print(json.dumps({'status': 'selection_plan_verified', 'tasks': len(plan['tasks'])}))


if __name__ == '__main__': main()
