#!/usr/bin/env python3
"""Build an isolated simulator candidate; this script does not run a trial."""
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ARCHIVE = ROOT / 'build/flex/sim/levels-v2/pitch82/physical-search-fallback-build-v1'
COMPILER = ROOT / 'build/flex/control/compiler'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


transform = load('dock_confirm_transform', HERE / 'transform.py')
search = load('dock_confirm_search_build', ROOT / 'experiments/physical-search-fallback-v1/prepare.py')


def build(output):
    output = Path(output).absolute()
    if output.exists() or output.is_symlink(): raise ValueError('output exists; preserve it')
    report_path = ARCHIVE / 'build.json'; report_sha = search.sha(report_path)
    report = json.loads(report_path.read_text())
    if report.get('schema') != 'puppybot.physical-search-fallback-build.v1': raise ValueError('unexpected archive')
    original_source = ARCHIVE / 'source'; original_library = ARCHIVE / 'build/flex/sim/library'
    if (search.hashes(original_source) != report['patchedSource'] or
            search.hashes(original_library) != report['library'] or
            search.sha(COMPILER) != report['compilerSHA256'] or
            search.sha(ARCHIVE / 'client') != report['clientSHA256'] or
            search.sha(ARCHIVE / 'simulator') != report['simulatorSHA256']):
        raise ValueError('archived build changed')
    transform_sha = search.sha(HERE / 'transform.py')
    output.mkdir(parents=False, exist_ok=False)
    source = output / 'source'; build_root = output / 'build'
    shutil.copytree(original_source, source, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copytree(ARCHIVE / 'build', build_root, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    library = build_root / 'flex/sim/library'; adapter = library / 'lib/f64.flex'
    old = f'import "{original_source / "core/words.flex"}";'
    new = f'import "{source / "core/words.flex"}";'
    adapter.write_text(transform.once(adapter.read_text(), old, new))
    (library.parent / 'dependencies.flex').write_text(
        f'import "{library / "libs/render.flex"}";\nimport "{library / "libs/physics/physics.flex"}";\n')
    paths = [source / 'sim' / name for name in ('collect.flex', 'discovery.flex', 'main.flex')]
    for path, text in zip(paths, transform.transform(*(path.read_text() for path in paths))): path.write_text(text)
    candidate = search.hashes(source); library_hash = search.hashes(library)
    if any(candidate[name] != digest for name, digest in report['patchedSource'].items()
           if name not in ('sim/collect.flex', 'sim/discovery.flex', 'sim/main.flex')):
        raise ValueError('unrelated source changed')
    shutil.copyfile(ARCHIVE / 'client', output / 'client'); (output / 'client').chmod(0o755)
    subprocess.run([str(COMPILER), str(paths[2]), '-o', str(output / 'simulator')],
                   cwd=ROOT, check=True, timeout=120, capture_output=True)
    for name in ('client', 'simulator'):
        shutil.copyfile(output / name, output / ('baseline-' + name))
        (output / ('baseline-' + name)).chmod(0o755)
    if (search.hashes(source) != candidate or search.hashes(library) != library_hash or
            search.sha(COMPILER) != report['compilerSHA256'] or search.sha(report_path) != report_sha or
            search.sha(HERE / 'transform.py') != transform_sha or
            search.hashes(original_source) != report['patchedSource'] or
            search.hashes(original_library) != report['library'] or
            search.sha(output / 'client') != report['clientSHA256'] or
            any(search.sha(output / name) != search.sha(output / ('baseline-' + name))
                for name in ('client', 'simulator'))):
        raise ValueError('inputs changed during build')
    result = {'schema': 'puppybot.physical-dock-confirm-build.v1',
              'archiveReportSHA256': report_sha, 'transformSHA256': transform_sha,
              'compilerSHA256': report['compilerSHA256'], 'source': candidate,
              'library': library_hash, 'clientSHA256': search.sha(output / 'client'),
              'simulatorSHA256': search.sha(output / 'simulator'),
              'scope': 'isolated simulator build; no rendered trial or physical validation'}
    (output / 'build.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    return result


if __name__ == '__main__':
    raise SystemExit('Direct build disabled; use a reviewed supervised caller.')
