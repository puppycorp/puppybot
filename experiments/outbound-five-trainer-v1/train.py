#!/usr/bin/env python3
"""Pre-register and run one bounded outbound-prefix warm-start training job."""
import importlib.util
import json
import math
import os
import shutil
import struct
import sys
import types
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
MANIFEST = P / 'outbound-five-train-plan-v1.json'
MODEL = P / 'outbound-five-trained-v1'
PACKAGE = P / 'outbound-five-fixed-epoch1-v1'
GIB = 1024**3


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec); spec.loader.exec_module(obj)
    return obj


design = load('outbound_five_design', HERE / 'design.py')
builder = load('outbound_five_builder', HERE / 'build.py')
aggregate = load('outbound_five_aggregate', ROOT / 'experiments/outbound-five-aggregate-v1/build.py')
aggregate_supervisor = load('outbound_five_aggregate_supervisor', ROOT / 'experiments/outbound-five-aggregate-v1/supervise.py')
build_supervisor = load('outbound_five_trainer_supervisor', HERE / 'supervise-build.py')
prior = load('outbound_five_supervisor', ROOT / 'datasets/visual-control/chase-v1/levels/run-heading-training.py')
sha = builder.sha


def capacity(amount):
    if shutil.disk_usage(P).free < amount * GIB:
        raise ValueError('insufficient disk; preserve any partial outputs')


def no_existing(*paths):
    for path in paths:
        if path.exists() or path.is_symlink():
            raise FileExistsError(f'output already exists: {path}')


def write_new(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())


def loaded_sources(roots):
    """Collect local Python modules held by the current import graph."""
    pending = list(roots); seen = set(); result = set()
    while pending:
        module = pending.pop()
        if not isinstance(module, types.ModuleType) or id(module) in seen:
            continue
        seen.add(id(module))
        name = getattr(module, '__file__', None)
        if name:
            path = Path(name).resolve()
            if path.suffix == '.py' and path.is_relative_to(ROOT):
                result.add(path)
                pending.extend(v for v in vars(module).values() if isinstance(v, types.ModuleType))
    return sorted(result)


def dataset_supervision(report):
    """Require the separate low-priority worker and final byte/order recheck."""
    root = aggregate_supervisor.MONITOR
    result = json.loads((root / 'result.json').read_text())
    launch = json.loads((root / 'launch.json').read_text())
    worker = json.loads((root / 'worker-result.json').read_text())
    final = json.loads((root / 'final-result.json').read_text())
    status = json.loads((root / 'supervisor-result.json').read_text())
    final_status = json.loads((root / 'final-monitor/supervisor-result.json').read_text())
    invocation = json.loads((root / 'final-monitor/invocation.json').read_text())
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home())}
    if (result.get('status') != 'candidate_data_only' or result.get('reason') is not None or
            not aggregate_supervisor.base.clean(status) or not aggregate_supervisor.base.clean(final_status) or
            result.get('supervisorStatus') != status):
        raise ValueError('candidate dataset supervisor did not complete cleanly')
    links = {'launchSHA256': root / 'launch.json', 'workerSHA256': root / 'worker-result.json',
             'finalResultSHA256': root / 'final-result.json',
             'finalStatusSHA256': root / 'final-monitor/supervisor-result.json'}
    if any(result.get(key) != sha(path) for key, path in links.items()):
        raise ValueError('candidate dataset supervision hash differs')
    if (launch.get('command') != aggregate_supervisor.command() or launch.get('environment') != env or
            launch.get('wallSeconds') != aggregate_supervisor.WALL_SECONDS or
            launch.get('output') != str(design.AGGREGATE) or launch.get('sourcePins') != aggregate_supervisor.pins() or
            worker.get('sourcePins') != launch.get('sourcePins')):
        raise ValueError('candidate dataset launch or source pins differ')
    if invocation != {'command': aggregate_supervisor.final_command(), 'environment': env,
                      'wallSeconds': aggregate_supervisor.WALL_SECONDS}:
        raise ValueError('candidate dataset final invocation differs')
    if (worker.get('status') != 'candidate_data_only' or worker.get('cpuNice', -1) < 15 or
            worker.get('ioClass') != 'idle' or worker.get('reportSHA256') != sha(design.AGGREGATE / 'report.json') or
            worker.get('dataSHA256') != report['dataSHA256'] or worker.get('mapSHA256') != report['mapSHA256'] or
            final.get('status') != 'candidate_bytes_verified' or final.get('cpuNice', -1) < 15 or
            final.get('ioClass') != 'idle' or final.get('reportSHA256') != worker.get('reportSHA256') or
            final.get('verification') != report.get('verification')):
        raise ValueError('candidate dataset worker or final verification differs')
    return {str(path): sha(path) for path in (root / 'result.json', root / 'launch.json', root / 'worker-result.json',
            root / 'supervisor-result.json', root / 'final-result.json', root / 'final-monitor/invocation.json',
            root / 'final-monitor/supervisor-result.json')}


