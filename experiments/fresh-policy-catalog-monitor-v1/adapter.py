#!/usr/bin/env python3
"""Strict catalog-aware inventory adapter for a future selection monitor.

No seed, plan, executor or launch is supplied here. A future independently
reviewed runner must call require_fresh before creating any outputs, pin this
file and verify.py in its frozen manifest, and reinstall this adapter in each
monitor and final-audit subprocess. This cannot repair an earlier monitor.
"""
import importlib.util
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
POSTRUN = ROOT / 'experiments/fresh-policy-postrun-v1/verify.py'
spec = importlib.util.spec_from_file_location('strict_catalog_inventory', POSTRUN)
postrun = importlib.util.module_from_spec(spec)
spec.loader.exec_module(postrun)

PROTECTED = tuple(P / name for name in (
    'fresh-policy-selection-plan-v1.json', 'fresh-policy-selection-v1',
    'fresh-policy-selection-monitored-v1', 'fresh-policy-selection-plan-v2.json',
    'fresh-policy-selection-v2', 'fresh-policy-selection-monitored-v2'))


def canonical(path):
    path = Path(path)
    if not path.is_absolute() or path.resolve(strict=False) != path:
        raise ValueError('path must be absolute and have no symlinked components')
    return path


def boundaries(output, monitored, manifest, base_dir=P):
    paths = [canonical(path) for path in (output, monitored, manifest)]
    base_dir = canonical(base_dir)
    if not base_dir.is_dir() or any(path.parent != base_dir for path in paths):
        raise ValueError('future paths must be dedicated direct children of the configured root')
    match = re.fullmatch(r'fresh-policy-selection-v([1-9][0-9]*)', paths[0].name)
    if not match or int(match.group(1)) < 3:
        raise ValueError('future output must use a new v3-or-later selection name')
    version = match.group(1)
    if (paths[1].name != f'fresh-policy-selection-monitored-v{version}' or
            paths[2].name != f'fresh-policy-selection-plan-v{version}.json'):
        raise ValueError('future output, monitor and plan versions differ')
    for i, path in enumerate(paths):
        for other in paths[i + 1:] + list(PROTECTED):
            if path == other or path in other.parents or other in path.parents:
                raise ValueError('future path overlaps a prior or sibling path')
    return paths


def require_fresh(output, monitored, manifest, base_dir=P):
    """Must run before registration; never remove or overwrite any prior path."""
    paths = boundaries(output, monitored, manifest, base_dir)
    if any(path.exists() or path.is_symlink() for path in paths):
        raise FileExistsError('future run path already exists')


def install(monitor, output, monitored, manifest, verify_plan, base_dir=P):
    """Bind the strict inventory in this process after verifying its plan.

    Call separately in each fresh monitor/final-audit subprocess. The caller's
    verify_plan must revalidate input hashes, runtime links, catalog links,
    seed/history/held-out boundaries and the saved manifest, not merely read
    a file. This adapter does not implement those checks or schedule a run.
    """
    output, monitored, manifest = boundaries(output, monitored, manifest, base_dir)
    if (Path(monitor.OUTPUT) != output or Path(monitor.MONITOR) != monitored or
            Path(monitor.MANIFEST) != manifest):
        raise ValueError('monitor paths differ from adapter configuration')
    frozen = verify_plan()
    if json.loads(manifest.read_text()) != frozen or frozen.get('status') != 'frozen_before_play':
        raise ValueError('future manifest differs')
    pins = frozen.get('files')
    if not isinstance(pins, dict):
        raise ValueError('missing source pins')
    for path in (Path(__file__).resolve(), POSTRUN):
        if pins.get(str(path)) != postrun.digest_regular(path)['sha256']:
            raise ValueError('catalog inventory implementation is not pinned')
    expected = postrun.expected_catalogs(frozen)

    def inventory(root):
        if canonical(root) != output:
            raise ValueError('inventory requested an unexpected root')
        if verify_plan() != frozen:
            raise ValueError('registered inputs changed before inventory')
        snapshot = postrun.inventory(output, expected)
        if verify_plan() != frozen:
            raise ValueError('registered inputs changed during inventory')
        return snapshot

    monitor.inventory = inventory
    return {'catalogLinks': len(expected), 'output': str(output),
            'scope': 'local catalog-aware inventory only; not execution attestation'}


if __name__ == '__main__':
    raise SystemExit('Adapter only; future selection requires independent design and review.')
