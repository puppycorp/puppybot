#!/usr/bin/env python3
"""Build same-binary opt-in short waypoint over the preserved floor-retry simulator."""
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ARCHIVE = ROOT / 'build/flex/sim/levels-v2/pitch82/dock-floor-refresh-build-v2'
COMPILER = ROOT / 'build/flex/control/compiler'
FLAG = 'PUPPYBOT_SIM_DOCK_SHORT_WAYPOINT'
TRANSFORM = HERE / 'transform.py'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prior = load('dock_waypoint_floor_builder', ROOT / 'experiments/dock-floor-refresh-v1/build.py')
transform = load('dock_waypoint_transform', HERE / 'transform.py')
sha, hashes = prior.sha, prior.hashes
FILES = ('sim/dock-search.flex', 'sim/main.flex')


def verify(output):
    output = Path(output).absolute(); report = json.loads((output / 'build.json').read_text())
    origin = prior.verify(ARCHIVE)
    if (report.get('schema') != 'puppybot.dock-short-waypoint-build.v1' or
            report.get('archiveBuildSHA256') != sha(ARCHIVE / 'build.json') or
            report.get('compilerSHA256') != sha(COMPILER) or
            report.get('builderSHA256') != sha(Path(__file__)) or
            report.get('transformSHA256') != sha(HERE / 'transform.py')):
        raise ValueError('builder, transform, compiler or archive differs')
    source = output / 'source'; library = output / 'build/flex/sim/library'
    current_source, current_library = hashes(source), hashes(library)
    if current_source != report['source'] or current_library != report['library']:
        raise ValueError('copied inputs changed')
    expected = transform.transform(*[(ARCHIVE / 'source' / name).read_text() for name in FILES])
    for name, value in zip(FILES, expected):
        if (source / name).read_text() != value: raise ValueError('waypoint transform differs: ' + name)
    if set(current_source) != set(origin['source']): raise ValueError('source inventory differs')
    for name, digest in origin['source'].items():
        if name not in FILES and current_source[name] != digest: raise ValueError('unrelated source changed: ' + name)
    if set(current_library) != set(origin['library']): raise ValueError('library inventory differs')
    for name, digest in origin['library'].items():
        if name == 'lib/f64.flex':
            expected_adapter = transform.once((ARCHIVE / 'build/flex/sim/library' / name).read_text(),
                f'import "{ARCHIVE / "source/core/words.flex"}";', f'import "{source / "core/words.flex"}";')
            if (library / name).read_text() != expected_adapter: raise ValueError('library adapter differs')
        elif current_library[name] != digest: raise ValueError('unrelated library changed: ' + name)
    expected_deps = f'import "{library / "libs/render.flex"}";\nimport "{library / "libs/physics/physics.flex"}";\n'
    if (library.parent / 'dependencies.flex').read_text() != expected_deps: raise ValueError('dependency path differs')
    for name in ('client', 'simulator'):
        path = output / name; baseline = output / ('baseline-' + name)
        if (sha(path) != report[name + 'SHA256'] or sha(baseline) != report[name + 'SHA256'] or
                not os.access(path, os.X_OK) or not os.access(baseline, os.X_OK)):
            raise ValueError('same-binary comparison differs')
    if report['clientSHA256'] != origin['clientSHA256']: raise ValueError('client differs')
    return report


def build(output):
    output = Path(output).absolute()
    if output.exists() or output.is_symlink(): raise FileExistsError('preserve existing output')
    origin = prior.verify(ARCHIVE)
    pins = {'archiveBuildSHA256': sha(ARCHIVE / 'build.json'), 'compilerSHA256': sha(COMPILER),
            'builderSHA256': sha(Path(__file__)), 'transformSHA256': sha(HERE / 'transform.py')}
    output.mkdir(parents=False, exist_ok=False)
    source = output / 'source'; build_root = output / 'build'
    shutil.copytree(ARCHIVE / 'source', source, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copytree(ARCHIVE / 'build', build_root, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    library = build_root / 'flex/sim/library'; adapter = library / 'lib/f64.flex'
    adapter.write_text(transform.once(adapter.read_text(), f'import "{ARCHIVE / "source/core/words.flex"}";',
                                      f'import "{source / "core/words.flex"}";'))
    (library.parent / 'dependencies.flex').write_text(f'import "{library / "libs/render.flex"}";\nimport "{library / "libs/physics/physics.flex"}";\n')
    paths = [source / name for name in FILES]
    for path, value in zip(paths, transform.transform(*(p.read_text() for p in paths))): path.write_text(value)
    source_hash, library_hash = hashes(source), hashes(library)
    shutil.copyfile(ARCHIVE / 'client', output / 'client'); (output / 'client').chmod(0o755)
    result = subprocess.run([str(COMPILER), str(source / 'sim/main.flex'), '-o', str(output / 'simulator')],
                            cwd=ROOT, timeout=120, capture_output=True, text=True)
    if result.returncode: raise RuntimeError(result.stdout + '\n' + result.stderr)
    (output / 'simulator').chmod(0o755)
    for name in ('client', 'simulator'):
        shutil.copyfile(output / name, output / ('baseline-' + name)); (output / ('baseline-' + name)).chmod(0o755)
    if prior.verify(ARCHIVE) != origin or pins != {'archiveBuildSHA256': sha(ARCHIVE / 'build.json'),
            'compilerSHA256': sha(COMPILER), 'builderSHA256': sha(Path(__file__)),
            'transformSHA256': sha(HERE / 'transform.py')}:
        raise ValueError('inputs changed during build')
    if hashes(source) != source_hash or hashes(library) != library_hash: raise ValueError('copied inputs changed during build')
    report = {'schema': 'puppybot.dock-short-waypoint-build.v1', **pins, 'source': source_hash,
              'library': library_hash, 'clientSHA256': sha(output / 'client'),
              'simulatorSHA256': sha(output / 'simulator'),
              'scope': 'copied simulator build only; both arms use identical binaries'}
    with (output / 'build.json').open('x') as stream:
        json.dump(report, stream, indent=2, sort_keys=True); stream.write('\n')
    if verify(output) != report: raise ValueError('build verification differs')
    return report


if __name__ == '__main__':
    raise SystemExit('Disabled; use a separately reviewed and supervised build.')