def build_supervision(built):
    """Bind the separately supervised, lock-serialized private CPU build."""
    root = build_supervisor.MONITOR
    result = json.loads((root / 'result.json').read_text())
    launch = json.loads((root / 'launch.json').read_text())
    worker = json.loads((root / 'worker-result.json').read_text())
    status = json.loads((root / 'supervisor-result.json').read_text())
    if (result.get('status') != 'isolated_build_only' or result.get('reason') is not None or
            not build_supervisor.base.clean(status) or result.get('supervisorStatus') != status):
        raise ValueError('private trainer CPU build was not clean')
    if (result.get('launchSHA256') != sha(root / 'launch.json') or
            result.get('workerSHA256') != sha(root / 'worker-result.json') or
            result.get('buildSHA256') != sha(design.TRAINER / 'build.json')):
        raise ValueError('private trainer CPU build evidence hash differs')
    if (launch.get('command') != build_supervisor.command() or
            launch.get('environment') != {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home())} or
            launch.get('wallSeconds') != 900 or launch.get('sourcePins') != build_supervisor.source_pins() or
            worker.get('sourcePins') != launch.get('sourcePins')):
        raise ValueError('private trainer CPU build invocation or sources differ')
    if (worker.get('status') != 'isolated_build_only' or worker.get('cpuNice', -1) < 15 or
            worker.get('ioClass') != 'idle' or worker.get('buildSHA256') != result.get('buildSHA256') or
            worker.get('binaries') != built['binaries']):
        raise ValueError('private trainer CPU build worker differs')
    return {str(path): sha(path) for path in (root / 'result.json', root / 'launch.json',
            root / 'worker-result.json', root / 'supervisor-result.json')}


