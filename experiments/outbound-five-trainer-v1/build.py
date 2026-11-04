#!/usr/bin/env python3
"""Build copied, narrowly adapted training binaries; never run the GPU."""
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PITCH = ROOT / 'build/flex/sim/levels-v2/pitch82'
ARCHIVE = PITCH / 'search-dagger-heading-trainer-build'
DEFAULT = PITCH / 'outbound-five-trainer-build-v1'
COMPILER = ROOT / 'build/flex/control/compiler'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


capacity = load('outbound_episode_capacity', ROOT / 'experiments/outbound-episode-cap-v1/transform.py')
auxiliary = load('outbound_auxiliary_mask', ROOT / 'experiments/outbound-aux-mask-v1/transform.py')
clone = load('outbound_reflink_transform', ROOT / 'datasets/visual-control/chase-v1/levels/heading-reflink-source.py')


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def tree(root):
    root = Path(root)
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*'))
            if p.is_file() and not p.is_symlink() and '__pycache__' not in p.parts and p.suffix != '.pyc'}


def imports(entries):
    """Pin literal source imports; reject missing or unparseable source files."""
    pending = list(entries); result = {}
    pattern = re.compile(r'^\s*import\s+"([^"\n]+)"\s*;', re.MULTILINE)
    while pending:
        path = Path(pending.pop()).resolve(strict=True)
        if str(path) in result:
            continue
        text = path.read_text()
        result[str(path)] = sha(path)
        for name in pattern.findall(text):
            child = Path(name)
            pending.append(child if child.is_absolute() else path.parent / child)
    return dict(sorted(result.items()))


def workflow(source, trainer):
    old = 'let args=vc_args();vc_add(args,vw_binary("trainer"));'
    if source.count(old) != 1:
        raise ValueError('unexpected training executable anchor')
    if any(c in str(trainer) for c in '"\\\n\r'):
        raise ValueError('unsafe private trainer path')
    return source.replace(old, f'let args=vc_args();vc_add(args,"{trainer}");', 1)


def expected_source(source, trainer):
    """Transform only dataset limit, trainer auxiliary masks and trainer path."""
    changed = dict(source)
    changed['control/dataset.flex'] = capacity.transform(source['control/dataset.flex'])
    changed['control/train.flex'] = auxiliary.transform(source['control/train.flex'], 928, 933)
    changed['control/workflow.flex'] = workflow(source['control/workflow.flex'], trainer)
    return changed


def build(output=DEFAULT):
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError('trainer build output already exists')
    if not output.parent.is_dir() or shutil.disk_usage(output.parent).free < 36 * 1024**3:
        raise ValueError('trainer build lacks parent or 36 GiB disk headroom')
    original = ARCHIVE / 'flex-source'
    old_receipt = json.loads((ARCHIVE / 'inputs.json').read_text())
    snapshot = tree(original)
    if snapshot != old_receipt.get('patchedSourceFiles'):
        raise ValueError('archived training source differs from its receipt')
    original_dataset = (ARCHIVE / 'dataset.original.flex').read_text()
    if (original / 'control/dataset.flex').read_text() != clone.transform(original_dataset):
        raise ValueError('archived reflink source differs from transform')
    before_compiler = sha(COMPILER)
    source_files = (HERE / 'build.py', ROOT / 'experiments/outbound-episode-cap-v1/transform.py',
                    ROOT / 'experiments/outbound-aux-mask-v1/transform.py',
                    ROOT / 'datasets/visual-control/chase-v1/levels/heading-reflink-source.py', ARCHIVE / 'inputs.json')
    before_sources = {str(p): sha(p) for p in source_files}
    output.mkdir(); source = output / 'flex-source'; shutil.copytree(original, source)
    if tree(source) != snapshot or tree(original) != snapshot:
        raise ValueError('source changed during copy')
    (output / 'build').symlink_to(ROOT / 'build', target_is_directory=True)
    keys = ('control/dataset.flex', 'control/train.flex', 'control/workflow.flex')
    originals = {key: (source / key).read_text() for key in keys}
    patched = expected_source(originals, output / 'trainer')
    for key in keys:
        (source / key).write_text(patched[key])
    patched_tree = tree(source)
    expected_tree = dict(snapshot)
    expected_tree.update({key: sha(source / key) for key in keys})
    if patched_tree != expected_tree:
        raise ValueError('unexpected copied source changes')
    entries = (source / 'control/main.flex', source / 'control/train.flex', source / 'control/reflink-probe.flex')
    source_imports = imports(entries)
    bins = {}
    for entry, target in zip(entries, ('control', 'trainer', 'reflink-probe')):
        dest = output / target
        subprocess.run([str(COMPILER), str(entry), '-o', str(dest)], cwd=ROOT, capture_output=True, text=True, timeout=120, check=True)
        bins[target] = sha(dest)
    fixture = output / 'probe-fixture'; fixture.mkdir()
    data = b'fixed isolated FICLONE probe\n' * 256
    original_file = fixture / 'source'; clone_file = fixture / 'target'
    with original_file.open('xb') as f:
        f.write(data); f.flush(); os.fsync(f.fileno())
    subprocess.run([str(output / 'reflink-probe'), str(original_file), str(clone_file)],
                   cwd=ROOT, capture_output=True, text=True, timeout=20, check=True)
    if original_file.read_bytes() != data or clone_file.read_bytes() != data or original_file.stat().st_ino == clone_file.stat().st_ino:
        raise ValueError('clone probe changed bytes or reused inode')
    raw = subprocess.check_output(['btrfs', 'filesystem', 'du', '--raw', '-s', str(original_file), str(clone_file)], cwd=ROOT, text=True)
    lines = raw.strip().splitlines()
    if len(lines) != 3:
        raise ValueError('unexpected extent query')
    for line in lines[1:]:
        fields = line.split(maxsplit=3)
        if len(fields) != 4 or any(not item.isdigit() for item in fields[:3]):
            raise ValueError('invalid extent query')
        total, exclusive, shared = map(int, fields[:3])
        if total <= 0 or exclusive != 0 or shared != total:
            raise ValueError('training probe did not share extents')
    if (tree(source) != patched_tree or tree(original) != snapshot or imports(entries) != source_imports or
            sha(COMPILER) != before_compiler or {str(p): sha(p) for p in source_files} != before_sources):
        raise ValueError('trainer source or compiler changed during build')
    receipt = {'schema': 'puppybot.outbound-five-trainer-build.v1', 'status': 'isolated_build_only',
               'archiveSource': snapshot, 'patchedSource': patched_tree, 'imports': source_imports,
               'sourcePins': before_sources, 'compilerSHA256': before_compiler, 'binaries': bins,
               'fixtureSHA256': sha(original_file), 'fixtureExtentReport': raw,
               'episodeRange': [928, 933], 'dimensions': [1029, 933, 300],
               'scope': 'local copied build and clone probe; no GPU, dataset, model or execution attestation'}
    with (output / 'build.json').open('x') as stream:
        json.dump(receipt, stream, sort_keys=True, indent=2); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    return receipt


