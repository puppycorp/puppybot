#!/usr/bin/env python3
"""Create and recompile a private collector build; never launch a simulator."""
import hashlib
import importlib.util
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT = ROOT / 'build/flex/sim/levels-v2/pitch82/parent-route-actor-boundary-build-v2'
COMPILER = ROOT / 'build/flex/control/compiler'


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def inventory(root):
    root = Path(root)
    return {str(path.relative_to(root)): digest(path) for path in sorted(root.rglob('*'))
            if path.is_file() and not path.is_symlink() and '__pycache__' not in path.parts and path.suffix != '.pyc'}


def transformer():
    spec = importlib.util.spec_from_file_location('parent_boundary_transform', HERE / 'transform.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_pins():
    files = (COMPILER, Path(__file__).resolve(), HERE / 'transform.py', HERE / 'parent-boundary.flex',
             HERE / 'audit.py', HERE / 'test.py', HERE / 'probe.flex')
    return {str(path): digest(path) for path in files}


def verify(output=OUTPUT):
    output = Path(output).absolute()
    if output != OUTPUT or output.is_symlink():
        raise ValueError('unexpected build path')
    record = json.loads((output / 'build.json').read_text())
    if (record.get('schema') != 'puppybot.parent-boundary-private-build.v1' or
            record.get('sourcePins') != source_pins() or record.get('originalSources') != inventory(ROOT / 'flex')):
        raise ValueError('private build source or tool changed')
    source = output / 'flex'
    if inventory(source) != record.get('privateSources'):
        raise ValueError('private sources changed')
    expected = transformer().transform((ROOT / 'flex/control/chase.flex').read_text())
    if ((source / 'control/chase.flex').read_text() != expected or
            (source / 'control/parent-boundary.flex').read_bytes() != (HERE / 'parent-boundary.flex').read_bytes()):
        raise ValueError('private instrumentation differs')
    original = record['originalSources']
    private = record['privateSources']
    if set(private) != set(original) | {'control/parent-boundary.flex'}:
        raise ValueError('private source inventory differs')
    if any(private[name] != value for name, value in original.items() if name != 'control/chase.flex'):
        raise ValueError('unrelated private source differs')
    if digest(output / 'control') != record.get('controlSHA256'):
        raise ValueError('private control binary differs')
    with tempfile.TemporaryDirectory(prefix='parent-boundary-rebuild-') as directory:
        rebuilt = Path(directory) / 'control'
        subprocess.run([str(COMPILER), str(source / 'control/main.flex'), '-o', str(rebuilt)],
                       cwd=ROOT, check=True, timeout=120)
        if digest(rebuilt) != record['controlSHA256']:
            raise ValueError('private binary does not reproduce from recorded source')
    if source_pins() != record['sourcePins'] or inventory(source) != private or inventory(ROOT / 'flex') != original:
        raise ValueError('source changed during rebuild')
    return record


def build(output=OUTPUT):
    output = Path(output).absolute()
    if output != OUTPUT or output.exists() or output.is_symlink():
        raise FileExistsError('private build path exists or is unexpected')
    if shutil.disk_usage(ROOT).free < 38 * 1024**3:
        raise ValueError('insufficient free disk for private build')
    original = inventory(ROOT / 'flex'); pins = source_pins()
    output.mkdir(); source = output / 'flex'
    shutil.copytree(ROOT / 'flex', source, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    if inventory(source) != original:
        raise ValueError('source copy differs')
    chase = source / 'control/chase.flex'
    chase.write_text(transformer().transform(chase.read_text()))
    shutil.copyfile(HERE / 'parent-boundary.flex', source / 'control/parent-boundary.flex')
    private = inventory(source)
    subprocess.run([str(COMPILER), str(source / 'control/main.flex'), '-o', str(output / 'control')],
                   cwd=ROOT, check=True, timeout=120)
    if source_pins() != pins or inventory(ROOT / 'flex') != original or inventory(source) != private:
        raise ValueError('source changed while compiling')
    record = {'schema': 'puppybot.parent-boundary-private-build.v1', 'status': 'cpu_build_only',
              'sourcePins': pins, 'originalSources': original, 'privateSources': private,
              'controlSHA256': digest(output / 'control'),
              'scope': 'private source/binary reproducibility only; no GPU run or actor execution proof'}
    with (output / 'build.json').open('x') as stream:
        json.dump(record, stream, indent=2, sort_keys=True); stream.write('\n')
    if verify(output) != record:
        raise ValueError('published build verification differs')
    return record


if __name__ == '__main__':
    raise SystemExit('Disabled: private build requires independent review and a dedicated process.')