def inputs():
    """Re-audit exact source episodes and their resulting positions in the aggregate."""
    built = builder.verify()
    supervised_build = build_supervision(built)
    report_path = design.AGGREGATE / 'report.json'
    report = json.loads(report_path.read_text())
    if (report.get('schema') != 'puppybot.outbound-five-aggregate.v1' or
            report.get('status') != 'candidate_data_only' or report.get('trainingAuthorized') is not False):
        raise ValueError('dataset candidate receipt missing or invalid')
    if report.get('dataSHA256') != design.DATA_SHA256 or report.get('mapSHA256') != design.MAP_SHA256:
        raise ValueError('dataset receipt differs from the fixed candidate hashes')
    sources, selected, completion, frozen = aggregate.source_checks()
    supervised = dataset_supervision(report)
    if selected != design.SELECTED or sources != report.get('sourceFiles'):
        raise ValueError('dataset source qualification changed')
    expected_rows = [{'episode': index, 'seed': 6910000 + index, 'firstConsumptionAction': cutoff,
                      'destinationEpisode': 928 + i} for i, (index, cutoff) in enumerate(selected)]
    if report.get('selectedTeacherEpisodes') != expected_rows:
        raise ValueError('selected teacher order differs')
    if sha(aggregate.MONITOR / 'completion.json') != report.get('pilotCompletionSHA256'):
        raise ValueError('pilot completion differs')
    expected = aggregate.verify.verify(aggregate.BASE / 'data.bin', aggregate.BASE / 'map.bin',
        aggregate.PILOT / 'teacher/data.bin', aggregate.PILOT / 'teacher/map.bin',
        design.AGGREGATE / 'data.bin', design.AGGREGATE / 'map.bin', selected)
    if report.get('verification') != expected:
        raise ValueError('dataset byte/order verification differs')
    for key, name in (('dataSHA256', 'data.bin'), ('mapSHA256', 'map.bin')):
        path = design.AGGREGATE / name
        if path.is_symlink() or sha(path) != report.get(key):
            raise ValueError(f'candidate dataset differs: {name}')
    baseline = design.parent_receipt()
    if (baseline.get('dataSHA256') != sources[str(aggregate.BASE / 'data.bin')] or
            baseline.get('memoryMapTargetsSHA256') != sources[str(aggregate.BASE / 'map.bin')]):
        raise ValueError('baseline aggregate is not parent provenance')
    if (sha(ROOT / 'build/flex/control/policy-categorical') != baseline['binarySHA256'] or
            sha(ROOT / 'flex/control/model-categorical.pup') != baseline['graphSHA256']):
        raise ValueError('current inference runtime differs from parent')
    for name, checksum in baseline['kernels'].items():
        if sha(ROOT / 'build/flex/control/kernels' / name) != checksum:
            raise ValueError('current inference kernel differs from parent')
    spec = design.design()
    data_files = [HERE / 'train.py', HERE / 'monitor.py', HERE / 'design.py', HERE / 'build.py',
                  design.AGGREGATE / 'report.json', design.AGGREGATE / 'data.bin', design.AGGREGATE / 'map.bin',
                  design.TRAINER / 'build.json', design.TRAINER / 'control', design.TRAINER / 'trainer',
                  design.PARENT / 'receipt.json', design.PARENT / 'weights.bin', design.PARENT / 'policy',
                  design.PARENT / 'model.pup', ROOT / 'build/flex/control/policy-categorical',
                  ROOT / 'flex/control/model-categorical.pup', ROOT / 'build/flex/pixel-control-categorical-model.flex',
                  ROOT / 'build/flex/rocm-runtime/libamdhip64.so', ROOT / 'build/flex/control/control',
                  ROOT / 'build/flex/control/simulator', ROOT / 'build/flex/sim/puppybot.bin',
                  ROOT / 'datasets/visual-control/chase-v1/evaluate.sh',
                  ROOT / 'experiments/final-loop-window-v1/audit.py',
                  ROOT / 'datasets/visual-control/chase-v1/levels/heading-selection-metrics.py',
                  ROOT / 'datasets/visual-control/chase-v1/levels/audit-selection.py',
                  ROOT / 'datasets/visual-control/chase-v1/levels/goal-report.py',
                  ROOT / 'experiments/heading-teacher-audit/audit.py',
                  ROOT / 'experiments/fresh-policy-catalog-monitor-v1/adapter.py',
                  ROOT / 'flex/tests/monitored-heading-full-training.py',
                  ROOT / 'flex/tests/monitored-visual-v4-smoke.py',
                  ROOT / 'flex/tests/run-physical-hidden-trial.py', Path(sys.executable)]
    data_files += sorted((ROOT / 'build/flex/control/kernels').glob('*'))
    data_files += sorted((design.PARENT / 'kernels').glob('*'))
    monitor = load('outbound_five_source_graph', HERE / 'monitor.py')
    data_files += loaded_sources((monitor, aggregate, aggregate_supervisor, build_supervisor, prior, builder, design))
    if any(not p.is_file() for p in data_files):
        raise ValueError('training or evaluation input is missing')
    pins = {str(p): sha(p) for p in data_files}
    return {'design': spec, 'datasetReport': report, 'datasetVerification': expected,
            'trainerBuildSHA256': sha(design.TRAINER / 'build.json'), 'sources': sources,
            'datasetSupervision': supervised, 'buildSupervision': supervised_build,
            'pilotCompletion': completion, 'pilotFrozenSHA256': hashlib_json(frozen),
            'files': pins, 'selectionScope': 'training-family only; historical selection monitor failed',
            'scope': 'local hashes and receipts, not execution or complete ancestry attestation'}


