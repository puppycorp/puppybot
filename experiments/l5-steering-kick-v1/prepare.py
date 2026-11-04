#!/usr/bin/env python3
"""Disabled isolated build for the simulator-only L5 steering probe."""
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
OUTPUT = P / 'l5-steering-kick-build-v1'
COMPILER = ROOT / 'build/flex/control/compiler'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


transform = load('steering_transform', HERE / 'transform.py')
base = load('steering_build_base', ROOT / 'datasets/visual-control/chase-v1/levels/run-route-factorial.py')
hidden = base.hidden


def verify(output=OUTPUT):
    output = Path(output)
    if output != OUTPUT or output.is_symlink(): raise ValueError('unexpected build path')
    report = json.loads((output / 'build.json').read_text())
    if report.get('schema') != 'puppybot.l5-steer-build.v1' or report.get('status') != 'diagnostic_build_only':
        raise ValueError('invalid isolated build receipt')
    inputs = report['inputs']
    expected = (COMPILER, HERE / 'transform.py', HERE / 'probe.flex', Path(__file__))
    if set(inputs) != {str(path) for path in expected} or any(base.sha(path) != inputs[str(path)] for path in expected):
        raise ValueError('build inputs changed')
    copied = output / 'flex-source'
    if (hidden.supervisor.source_hashes(copied) != report['patchedSources'] or
            hidden.supervisor.source_hashes(ROOT / 'flex') != report['originalSources']):
        raise ValueError('build source changed')
    original_chase = (output / 'original-chase.flex').read_text(); original_main = (output / 'original-main.flex').read_text()
    chase, main = transform.transform(original_chase, original_main)
    if ((ROOT / 'flex/control/chase.flex').read_text() != original_chase or
            (ROOT / 'flex/control/main.flex').read_text() != original_main or
            (copied / 'control/chase.flex').read_text() != chase or (copied / 'control/main.flex').read_text() != main or
            (copied / 'control/steer-probe.flex').read_bytes() != (HERE / 'probe.flex').read_bytes() or
            base.sha(output / 'control') != report['controlSHA256'] or base.sha(output / 'probe') != report['probeSHA256']):
        raise ValueError('isolated transform or binary differs')
    return report


def prepare(output=OUTPUT):
    """Must be called in a dedicated monitored process, never during GPU work."""
    with base.acquire_lock(P / '.l4-matched.lock'):
        output = Path(output)
        if output != OUTPUT: raise ValueError('build path is fixed')
        base.require_new_output(output); base.require_capacity(P, 36 * 1024**3)
        snapshot = hidden.supervisor.source_hashes(ROOT / 'flex')
        inputs = {str(path): base.sha(path) for path in (COMPILER, HERE / 'transform.py', HERE / 'probe.flex', Path(__file__))}
        output.mkdir(); copied = output / 'flex-source'
        shutil.copytree(ROOT / 'flex', copied, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        if hidden.supervisor.source_hashes(copied) != snapshot or hidden.supervisor.source_hashes(ROOT / 'flex') != snapshot:
            raise ValueError('source snapshot changed')
        chase = copied / 'control/chase.flex'; main = copied / 'control/main.flex'
        original_chase = chase.read_text(); original_main = main.read_text()
        (output / 'original-chase.flex').write_text(original_chase); (output / 'original-main.flex').write_text(original_main)
        changed_chase, changed_main = transform.transform(original_chase, original_main)
        chase.write_text(changed_chase); main.write_text(changed_main)
        shutil.copyfile(HERE / 'probe.flex', copied / 'control/steer-probe.flex')
        patched = hidden.supervisor.source_hashes(copied)
        for source, name, limit in (('main.flex', 'control', 120), ('steer-probe.flex', 'probe', 120)):
            subprocess.run([str(COMPILER), str(copied / 'control' / source), '-o', str(output / name)],
                           cwd=ROOT, check=True, timeout=limit)
        subprocess.run([str(output / 'probe')], cwd=ROOT, check=True, timeout=10)
        if any(base.sha(Path(path)) != digest for path, digest in inputs.items()): raise ValueError('build input changed')
        if hidden.supervisor.source_hashes(ROOT / 'flex') != snapshot: raise ValueError('active source changed')
        if hidden.supervisor.source_hashes(copied) != patched: raise ValueError('isolated source changed during build')
        base.require_capacity(P, 32 * 1024**3)
        report = {'schema': 'puppybot.l5-steer-build.v1', 'status': 'diagnostic_build_only',
                  'inputs': inputs, 'originalSources': snapshot, 'patchedSources': patched,
                  'controlSHA256': base.sha(output / 'control'), 'probeSHA256': base.sha(output / 'probe'),
                  'scope': 'isolated source build only; no original simulator or actor execution attestation'}
        with (output / 'build.json').open('x') as stream:
            json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False); stream.write('\n')
        if verify(output) != report: raise ValueError('published build receipt differs')
        return report


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and scheduling; no GPU launch authorized.')
