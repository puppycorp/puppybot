#!/usr/bin/env python3
"""Build a fresh diagnostic simulator from the recorded dock-confirm source."""
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ARCHIVE = ROOT / 'build/flex/sim/levels-v2/pitch82/physical-dock-confirm-build-v1'
COMPILER = ROOT / 'build/flex/control/compiler'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


transform = load('survey_transform', HERE / 'transform.py')
search = load('survey_source_hashes', ROOT / 'experiments/physical-search-fallback-v1/prepare.py')
dock = load('survey_existing_check', ROOT / 'experiments/physical-dock-confirm-trial-v1/run.py')


def build(output):
    output = Path(output).absolute()
    if output.exists() or output.is_symlink(): raise ValueError('output exists; preserve it')
    original = dock.check_build(ARCHIVE)
    archived_report_sha = search.sha(ARCHIVE / 'build.json')
    transform_sha = search.sha(HERE / 'transform.py')
    output.mkdir(parents=False, exist_ok=False)
    source = output / 'source'; build_root = output / 'build'
    shutil.copytree(ARCHIVE / 'source', source, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copytree(ARCHIVE / 'build', build_root, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    library = build_root / 'flex/sim/library'; adapter = library / 'lib/f64.flex'
    old = f'import "{ARCHIVE / "source/core/words.flex"}";'
    new = f'import "{source / "core/words.flex"}";'
    adapter.write_text(transform.once(adapter.read_text(), old, new))
    (library.parent / 'dependencies.flex').write_text(
        f'import "{library / "libs/render.flex"}";\nimport "{library / "libs/physics/physics.flex"}";\n')
    names = ('main.flex', 'dock-vision.flex', 'dock-search.flex', 'navigation.flex')
    paths = [source / 'sim' / name for name in names]
    for path, content in zip(paths, transform.transform(*(p.read_text() for p in paths))): path.write_text(content)
    candidate = search.hashes(source); library_hash = search.hashes(library)
    changed = {'sim/' + name for name in names}
    if set(candidate) != set(original['source']) or any(candidate[name] != digest for name, digest in original['source'].items() if name not in changed):
        raise ValueError('unrelated source changed')
    shutil.copyfile(ARCHIVE / 'client', output / 'client'); (output / 'client').chmod(0o755)
    subprocess.run([str(COMPILER), str(paths[0]), '-o', str(output / 'simulator')],
                   cwd=ROOT, check=True, timeout=120, capture_output=True)
    for name in ('client', 'simulator'):
        shutil.copyfile(output / name, output / ('baseline-' + name)); (output / ('baseline-' + name)).chmod(0o755)
    if (dock.check_build(ARCHIVE) != original or search.sha(ARCHIVE / 'build.json') != archived_report_sha or
            search.sha(HERE / 'transform.py') != transform_sha or search.hashes(source) != candidate or
            search.hashes(library) != library_hash or search.sha(COMPILER) != original['compilerSHA256'] or
            search.sha(output / 'client') != original['clientSHA256'] or
            any(search.sha(output / name) != search.sha(output / ('baseline-' + name))
                for name in ('client', 'simulator'))):
        raise ValueError('inputs changed during build')
    result = {'schema': 'puppybot.dock-survey-diagnostic-build.v1', 'archiveReportSHA256': archived_report_sha,
              'transformSHA256': transform_sha, 'compilerSHA256': original['compilerSHA256'],
              'source': candidate, 'library': library_hash, 'clientSHA256': search.sha(output / 'client'),
              'simulatorSHA256': search.sha(output / 'simulator'),
              'scope': 'simulator diagnostic build only; no rendered or physical validation'}
    (output / 'build.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    return result


if __name__ == '__main__':
    raise SystemExit('Direct build disabled; use a reviewed supervised caller.')