def hashlib_json(value):
    import hashlib
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def command():
    return [str(design.TRAINER / 'control'), 'train', '--output', str(MODEL), '--seed', '7120000',
            '--learning-rate-micros', '100', '--data', str(design.AGGREGATE / 'data.bin'),
            '--memory-map', str(design.AGGREGATE / 'map.bin'), '--transition-weight-one',
            '--policy', str(design.PARENT), '--categorical', '--mirror-augment', '--carry-cue',
            '--epochs', '1', '--batch', '2', '--checkpoint-every', '1']


def environment():
    return {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'PUPPYBOT_PROJECT': str(ROOT),
            'LD_LIBRARY_PATH': str(ROOT / 'build/flex/rocm-runtime'), 'SDL_VIDEODRIVER': 'offscreen'}


def freeze():
    capacity(36); no_existing(MANIFEST, MODEL, PACKAGE, P / 'outbound-five-train-worker-v1',
                              P / 'outbound-five-training-monitored-v1')
    frozen = {'schema': 'puppybot.outbound-five-train-plan.v1', 'inputs': inputs(),
              'command': command(), 'environment': environment(), 'wallSeconds': 3600,
              'optimizer': 'fresh Adam moments and step counter; parent weights only',
              'trainingAuthorized': False, 'scope': 'preregistration only, no training or promotion'}
    capacity(36); write_new(MANIFEST, frozen)
    return frozen


def verify_manifest():
    frozen = json.loads(MANIFEST.read_text())
    expected = {'schema': 'puppybot.outbound-five-train-plan.v1', 'inputs': inputs(),
                'command': command(), 'environment': environment(), 'wallSeconds': 3600,
                'optimizer': 'fresh Adam moments and step counter; parent weights only',
                'trainingAuthorized': False, 'scope': 'preregistration only, no training or promotion'}
    if frozen != expected:
        raise ValueError('registered training plan changed')
    return frozen