def verify(output=DEFAULT):
    output = Path(output).absolute(); receipt = json.loads((output / 'build.json').read_text())
    if receipt.get('schema') != 'puppybot.outbound-five-trainer-build.v1' or receipt.get('status') != 'isolated_build_only':
        raise ValueError('unexpected private trainer receipt')
    if receipt.get('dimensions') != [1029, 933, 300] or receipt.get('episodeRange') != [928, 933]:
        raise ValueError('unexpected trainer dataset shape')
    archive = tree(ARCHIVE / 'flex-source')
    if archive != json.loads((ARCHIVE / 'inputs.json').read_text()).get('patchedSourceFiles'):
        raise ValueError('archive differs from its original build receipt')
    if archive != receipt['archiveSource'] or tree(output / 'flex-source') != receipt['patchedSource']:
        raise ValueError('archive or private source changed')
    before = {key: (ARCHIVE / 'flex-source' / key).read_text() for key in ('control/dataset.flex', 'control/train.flex', 'control/workflow.flex')}
    transformed = expected_source(before, output / 'trainer')
    if any((output / 'flex-source' / key).read_text() != value for key, value in transformed.items()):
        raise ValueError('private transforms differ')
    expected_tree = dict(archive)
    expected_tree.update({key: hashlib.sha256(value.encode()).hexdigest() for key, value in transformed.items()})
    if receipt['patchedSource'] != expected_tree:
        raise ValueError('unrelated private source differs from archive')
    build_link = output / 'build'
    if not build_link.is_symlink() or build_link.resolve(strict=True) != (ROOT / 'build').resolve(strict=True):
        raise ValueError('private generated-source link differs')
    entries = tuple(output / 'flex-source/control' / p for p in ('main.flex', 'train.flex', 'reflink-probe.flex'))
    if imports(entries) != receipt['imports'] or sha(COMPILER) != receipt['compilerSHA256']:
        raise ValueError('trainer import or compiler changed')
    if {name: sha(output / name) for name in ('control', 'trainer', 'reflink-probe')} != receipt['binaries']:
        raise ValueError('private training binary changed')
    if {path: sha(path) for path in receipt['sourcePins']} != receipt['sourcePins']:
        raise ValueError('trainer builder source changed')
    for name in ('source', 'target'):
        if sha(output / 'probe-fixture' / name) != receipt['fixtureSHA256']:
            raise ValueError('clone probe changed')
    return receipt


if __name__ == '__main__':
    raise SystemExit('CPU build entrypoint disabled; invoke build() under an independently reviewed supervisor.')
