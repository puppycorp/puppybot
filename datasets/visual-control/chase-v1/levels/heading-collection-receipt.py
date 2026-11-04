#!/usr/bin/env python3
"""Verify the monitored full heading collection's fixed-path completion receipt."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
OUTPUT = P / 'search-dagger-heading'
MONITORED = P / 'heading-full-collection-monitored-v1'
MONITOR_SCRIPT = ROOT / 'flex/tests/monitored-heading-collection.py'


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as file:
        for block in iter(lambda: file.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def clean_status(path):
    value = json.loads(path.read_text())
    if (type(value.get('clientExit')) is not int or value['clientExit'] != 0 or
            'signal' not in value or value['signal'] is not None or value.get('timedOut') is not False or
            value.get('remainingWorkersTerminated') is not False or
            type(value.get('processGroup')) is not int or value['processGroup'] <= 0):
        raise ValueError(f'unclean supervisor status: {path}')


def source_pins():
    paths = {'source.monitor': MONITOR_SCRIPT, 'source.verifier': Path(__file__).resolve(),
             'source.telemetry': ROOT / 'flex/tests/monitored-visual-v4-smoke.py',
             'source.supervisor': ROOT / 'flex/tests/run-physical-hidden-trial.py',
             'source.rescan': ROOT / 'flex/tests/run-physical-rescan-trial.py',
             'source.cleanup': ROOT / 'flex/tests/run-physical-hybrid-trial.py',
             'source.collector': ROOT / 'datasets/visual-control/chase-v1/levels/run-heading-rollin.py'}
    return {name: digest(path) for name, path in paths.items()}


def snapshot():
    report = json.loads((OUTPUT / 'collection-report.json').read_text())
    if report.get('status') != 'passed' or report.get('mode') != 'full':
        raise ValueError('full collection report is not passed')
    monitor = json.loads((MONITORED / 'monitor-result.json').read_text())
    if monitor.get('status') != 'passed':
        raise ValueError('GPU monitor did not pass')
    paths = {'report': OUTPUT / 'collection-report.json', 'inputs': OUTPUT / 'inputs.json',
             'catalogs': P / 'heading-rollin-full-catalogs/catalogs.json',
             'monitorResult': MONITORED / 'monitor-result.json',
             'outerStatus': MONITORED / 'outer-monitor/supervisor-result.json',
             'telemetry': MONITORED / 'telemetry.jsonl', 'launch': MONITORED / 'launch.json'}
    optional_paths = {}
    clean_status(paths['outerStatus'])
    for arm in ('control', 'treatment'):
        for index in range(4):
            root = OUTPUT / f'{arm}-L5'
            status = root / f'monitor-{index}/supervisor-result.json'; clean_status(status)
            paths[f'{arm}.{index}.status'] = status
            for name in ('data.bin', 'map.bin', 'report.json'):
                paths[f'{arm}.{index}.{name}'] = root / f'shard-{index}' / name
            shard = root / f'shard-{index}'
            for name, path in (('shard.log', shard.with_suffix('.log')), ('policy.log', shard / 'policy.log')):
                optional_paths[f'{arm}.{index}.{name}'] = path
            for name in ('weights.bin', 'policy', 'receipt.json'):
                paths[f'{arm}.{index}.policy.{name}'] = shard / 'policy' / name
            kernels = sorted(path for path in (shard / 'policy/kernels').iterdir() if path.is_file())
            if not kernels: raise ValueError(f'policy snapshot kernels missing: {shard}')
            for kernel in kernels:
                paths[f'{arm}.{index}.policy.kernels.{kernel.name}'] = kernel
            for episode in range(32):
                game = shard / f'expert-{episode}'
                for name in ('result.json', 'decisions.jsonl', 'chase.jsonl', 'scene/case.json', 'scene/environment.bin'):
                    paths[f'{arm}.{index}.{episode}.{name}'] = game / name
                optional_paths[f'{arm}.{index}.{episode}.native.log'] = game / 'native.log'
    result = {name: digest(path) for name, path in paths.items()}
    result.update({name: digest(path) if path.exists() else None for name, path in optional_paths.items()})
    result.update(source_pins())
    return result


def verify():
    receipt = json.loads((MONITORED / 'completion.json').read_text())
    if receipt.get('status') != 'passed' or receipt.get('hashes') != snapshot():
        raise ValueError('monitored full-collection receipt differs')
    launch = json.loads((MONITORED / 'launch.json').read_text())
    if launch.get('sourcePins') != source_pins():
        raise ValueError('monitoring source pins changed during collection')
    return receipt