def verify_model():
    receipt = json.loads((MODEL / 'receipt.json').read_text()); parent = design.parent_receipt()
    expected = {'initialWeightsSHA256': parent['weightsSHA256'], 'dataSHA256': sha(design.AGGREGATE / 'data.bin'),
                'memoryMapTargetsSHA256': sha(design.AGGREGATE / 'map.bin'), 'epochs': 1, 'batch': 2,
                'learningRateMicros': 100, 'seed': 7120000, 'checkpointEveryEpochs': 1,
                'sequenceMirrorAugmentation': True, 'carryCue': True, 'speedTransitionLossWeight': 1,
                'stopLossWeight': 5, 'actionCodec': 'joint-seven-v1', 'memoryWidth': 128,
                'phaseSupervisionFromValidFrames': False, 'taskFeedback': False,
                'trainingRuntime': 'Flexscript/Pup HIP (RDNA)'}
    for key, value in expected.items():
        actual = receipt.get(key)
        if (actual is not value if isinstance(value, bool) else actual != value):
            raise ValueError(f'model training receipt differs: {key}')
    if (MODEL / 'backend.txt').read_bytes() != b'hip':
        raise ValueError('training backend is not HIP')
    for key, name in (('weightsSHA256', 'weights.bin'), ('binarySHA256', 'policy'), ('graphSHA256', 'model.pup')):
        if sha(MODEL / name) != receipt.get(key): raise ValueError(f'model artifact changed: {name}')
    if receipt['binarySHA256'] != parent['binarySHA256'] or receipt['graphSHA256'] != parent['graphSHA256']:
        raise ValueError('published inference runtime differs from parent')
    kernels = receipt.get('kernels')
    if not isinstance(kernels, dict) or len(kernels) < 5:
        raise ValueError('model kernel receipt missing')
    for name, checksum in kernels.items():
        if Path(name).name != name or sha(MODEL / 'kernels' / name) != checksum:
            raise ValueError('model kernel differs')
    if kernels != parent['kernels']:
        raise ValueError('published kernel set differs from parent')
    if sha(MODEL / 'data.bin') != expected['dataSHA256']:
        raise ValueError('training copy differs from data input')
    if sha(MODEL / 'seed.bin') != parent['weightsSHA256'] or sha(MODEL / 'initial.bin') != parent['weightsSHA256']:
        raise ValueError('trainer did not start at the registered parent weights')
    curve = [json.loads(line) for line in (MODEL / 'curves.jsonl').read_text().splitlines()]
    if ([r.get('epoch') for r in curve] != [0, 1] or curve[-1].get('optimizerSteps') != 467 or
            any(not math.isfinite(r[k]) for r in curve for k in ('trainingLoss', 'validationLoss'))):
        raise ValueError('training did not finish the fixed epoch')
    first = (MODEL / 'first-order.bin').read_bytes(); final_order = (MODEL / 'final-order.bin').read_bytes()
    if len(first) != 1029 * 8 or first != final_order:
        raise ValueError('saved training orders missing or different')
    order = struct.unpack('<1029Q', first)
    if set(order[:933]) != set(range(933)) or order[933:] != tuple(range(933, 1029)):
        raise ValueError('saved training order is not the registered fit/validation split')
    mirror = (MODEL / 'first-mirror-mask.bin').read_bytes()
    if len(mirror) != 8 or struct.unpack('<Q', mirror)[0] > 3:
        raise ValueError('invalid first batch mirror mask')
    epoch = MODEL / 'epoch-1.bin'
    if sha(epoch) != sha(MODEL / 'last.bin'):
        raise ValueError('fixed checkpoint differs from final checkpoint')
    with epoch.open('rb') as stream: header = stream.read(32)
    with (MODEL / 'initial.bin').open('rb') as stream: initial = stream.read(32)
    if header[:8] != b'PUPV0001' or initial[:8] != b'PUPV0001' or header[8:16] != initial[8:16]:
        raise ValueError('unexpected checkpoint structure')
    count = int.from_bytes(header[8:16], 'little')
    table_end = 32 + count * 256
    if not 0 < count <= 4096 or epoch.stat().st_size != (MODEL / 'initial.bin').stat().st_size:
        raise ValueError('checkpoint dimensions differ')
    with epoch.open('rb') as actual, (MODEL / 'initial.bin').open('rb') as baseline:
        if actual.read(table_end) != baseline.read(table_end):
            raise ValueError('checkpoint tensor description changed')
    return receipt


def package_fixed_epoch():
    no_existing(PACKAGE); receipt = verify_model(); fixed = MODEL / 'epoch-1.bin'
    PACKAGE.mkdir(); (PACKAGE / 'kernels').mkdir()
    shutil.copyfile(fixed, PACKAGE / 'weights.bin')
    for name in ('policy', 'model.pup', 'factory.flex'):
        shutil.copyfile(MODEL / name, PACKAGE / name)
    for name in receipt['kernels']:
        shutil.copyfile(MODEL / 'kernels' / name, PACKAGE / 'kernels' / name)
    shutil.copyfile(MODEL / 'receipt.json', PACKAGE / 'training-receipt.json')
    derived = dict(receipt)
    derived.update({'checkpointSourceWeightsSHA256': receipt['weightsSHA256'],
                    'weightsSHA256': sha(fixed), 'checkpointSHA256': sha(fixed),
                    'checkpointEpoch': 1, 'checkpointSelection': 'fixed epoch, not validation selected',
                    'sourceTrainingReceiptSHA256': sha(MODEL / 'receipt.json')})
    write_new(PACKAGE / 'receipt.json', derived)
    for path in PACKAGE.rglob('*'):
        if path.is_file(): path.chmod(0o555 if path.name == 'policy' else 0o444)
    (PACKAGE / 'kernels').chmod(0o555); PACKAGE.chmod(0o555)
    result = {'weightsSHA256': sha(PACKAGE / 'weights.bin'), 'trainingReceiptSHA256': sha(MODEL / 'receipt.json'),
            'checkpointRule': 'fixed epoch-1; not validation-selected',
            'scope': 'derived inference package; no selection or promotion'}
    if verify_package() != result:
        raise ValueError('fixed checkpoint package differs after creation')
    return result


