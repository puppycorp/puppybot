#!/usr/bin/env python3
"""Prepare six private fault-injected simulator builds; never launches them."""
import hashlib
import importlib.util
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = ROOT / 'build/flex/sim/levels-v2/pitch82'
REFERENCE = BASE / 'physical-hybrid-refine-final-29980'
COMPILER = ROOT / 'build/flex/control/compiler'
INPUTS = {
    'case': BASE / 'physical-hybrid-visible-trial/case.json',
    'environment': ROOT / 'build/flex/sim/environments/apartment/apartment.bin',
    'robot': ROOT / 'build/flex/sim/puppybot.bin',
    'model': BASE / 'more1-s0/weights.bin',
    'policy': BASE / 'more1-s0/policy',
    'receipt': BASE / 'more1-s0/receipt.json',
    'client': Path('/tmp/puppybot-physical-client'),
    'supervisor': REFERENCE / 'supervisor-inputs.json',
    'source': HERE / 'transform.py',
    'builder': Path(__file__).resolve(),
    'compiler': COMPILER,
    'baselineCase': ROOT / 'experiments/dock-turn-reacquire-current-v1/baseline-case.flex',
    'candidateTransform': ROOT / 'experiments/dock-turn-reacquire-current-v1/transform.py',
    'originalTransform': ROOT / 'experiments/dock-turn-reacquire-v1/transform.py',
}


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


inject = load('dock_turn_rendered_transform', HERE / 'transform.py')
prior = load('dock_turn_current_transform', ROOT / 'experiments/dock-turn-reacquire-current-v1/transform.py')


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def inventory(root):
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*'))
            if p.is_file() and p.suffix != '.pyc' and '__pycache__' not in p.parts}


def verify(output, recompile=False):
    output = Path(output).absolute()
    report = json.loads((output / 'build.json').read_text())
    if report.get('schema') != 'puppybot.dock-turn-rendered-probe-build.v1':
        raise ValueError('build schema differs')
    if report.get('inputs') != {name: sha(path) for name, path in INPUTS.items()}:
        raise ValueError('build input changed')
    arms = report.get('arms', {})
    if set(arms) != {f'{kind}-{duration}' for kind in ('control', 'candidate') for duration in (0, 10, 60)}:
        raise ValueError('unexpected arm inventory')
    original = inventory(ROOT / 'flex'); original_lib = inventory(ROOT / 'build/flex/sim/library')
    baseline = INPUTS['baselineCase'].read_text(); candidate = prior.transform(baseline)
    if candidate != (ROOT / 'flex/sim/case.flex').read_text():
        raise ValueError('current candidate differs')
    dock = (ROOT / 'flex/sim/dock-vision.flex').read_text()
    for name, record in arms.items():
        label, number = name.split('-'); duration = int(number); is_candidate = label == 'candidate'
        if record.get('candidate') is not is_candidate or record.get('durationTicks') != duration:
            raise ValueError('arm mode differs')
        arm = output / name; source = arm / 'flex'; library = arm / 'build/flex/sim/library'
        if inventory(source) != record['source'] or inventory(library) != record['library']:
            raise ValueError('arm sources changed')
        for key, digest in original.items():
            if key not in ('sim/case.flex', 'sim/dock-vision.flex') and record['source'].get(key) != digest:
                raise ValueError('unrelated source changed')
        if set(record['source']) != set(original):
            raise ValueError('source inventory differs')
        case_expected, dock_expected = inject.transform(candidate if is_candidate else baseline, dock, duration, is_candidate)
        if ((source / 'sim/case.flex').read_text() != case_expected or
                (source / 'sim/dock-vision.flex').read_text() != dock_expected):
            raise ValueError('fault transform differs')
        if set(record['library']) != set(original_lib):
            raise ValueError('library inventory differs')
        for key, digest in original_lib.items():
            if key != 'lib/f64.flex' and record['library'][key] != digest:
                raise ValueError('unrelated library changed')
        adapter = inject.once((ROOT / 'build/flex/sim/library/lib/f64.flex').read_text(),
                              f'import "{ROOT / "flex/core/words.flex"}";',
                              f'import "{source / "core/words.flex"}";')
        if (library / 'lib/f64.flex').read_text() != adapter:
            raise ValueError('library adapter differs')
        deps = library.parent / 'dependencies.flex'
        expected_deps = f'import "{library / "libs/render.flex"}";\nimport "{library / "libs/physics/physics.flex"}";\n'
        if deps.read_text() != expected_deps or sha(deps) != record['dependenciesSHA256']:
            raise ValueError('generated dependencies changed')
        binary = arm / 'simulator'
        if sha(binary) != record['simulatorSHA256']:
            raise ValueError('simulator changed')
        if recompile:
            with tempfile.TemporaryDirectory(prefix='dock-turn-rebuild-') as tmp:
                rebuilt = Path(tmp) / 'simulator'
                subprocess.run([str(COMPILER), str(source / 'sim/main.flex'), '-o', str(rebuilt)],
                               cwd=ROOT, check=True, timeout=120, capture_output=True)
                if sha(rebuilt) != sha(binary):
                    raise ValueError('private source rebuild differs')
    return report


