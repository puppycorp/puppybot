#!/usr/bin/env python3
"""Build a copied 1031-episode trainer; no GPU initialization or training."""
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
PREVIOUS = P / 'outbound-five-trainer-build-v1'
DEFAULT = P / 'parent-route-paired-trainer-build-v1'
COMPILER = ROOT / 'build/flex/control/compiler'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


prior = load('paired_trainer_previous_builder', ROOT / 'experiments/outbound-five-trainer-v1/build.py')
transform = load('paired_trainer_source_transform', HERE / 'transform.py')
sha, tree, imports = prior.sha, prior.tree, prior.imports


def pins():
    paths = (Path(__file__).resolve(), HERE / 'transform.py',
             ROOT / 'experiments/outbound-five-trainer-v1/build.py', PREVIOUS / 'build.json', COMPILER)
    return {str(path): sha(path) for path in paths}


def expected_source(source, trainer):
    changed = dict(source)
    changed['control/dataset.flex'] = transform.dataset(source['control/dataset.flex'])
    changed['control/train.flex'] = transform.train(source['control/train.flex'])
    changed['control/workflow.flex'] = transform.workflow(source['control/workflow.flex'], PREVIOUS / 'trainer', trainer)
    return changed


def verify(output=DEFAULT, *, recompile=True):
    output = Path(output).absolute()
    if output.is_symlink() or not output.is_dir():
        raise ValueError('invalid private trainer output')
    receipt = json.loads((output / 'build.json').read_text())
    if (receipt.get('schema') != 'puppybot.parent-route-paired-trainer-build.v1' or
            receipt.get('status') != 'cpu_build_only' or receipt.get('dimensions') != [1031, 935, 300] or
            receipt.get('auxiliaryMaskEpisodeRange') != [928, 935] or receipt.get('sourcePins') != pins()):
        raise ValueError('private trainer receipt or source pins differ')
    previous = prior.verify(PREVIOUS)
    if sha(PREVIOUS / 'build.json') != receipt['previousBuildSHA256']:
        raise ValueError('previous verified trainer build changed')
    original = tree(PREVIOUS / 'flex-source'); source = output / 'flex-source'
    if receipt['previousSource'] != original or receipt['privateSource'] != tree(source):
        raise ValueError('previous or private source tree changed')
    keys = ('control/dataset.flex', 'control/train.flex', 'control/workflow.flex')
    before = {key: (PREVIOUS / 'flex-source' / key).read_text() for key in keys}
    expected = expected_source(before, output / 'trainer')
    if any((source / key).read_text() != expected[key] for key in keys):
        raise ValueError('private trainer transform differs')
    expected_tree = dict(original)
    import hashlib
    expected_tree.update({key: hashlib.sha256(value.encode()).hexdigest() for key, value in expected.items()})
    if receipt['privateSource'] != expected_tree:
        raise ValueError('unrelated private trainer source changed')
    link = output / 'build'
    if not link.is_symlink() or link.resolve(strict=True) != (ROOT / 'build').resolve(strict=True):
        raise ValueError('generated source link changed')
    entries = tuple(source / 'control' / name for name in ('main.flex', 'train.flex', 'reflink-probe.flex'))
    if (imports(entries) != receipt['imports'] or sha(COMPILER) != receipt['compilerSHA256'] or
            {name: sha(output / name) for name in ('control', 'trainer', 'reflink-probe')} != receipt['binaries']):
        raise ValueError('trainer import, compiler or binary changed')
    if recompile:
        with tempfile.TemporaryDirectory(prefix='parent-paired-trainer-rebuild-') as temporary:
            for entry, name in zip(entries, ('control', 'trainer', 'reflink-probe')):
                binary = Path(temporary) / name
                subprocess.run([str(COMPILER), str(entry), '-o', str(binary)], cwd=ROOT,
                               capture_output=True, text=True, timeout=120, check=True)
                if sha(binary) != receipt['binaries'][name]:
                    raise ValueError('private trainer binary does not reproduce')
    for name in ('source', 'target'):
        path = output / 'clone-fixture' / name
        if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1 or sha(path) != receipt['cloneFixtureSHA256']:
            raise ValueError('private clone fixture changed')
    if (output / 'clone-fixture/source').stat().st_ino == (output / 'clone-fixture/target').stat().st_ino:
        raise ValueError('clone fixture reused an inode')
    if (prior.verify(PREVIOUS) != previous or pins() != receipt['sourcePins'] or
            tree(source) != receipt['privateSource'] or imports(entries) != receipt['imports']):
        raise ValueError('trainer input changed during verification')
    return receipt


