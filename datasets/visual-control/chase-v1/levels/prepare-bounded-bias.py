#!/usr/bin/env python3
"""Build an isolated bounded-bias control binary; no GPU job is launched.

Usage: prepare-bounded-bias.py
Output and copied source are retained on failure. Both experimental arms must
use this same binary, with thresholds 1000 (control) and 70 (treatment).
"""
import fcntl
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[4]
S = PROJECT / 'datasets/visual-control/chase-v1/levels'
P = PROJECT / 'build/flex/sim/levels-v2/pitch82'
O = P / 'search-dagger-l4-matched'
OUTPUT = O / 'bounded-bias-build'
COMPILER = PROJECT / 'build/flex/control/compiler'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


source = load('bounded', S / 'bounded-bias-source.py')
hybrid = load('hybrid', PROJECT / 'flex/tests/run-physical-hybrid-trial.py')


def verify(output, manifest):
    if hybrid.source_hashes(output / 'flex-source') != manifest['patchedSourceFiles']:
        raise ValueError('archived source changed')
    original = (output / 'chase.original.flex').read_text()
    if hybrid.sha(output / 'chase.original.flex') != manifest['originalChaseSHA256']:
        raise ValueError('archived original changed')
    if (output / 'flex-source/control/chase.flex').read_text() != source.transform(original):
        raise ValueError('patched source differs from bounded transformation')
    for key, path in [('compilerSHA256', COMPILER), ('controlSHA256', output / 'control'),
                      ('probeSHA256', output / 'bounded-probe'),
                      ('simulatorSHA256', PROJECT / 'build/flex/control/simulator'),
                      ('robotAssetSHA256', PROJECT / 'build/flex/sim/puppybot.bin'),
                      ('robotConfigSHA256', PROJECT / 'puppybot.json'),
                      ('transformSHA256', S / 'bounded-bias-source.py')]:
        if hybrid.sha(path) != manifest[key]:
            raise ValueError(f'input or binary changed: {path}')


def main():
    if len(sys.argv) != 1:
        raise SystemExit(__doc__)
    os.chdir(PROJECT)
    with (P / '.l4-matched.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if OUTPUT.exists() or OUTPUT.is_symlink():
            raise ValueError('build output exists; preserve and inspect')
        if shutil.disk_usage(P).free < 12 * 1024**3:
            raise ValueError('at least 12 GiB free is required')
        worktree = hybrid.source_hashes(PROJECT / 'flex')
        compiler = hybrid.sha(COMPILER); simulator = hybrid.sha(PROJECT / 'build/flex/control/simulator')
        asset = hybrid.sha(PROJECT / 'build/flex/sim/puppybot.bin'); config = hybrid.sha(PROJECT / 'puppybot.json')
        transform = hybrid.sha(S / 'bounded-bias-source.py')
        OUTPUT.mkdir()
        shutil.copytree(PROJECT / 'flex', OUTPUT / 'flex-source', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        if hybrid.source_hashes(OUTPUT / 'flex-source') != worktree or hybrid.source_hashes(PROJECT / 'flex') != worktree:
            raise ValueError('worktree changed while snapshotting')
        chase = OUTPUT / 'flex-source/control/chase.flex'; original = chase.read_text()
        (OUTPUT / 'chase.original.flex').write_text(original)
        chase.write_text(source.transform(original))
        shutil.copyfile(PROJECT / 'flex/tests/bounded-bias-native.flex', OUTPUT / 'flex-source/control/bounded-probe.flex')
        patched = hybrid.source_hashes(OUTPUT / 'flex-source')
        for input_name, output_name in (('main.flex', 'control'), ('bounded-probe.flex', 'bounded-probe')):
            subprocess.run([str(COMPILER), str(OUTPUT / 'flex-source/control' / input_name), '-o', str(OUTPUT / output_name)],
                           cwd=PROJECT, check=True, timeout=120)
        subprocess.run([str(OUTPUT / 'bounded-probe')], cwd=PROJECT, check=True, timeout=10)
        manifest = {'originalChaseSHA256': hybrid.sha(OUTPUT / 'chase.original.flex'),
                    'compilerSHA256': compiler, 'simulatorSHA256': simulator, 'robotAssetSHA256': asset,
                    'robotConfigSHA256': config, 'transformSHA256': transform,
                    'controlSHA256': hybrid.sha(OUTPUT / 'control'), 'probeSHA256': hybrid.sha(OUTPUT / 'bounded-probe'), 'originalSourceFiles': worktree,
                    'patchedSourceFiles': patched, 'windowActions': 30,
                    'scope': 'isolated experimental build; not a physical-safety claim'}
        verify(OUTPUT, manifest)
        (OUTPUT / 'inputs.json').write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n')
        print(json.dumps({'status': 'built', 'controlSHA256': manifest['controlSHA256'], 'output': str(OUTPUT)}))


if __name__ == '__main__':
    main()
