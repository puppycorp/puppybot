#!/usr/bin/env python3
"""Read-only re-audit after the original selection inventory rejected catalogs.

This verifier never changes the original run or its failed monitor outcome.
It admits only the exact frozen selection catalog links, without traversing
them, and checks all regular output files before and after the saved re-audit.
It is local consistency evidence, not execution or physical attestation.
"""
import hashlib
import importlib.util
import json
import os
import stat
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


retry = load('postrun_selection', ROOT / 'experiments/fresh-policy-comparison-v2/retry.py')


def expected_catalogs(frozen):
    design = frozen['design']
    tasks = design['tasks']
    if ([task['name'] for task in tasks] != ['L1', 'L2', 'L3', 'L4', 'L5'] or
            design['gamesPerArmPerLevel'] != 32):
        raise ValueError('unexpected selection design')
    expected = {}
    for task in tasks:
        level = task['level']
        if task['name'] != f'L{level}' or len(task['rows']) != 32:
            raise ValueError('unexpected task')
        for i, row in enumerate(task['rows']):
            if row['index'] != i:
                raise ValueError('unordered task scenes')
            scene = Path(row['scene'])
            if not scene.is_absolute():
                raise ValueError('relative catalog target')
            suffix = '-two-room-selection' if level >= 4 else '-selection'
            key = f"{task['name']}/catalogs/4-{i // 8}{suffix}/{i % 8}"
            expected[key] = str(scene)
    if len(expected) != 160:
        raise ValueError('catalog links are incomplete')
    return expected


def digest_regular(path):
    # O_NOFOLLOW blocks a final-component symlink. Directory enumeration and
    # stat checks narrow, but do not eliminate, concurrent path-retarget races.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError('output is not a regular file')
        digest = hashlib.sha256()
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        after = os.fstat(fd)
        identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        if identity(before) != identity(after):
            raise ValueError('output changed while hashing')
        return {'sha256': digest.hexdigest(), 'size': before.st_size}
    finally:
        os.close(fd)


def inventory(root, expected):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('missing or symlinked output root')
    links = {}; files = {}; directories = []
    def error(exc):
        raise exc
    for directory, names, filenames in os.walk(root, topdown=True, followlinks=False, onerror=error):
        parent = Path(directory)
        directories.append(str(parent.relative_to(root)))
        for name in sorted(names + filenames):
            path = parent / name
            relative = str(path.relative_to(root))
            info = path.lstat()
            if relative in expected and not stat.S_ISLNK(info.st_mode):
                raise ValueError('expected catalog link is not a link: ' + relative)
            if stat.S_ISLNK(info.st_mode):
                target = os.readlink(path)
                if relative not in expected or target != expected[relative]:
                    raise ValueError('unexpected or retargeted output link: ' + relative)
                if not path.is_dir() or path.resolve(strict=True) != Path(target):
                    raise ValueError('missing or aliased catalog target: ' + relative)
                links[relative] = target
            elif stat.S_ISDIR(info.st_mode):
                if name not in names:
                    raise ValueError('output changed during enumeration')
            elif stat.S_ISREG(info.st_mode):
                if name not in filenames:
                    raise ValueError('output changed during enumeration')
                files[relative] = digest_regular(path)
            else:
                raise ValueError('unsupported output node: ' + relative)
    if links != expected:
        raise ValueError('missing expected catalog links')
    return {'directories': sorted(directories), 'links': links, 'files': files}


def sha_json(value):
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def monitor_snapshot(root):
    names = ('launch.json', 'frozen-manifest.json', 'telemetry.jsonl', 'disk.jsonl',
             'worker.log', 'monitor-result.json', 'outer-monitor/client.log',
             'outer-monitor/supervisor-result.json')
    root = Path(root)
    return {name: digest_regular(root / name) for name in names}


def audit():
    """Run a read-only postrun audit; original monitor remains failed."""
    verifier_before = digest_regular(Path(__file__))
    frozen = retry.verify()
    if json.loads((retry.MONITOR / 'frozen-manifest.json').read_text()) != frozen:
        raise ValueError('saved monitor manifest differs')
    monitor = json.loads((retry.MONITOR / 'monitor-result.json').read_text())
    outer = json.loads((retry.MONITOR / 'outer-monitor/supervisor-result.json').read_text())
    if (monitor != {'status': 'failed', 'reason': 'unsafe or vanished output directory'} or
            outer.get('clientExit') != 1 or outer.get('signal') is not None or
            outer.get('timedOut') is not False or outer.get('remainingWorkersTerminated') is not False):
        raise ValueError('unexpected original monitor outcome')
    if (retry.MONITOR / 'completion.json').exists() or (retry.MONITOR / 'evidence.json').exists():
        raise ValueError('original monitor unexpectedly completed')
    expected = expected_catalogs(frozen)
    monitor_before = monitor_snapshot(retry.MONITOR)
    before = inventory(retry.OUTPUT, expected)
    retry.base.monitor.verify_logs(retry.MONITOR)
    saved = json.loads((retry.OUTPUT / 'report.json').read_text())
    if retry.base.reaudit(frozen) != saved:
        raise ValueError('saved comparison audit differs')
    after = inventory(retry.OUTPUT, expected)
    if (before != after or retry.verify() != frozen or monitor_before != monitor_snapshot(retry.MONITOR) or
            verifier_before != digest_regular(Path(__file__))):
        raise ValueError('evidence changed during postrun audit')
    return {'status': 'postrun_consistent_original_monitor_failed',
            'originalMonitor': monitor, 'outputInventorySHA256': sha_json(after),
            'regularFiles': len(after['files']), 'catalogLinks': len(after['links']),
            'monitorFilesSHA256': sha_json(monitor_before), 'verifierSHA256': verifier_before['sha256'], 'report': saved,
            'scope': 'later local re-audit; original monitor failed before final inventory; no execution, held-out or physical attestation'}


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review and a supervised read-only audit.')