def build(output):
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError('output already exists')
    pins = {name: sha(path) for name, path in INPUTS.items()}
    ref = json.loads((REFERENCE / 'supervisor-inputs.json').read_text())
    for name, key in (('case', 'caseSHA256'), ('environment', 'environmentSHA256'),
                      ('robot', 'robotAssetSHA256'), ('model', 'weightsSHA256'),
                      ('policy', 'policySHA256'), ('receipt', 'receiptSHA256')):
        if pins[name] != ref['referenceInputs'][key]:
            raise ValueError('historical reference input changed: ' + name)
    if pins['client'] != ref['clientSHA256']:
        raise ValueError('historical client changed')
    baseline = (ROOT / 'experiments/dock-turn-reacquire-current-v1/baseline-case.flex').read_text()
    candidate = prior.transform(baseline)
    if candidate != (ROOT / 'flex/sim/case.flex').read_text():
        raise ValueError('live source differs from reviewed candidate')
    current = inventory(ROOT / 'flex'); lib_current = inventory(ROOT / 'build/flex/sim/library')
    dock = (ROOT / 'flex/sim/dock-vision.flex').read_text()
    output.mkdir(parents=False)
    arms = {}
    for label, is_candidate, original in (('control', False, baseline), ('candidate', True, candidate)):
        for duration in (0, 10, 60):
            arm = output / (label + '-' + str(duration)); arm.mkdir()
            source = arm / 'flex'; library = arm / 'build/flex/sim/library'
            shutil.copytree(ROOT / 'flex', source, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            shutil.copytree(ROOT / 'build/flex/sim/library', library)
            if inventory(source) != current or inventory(library) != lib_current:
                raise ValueError('source changed while copying')
            adapter = library / 'lib/f64.flex'
            adapter.write_text(inject.once(adapter.read_text(), f'import "{ROOT / "flex/core/words.flex"}";',
                                           f'import "{source / "core/words.flex"}";'))
            (library.parent / 'dependencies.flex').write_text(
                f'import "{library / "libs/render.flex"}";\nimport "{library / "libs/physics/physics.flex"}";\n')
            instrumented_case, instrumented_dock = inject.transform(original, dock, duration, is_candidate)
            (source / 'sim/case.flex').write_text(instrumented_case)
            (source / 'sim/dock-vision.flex').write_text(instrumented_dock)
            source_pins, lib_pins = inventory(source), inventory(library)
            deps_sha = sha(library.parent / 'dependencies.flex')
            binary = arm / 'simulator'
            compiled = subprocess.run([str(COMPILER), str(source / 'sim/main.flex'), '-o', str(binary)],
                                      cwd=ROOT, capture_output=True, text=True, timeout=120)
            if compiled.returncode:
                raise RuntimeError(compiled.stdout + '\n' + compiled.stderr)
            if (inventory(source) != source_pins or inventory(library) != lib_pins or
                    sha(library.parent / 'dependencies.flex') != deps_sha):
                raise ValueError('build inputs changed during compilation')
            arms[arm.name] = {'simulatorSHA256': sha(binary), 'source': source_pins,
                              'library': lib_pins, 'dependenciesSHA256': deps_sha,
                              'durationTicks': duration, 'candidate': is_candidate}
    if (pins != {name: sha(path) for name, path in INPUTS.items()} or
            inventory(ROOT / 'flex') != current or inventory(ROOT / 'build/flex/sim/library') != lib_current):
        raise ValueError('source or pinned input changed during build')
    report = {'schema': 'puppybot.dock-turn-rendered-probe-build.v1', 'inputs': pins, 'arms': arms,
              'scope': 'private compiled source variants only; no rendered or physical result'}
    with (output / 'build.json').open('x') as stream:
        json.dump(report, stream, sort_keys=True, indent=2); stream.write('\n')
    if verify(output, recompile=True) != report:
        raise ValueError('final build verification differs')
    return report


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and supervised execution.')