def verify_package():
    receipt = verify_model(); fixed = MODEL / 'epoch-1.bin'
    if PACKAGE.is_symlink() or PACKAGE.stat().st_mode & 0o222:
        raise ValueError('package root must be read-only')
    expected_names = {'weights.bin', 'policy', 'model.pup', 'factory.flex', 'receipt.json', 'training-receipt.json', 'kernels'}
    if {p.name for p in PACKAGE.iterdir()} != expected_names:
        raise ValueError('unexpected fixed-epoch package files')
    derived = dict(receipt)
    derived.update({'checkpointSourceWeightsSHA256': receipt['weightsSHA256'],
                    'weightsSHA256': sha(fixed), 'checkpointSHA256': sha(fixed),
                    'checkpointEpoch': 1, 'checkpointSelection': 'fixed epoch, not validation selected',
                    'sourceTrainingReceiptSHA256': sha(MODEL / 'receipt.json')})
    if (json.loads((PACKAGE / 'receipt.json').read_text()) != derived or
            (PACKAGE / 'training-receipt.json').read_bytes() != (MODEL / 'receipt.json').read_bytes() or
            sha(PACKAGE / 'weights.bin') != sha(fixed)):
        raise ValueError('fixed-epoch receipt or weights differ')
    for name in ('policy', 'model.pup', 'factory.flex'):
        if sha(PACKAGE / name) != sha(MODEL / name):
            raise ValueError('fixed-epoch runtime differs')
    if {p.name for p in (PACKAGE / 'kernels').iterdir()} != set(receipt['kernels']):
        raise ValueError('fixed-epoch kernel set differs')
    for name, checksum in receipt['kernels'].items():
        if sha(PACKAGE / 'kernels' / name) != checksum:
            raise ValueError('fixed-epoch kernel differs')
    for path in PACKAGE.rglob('*'):
        if path.is_symlink() or path.stat().st_mode & 0o222:
            raise ValueError('fixed-epoch package contains writable or linked entries')
    if not os.access(PACKAGE / 'policy', os.X_OK):
        raise ValueError('fixed-epoch policy is not executable')
    return {'weightsSHA256': sha(PACKAGE / 'weights.bin'), 'trainingReceiptSHA256': sha(MODEL / 'receipt.json'),
            'checkpointRule': 'fixed epoch-1; not validation-selected',
            'scope': 'derived inference package; no selection or promotion'}


def run():
    """Call only from the reviewed bounded monitor in a dedicated process."""
    with prior.base.acquire_lock(P / '.l4-matched.lock'):
        capacity(34); no_existing(MODEL, PACKAGE)
        frozen = verify_manifest(); pin = sha(MANIFEST)
        supervisor = P / 'outbound-five-train-worker-v1'; no_existing(supervisor); supervisor.mkdir()
        write_new(supervisor / 'invocation.json', {'argv': command(), 'environment': environment(), 'wallSeconds': 3600})
        status = prior.base.hidden.supervise(command(), supervisor, environment(), 3600)
        prior.base.require_success(status, supervisor)
        if json.loads((supervisor / 'supervisor-result.json').read_text()) != status:
            raise ValueError('training supervisor evidence differs')
        capacity(34)
        if verify_manifest() != frozen or sha(MANIFEST) != pin:
            raise ValueError('training inputs changed')
        packaged = package_fixed_epoch()
        if verify_manifest() != frozen or sha(MANIFEST) != pin:
            raise ValueError('training inputs changed during packaging')
        capacity(32)
        result = {'status': 'training_diagnostic_only', 'planSHA256': pin,
                  'supervisorStatusSHA256': sha(supervisor / 'supervisor-result.json'),
                  'trainingReceiptSHA256': sha(MODEL / 'receipt.json'), 'package': packaged,
                  'scope': 'one fixed warm-start; no independent selection, held-out, promotion or physical claim'}
        write_new(supervisor / 'result.json', result)
        return result


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and monitored scheduling.')
