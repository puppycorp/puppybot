#!/usr/bin/env python3
"""Build a disposable contact-stop controller from the archived hysteresis build."""
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
ARCHIVE = P / 'l5-steering-hysteresis-build-v1'
BUILD = P / 'contact-stop-build-v1'
COMPILER = ROOT / 'build/flex/control/compiler'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prior = load('contact_prior_builder', ROOT / 'experiments/l5-steering-hysteresis-v1/prepare.py')
transform = load('contact_trial_transform', ROOT / 'experiments/contact-stop-v1/transform.py')
base = prior.base
LIBRARY = ROOT / 'experiments/contact-stop-v1/contact-stop.flex'


def inputs():
    receipt = prior.verify()
    return {'archiveReceipt': base.sha(ARCHIVE / 'build.json'),
            'archiveControl': receipt['controlSHA256'],
            'compiler': base.sha(COMPILER), 'transform': base.sha(Path(transform.__file__)),
            'library': base.sha(LIBRARY), 'builder': base.sha(Path(__file__))}


def verify(output=BUILD):
    output = Path(output)
    receipt = json.loads((output / 'build.json').read_text())
    if receipt.get('schema') != 'puppybot.contact-stop-build.v1' or receipt.get('inputs') != inputs():
        raise ValueError('build inputs changed')
    source = output / 'flex-source'; original = ARCHIVE / 'flex-source'
    old = base.hidden.supervisor.source_hashes(original)
    actual = base.hidden.supervisor.source_hashes(source)
    changes = ('control/chase.flex', 'control/main.flex')
    extra = 'control/contact-stop.flex'
    if set(actual) != set(old) | {extra} or any(actual[n] != h for n, h in old.items() if n not in changes):
        raise ValueError('unrelated build source changed')
    chase, main = transform.transform(*((original / name).read_text() for name in changes))
    if ((source / changes[0]).read_text() != chase or (source / changes[1]).read_text() != main or
            (source / extra).read_bytes() != LIBRARY.read_bytes() or
            actual != receipt['source'] or base.sha(output / 'control') != receipt['controlSHA256']):
        raise ValueError('transformation or output differs')
    return receipt


def build(output=BUILD):
    """A separate low-priority, locked supervisor must own this build."""
    output = Path(output)
    if output.exists() or output.is_symlink(): raise FileExistsError('preserve existing output')
    pinned = inputs()
    output.mkdir(); source = output / 'flex-source'
    shutil.copytree(ARCHIVE / 'flex-source', source, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    chase = source / 'control/chase.flex'; main = source / 'control/main.flex'
    new_chase, new_main = transform.transform(chase.read_text(), main.read_text())
    chase.write_text(new_chase); main.write_text(new_main)
    shutil.copyfile(LIBRARY, source / 'control/contact-stop.flex')
    compiled = subprocess.run([str(COMPILER), str(main), '-o', str(output / 'control')],
                              cwd=ROOT, timeout=120, capture_output=True)
    if compiled.returncode: raise RuntimeError('controller compilation failed: ' + compiled.stderr.decode(errors='replace')[-2000:])
    if inputs() != pinned: raise ValueError('inputs changed during build')
    receipt = {'schema': 'puppybot.contact-stop-build.v1', 'inputs': pinned,
               'source': base.hidden.supervisor.source_hashes(source),
               'controlSHA256': base.sha(output / 'control'),
               'scope': 'isolated simulator build; no execution or hardware attestation'}
    with (output / 'build.json').open('x') as stream:
        json.dump(receipt, stream, sort_keys=True, indent=2); stream.write('\n')
    if verify(output) != receipt: raise ValueError('build verification differs')
    return receipt


if __name__ == '__main__':
    raise SystemExit('Disabled; reviewed low-priority locked supervision is required.')