def build(output=DEFAULT):
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError('trainer output exists; preserve it')
    if not output.parent.is_dir() or shutil.disk_usage(output.parent).free < 38 * 1024**3:
        raise ValueError('trainer build requires 38 GiB free')
    previous = prior.verify(PREVIOUS); previous_sha = sha(PREVIOUS / 'build.json')
    original = tree(PREVIOUS / 'flex-source'); sources = pins(); compiler_sha = sha(COMPILER)
    output.mkdir(); source = output / 'flex-source'; shutil.copytree(PREVIOUS / 'flex-source', source)
    if tree(source) != original or tree(PREVIOUS / 'flex-source') != original:
        raise ValueError('previous trainer source changed during copy')
    (output / 'build').symlink_to(ROOT / 'build', target_is_directory=True)
    keys = ('control/dataset.flex', 'control/train.flex', 'control/workflow.flex')
    before = {key: (source / key).read_text() for key in keys}
    changed = expected_source(before, output / 'trainer')
    for key in keys:
        (source / key).write_text(changed[key])
    private = tree(source); entries = tuple(source / 'control' / name for name in ('main.flex', 'train.flex', 'reflink-probe.flex'))
    imported = imports(entries); binaries = {}
    for entry, name in zip(entries, ('control', 'trainer', 'reflink-probe')):
        dest = output / name
        subprocess.run([str(COMPILER), str(entry), '-o', str(dest)], cwd=ROOT,
                       capture_output=True, text=True, timeout=120, check=True)
        binaries[name] = sha(dest)
    fixture = output / 'clone-fixture'; fixture.mkdir()
    source_file, target_file = fixture / 'source', fixture / 'target'
    contents = b'private paired trainer FICLONE fixture\n' * 256
    with source_file.open('xb') as stream:
        stream.write(contents); stream.flush(); os.fsync(stream.fileno())
    subprocess.run([str(output / 'reflink-probe'), str(source_file), str(target_file)],
                   cwd=ROOT, capture_output=True, text=True, timeout=20, check=True)
    if (source_file.read_bytes() != contents or target_file.read_bytes() != contents or
            source_file.stat().st_ino == target_file.stat().st_ino or
            source_file.stat().st_nlink != 1 or target_file.stat().st_nlink != 1):
        raise ValueError('private FICLONE probe bytes or identity differ')
    extent = subprocess.check_output(['btrfs', 'filesystem', 'du', '--raw', '-s', str(source_file), str(target_file)],
                                     cwd=ROOT, text=True, timeout=20)
    lines = extent.strip().splitlines()
    if len(lines) != 3:
        raise ValueError('unexpected FICLONE extent report')
    for line in lines[1:]:
        fields = line.split(maxsplit=3)
        if len(fields) != 4 or any(not value.isdigit() for value in fields[:3]):
            raise ValueError('invalid FICLONE extent report')
        total, exclusive, shared = map(int, fields[:3])
        if total <= 0 or exclusive != 0 or shared != total:
            raise ValueError('private FICLONE fixture does not share extents')
    if (pins() != sources or sha(COMPILER) != compiler_sha or tree(source) != private or
            imports(entries) != imported or prior.verify(PREVIOUS) != previous):
        raise ValueError('trainer inputs changed during compilation')
    receipt = {'schema': 'puppybot.parent-route-paired-trainer-build.v1', 'status': 'cpu_build_only',
               'previousBuildSHA256': previous_sha, 'previousSource': original, 'privateSource': private,
               'sourcePins': sources, 'compilerSHA256': compiler_sha, 'imports': imported, 'binaries': binaries,
               'cloneFixtureSHA256': sha(source_file), 'cloneFixtureExtentReport': extent,
               'dimensions': [1031, 935, 300], 'auxiliaryMaskEpisodeRange': [928, 935],
               'scope': 'private CPU build only; no dataset identity, GPU training, gradient or performance claim'}
    with (output / 'build.json').open('x') as stream:
        json.dump(receipt, stream, sort_keys=True, indent=2); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    if verify(output) != receipt:
        raise ValueError('private trainer build readback differs')
    return receipt


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and resource scheduling.')
