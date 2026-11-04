#!/usr/bin/env python3
"""Build the visual-search client beside an unchanged search simulator."""
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ARCHIVE = ROOT / 'build/flex/sim/levels-v2/pitch82/physical-search-fallback-build-v1'
COMPILER = ROOT / 'build/flex/control/compiler'
STALL = ROOT / 'experiments/visual-exact-stall-v1/visual-stall.flex'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


prepare = load('matched_search_prepare', ROOT / 'experiments/physical-search-fallback-v1/prepare.py')
transform = load('matched_visual_transform', ROOT / 'experiments/visual-search-recovery-v1/transform.py')


def inputs():
    report = json.loads((ARCHIVE / 'build.json').read_text())
    if report.get('schema') != 'puppybot.physical-search-fallback-build.v1': raise ValueError('archive schema differs')
    if (prepare.hashes(ARCHIVE / 'source') != report['patchedSource'] or
            prepare.hashes(ARCHIVE / 'build/flex/sim/library') != report['library'] or
            prepare.sha(COMPILER) != report['compilerSHA256'] or
            prepare.sha(ARCHIVE / 'client') != report['clientSHA256'] or
            prepare.sha(ARCHIVE / 'simulator') != report['simulatorSHA256']):
        raise ValueError('search archive changed')
    return {'archive': prepare.sha(ARCHIVE / 'build.json'), 'compiler': prepare.sha(COMPILER),
            'transform': prepare.sha(Path(transform.__file__)), 'stall': prepare.sha(STALL),
            'builder': prepare.sha(Path(__file__))}


def verify(output):
    output = Path(output); report = json.loads((output / 'build.json').read_text())
    if report.get('schema') != 'puppybot.visual-search-matched-build.v1' or report.get('inputs') != inputs():
        raise ValueError('build provenance differs')
    old = prepare.hashes(ARCHIVE / 'source'); source = output / 'source'; current = prepare.hashes(source)
    changed = 'control/physical-client.flex'; added = 'control/visual-stall.flex'
    if set(current) != set(old) | {added} or any(current[k] != v for k, v in old.items() if k != changed):
        raise ValueError('unrelated source changed')
    if ((source / changed).read_text() != transform.transform((ARCHIVE / 'source' / changed).read_text()) or
            (source / added).read_bytes() != STALL.read_bytes() or current != report['source'] or
            prepare.hashes(output / 'build/flex/sim/library') != report['library'] or
            report['library'] != prepare.hashes(ARCHIVE / 'build/flex/sim/library')):
        raise ValueError('build transform or library differs')
    if prepare.sha(output / 'build/flex/sim/dependencies.flex') != prepare.sha(ARCHIVE / 'build/flex/sim/dependencies.flex'):
        raise ValueError('copied dependencies differ')
    for name in ('client', 'simulator'):
        digest = report[name + 'SHA256']
        if (prepare.sha(output / name) != digest or prepare.sha(output / ('baseline-' + name)) != digest or
                not os.access(output / name, os.X_OK) or not os.access(output / ('baseline-' + name), os.X_OK)):
            raise ValueError('binary changed or same-binary comparison lost')
    if report['simulatorSHA256'] != prepare.sha(ARCHIVE / 'simulator'):
        raise ValueError('simulator differs from archive')
    return report


def build(output):
    output = Path(output).absolute()
    if output.exists() or output.is_symlink(): raise FileExistsError('preserve existing output')
    pinned = inputs(); output.mkdir(parents=False, exist_ok=False)
    source = output / 'source'
    shutil.copytree(ARCHIVE / 'source', source, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copytree(ARCHIVE / 'build', output / 'build', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    path = source / 'control/physical-client.flex'; path.write_text(transform.transform(path.read_text()))
    shutil.copyfile(STALL, source / 'control/visual-stall.flex')
    subprocess.run([str(COMPILER), str(path), '-o', str(output / 'client')],
                   cwd=ROOT, check=True, timeout=120, capture_output=True)
    shutil.copyfile(ARCHIVE / 'simulator', output / 'simulator')
    for name in ('client', 'simulator'):
        (output / name).chmod(0o755)
        shutil.copyfile(output / name, output / ('baseline-' + name)); (output / ('baseline-' + name)).chmod(0o755)
    if inputs() != pinned: raise ValueError('build inputs changed')
    report = {'schema': 'puppybot.visual-search-matched-build.v1', 'inputs': pinned,
              'source': prepare.hashes(source), 'library': prepare.hashes(output / 'build/flex/sim/library'),
              'clientSHA256': prepare.sha(output / 'client'), 'simulatorSHA256': prepare.sha(output / 'simulator'),
              'scope': 'copied simulator and transformed client; no rendered or physical validation'}
    with (output / 'build.json').open('x') as stream: json.dump(report, stream, indent=2, sort_keys=True); stream.write('\n')
    if verify(output) != report: raise ValueError('build verification differs')
    return report


if __name__ == '__main__': raise SystemExit('Disabled; use a reviewed supervised build.')
