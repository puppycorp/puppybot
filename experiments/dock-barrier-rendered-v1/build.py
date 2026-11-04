#!/usr/bin/env python3
"""Build an isolated dock simulator with the opt-in worker barrier."""
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ARCHIVE = ROOT / 'build/flex/sim/levels-v2/pitch82/dock-clearance-build-v1'
COMPILER = ROOT / 'build/flex/control/compiler'
TRANSFORM = ROOT / 'experiments/discovery-worker-barrier-v1/transform.py'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


clearance = load('barrier_clearance_builder', ROOT / 'experiments/dock-clearance-diagnostic-v1/build.py')
transform = load('barrier_source_transform', TRANSFORM)
sha = clearance.sha
hashes = clearance.survey.base.prepare.hashes


def verify(output):
    output = Path(output); report = json.loads((output / 'build.json').read_text())
    original = clearance.verify(ARCHIVE)
    if (report.get('schema') != 'puppybot.dock-barrier-rendered-build.v1' or
            report.get('archiveSHA256') != sha(ARCHIVE / 'build.json') or
            report.get('transformSHA256') != sha(TRANSFORM) or
            report.get('compilerSHA256') != original['compilerSHA256'] or
            sha(COMPILER) != report['compilerSHA256']):
        raise ValueError('barrier build provenance differs')
    source = output / 'source'; library = output / 'build/flex/sim/library'
    current = hashes(source); libhash = hashes(library)
    if current != report['source'] or libhash != report['library']:
        raise ValueError('barrier source or library changed')
    changed_names = ('sim/discovery.flex', 'sim/main.flex')
    changed = dict(zip(changed_names, transform.transform(*((ARCHIVE / 'source' / n).read_text() for n in changed_names))))
    if set(current) != set(original['source']): raise ValueError('source inventory differs')
    for name, digest in original['source'].items():
        if name in changed:
            if (source / name).read_text() != changed[name]: raise ValueError('barrier transform differs')
        elif current[name] != digest: raise ValueError('unrelated source changed')
    for name, digest in original['library'].items():
        if name == 'lib/f64.flex':
            old = f'import "{ARCHIVE / "source/core/words.flex"}";'
            new = f'import "{source / "core/words.flex"}";'
            expected = transform.once((ARCHIVE / 'build/flex/sim/library' / name).read_text(), old, new)
            if (library / name).read_text() != expected: raise ValueError('library adapter differs')
        elif libhash.get(name) != digest: raise ValueError('unrelated library changed')
    if set(libhash) != set(original['library']): raise ValueError('library inventory differs')
    dependencies = f'import "{library / "libs/render.flex"}";\nimport "{library / "libs/physics/physics.flex"}";\n'
    if (library.parent / 'dependencies.flex').read_text() != dependencies: raise ValueError('dependencies differ')
    for name in ('client', 'simulator'):
        expected = report[name + 'SHA256']
        if (sha(output / name) != expected or sha(output / ('baseline-' + name)) != expected or
                not os.access(output / name, os.X_OK) or not os.access(output / ('baseline-' + name), os.X_OK)):
            raise ValueError('binary changed or same-binary comparison lost')
    if report['clientSHA256'] != original['clientSHA256']: raise ValueError('client differs')
    return report


def build(output):
    output = Path(output).absolute()
    if output.exists() or output.is_symlink(): raise FileExistsError('preserve existing output')
    original = clearance.verify(ARCHIVE); archive_sha = sha(ARCHIVE / 'build.json'); transform_sha = sha(TRANSFORM)
    output.mkdir(parents=False, exist_ok=False)
    source = output / 'source'; build_root = output / 'build'
    shutil.copytree(ARCHIVE / 'source', source, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copytree(ARCHIVE / 'build', build_root, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    library = build_root / 'flex/sim/library'; adapter = library / 'lib/f64.flex'
    old = f'import "{ARCHIVE / "source/core/words.flex"}";'; new = f'import "{source / "core/words.flex"}";'
    adapter.write_text(transform.once(adapter.read_text(), old, new))
    (library.parent / 'dependencies.flex').write_text(
        f'import "{library / "libs/render.flex"}";\nimport "{library / "libs/physics/physics.flex"}";\n')
    paths = [source / name for name in ('sim/discovery.flex', 'sim/main.flex')]
    for path, content in zip(paths, transform.transform(*(p.read_text() for p in paths))): path.write_text(content)
    candidate = hashes(source); libhash = hashes(library)
    shutil.copyfile(ARCHIVE / 'client', output / 'client'); (output / 'client').chmod(0o755)
    subprocess.run([str(COMPILER), str(source / 'sim/main.flex'), '-o', str(output / 'simulator')],
                   cwd=ROOT, check=True, timeout=120, capture_output=True)
    for name in ('client', 'simulator'):
        (output / name).chmod(0o755)
        shutil.copyfile(output / name, output / ('baseline-' + name)); (output / ('baseline-' + name)).chmod(0o755)
    if (clearance.verify(ARCHIVE) != original or sha(ARCHIVE / 'build.json') != archive_sha or
            sha(TRANSFORM) != transform_sha or hashes(source) != candidate or hashes(library) != libhash or
            sha(COMPILER) != original['compilerSHA256']):
        raise ValueError('inputs changed during build')
    report = {'schema': 'puppybot.dock-barrier-rendered-build.v1', 'archiveSHA256': archive_sha,
              'transformSHA256': transform_sha, 'compilerSHA256': original['compilerSHA256'],
              'source': candidate, 'library': libhash, 'clientSHA256': sha(output / 'client'),
              'simulatorSHA256': sha(output / 'simulator'),
              'scope': 'copied simulator build only; no rendered or physical validation'}
    with (output / 'build.json').open('x') as stream: json.dump(report, stream, indent=2, sort_keys=True); stream.write('\n')
    if verify(output) != report: raise ValueError('barrier build verification differs')
    return report


if __name__ == '__main__': raise SystemExit('Disabled; use a reviewed supervised CPU build.')
