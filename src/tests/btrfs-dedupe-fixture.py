#!/usr/bin/env python3
"""Tiny isolated Btrfs FIDEDUPERANGE fixture; never touches experiment data."""
import fcntl
import hashlib
import json
import os
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRATCH_PARENT = ROOT / 'build/flex/sim/levels-v2/pitch82'
FIDEDUPERANGE = 0xC0189436
SIZE = 2 * 1024 * 1024 + 32  # match the candidate files' non-aligned EOF shape


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dedupe(source, destination):
    with source.open('rb') as a, destination.open('r+b') as b:
        request = bytearray(struct.pack('=QQHHI', 0, SIZE, 1, 0, 0) +
                            struct.pack('=qQQiI', b.fileno(), 0, 0, 0, 0))
        fcntl.ioctl(a.fileno(), FIDEDUPERANGE, request, True)
        _, _, done, status, _ = struct.unpack_from('=qQQiI', request, 24)
        return done, status


def extent(*paths):
    result = subprocess.run(['btrfs', 'filesystem', 'du', '-s', *(str(p) for p in paths)],
                            text=True, capture_output=True, check=True)
    return result.stdout.strip()


def main():
    if subprocess.run(['stat', '-f', '-c', '%T', str(SCRATCH_PARENT)], text=True, capture_output=True, check=True).stdout.strip() != 'btrfs':
        raise ValueError('scratch parent must be on Btrfs')
    free_before = shutil.disk_usage(SCRATCH_PARENT).free
    with tempfile.TemporaryDirectory(prefix='.btrfs-dedupe-fixture-', dir=SCRATCH_PARENT) as tmp:
        root = Path(tmp); source, same, different = (root / name for name in ('source', 'same', 'different'))
        data = os.urandom(SIZE); source.write_bytes(data); same.write_bytes(data)
        changed = bytearray(data); changed[12345] ^= 1; different.write_bytes(changed)
        for p in (source, same, different):
            with p.open('rb') as f: os.fsync(f.fileno())
        original = {p.name: digest(p) for p in (source, same, different)}
        before = extent(source, same, different)
        mismatch_done, mismatch_status = dedupe(source, different)
        if mismatch_status != 1 or mismatch_done != 0 or digest(different) != original['different']:
            raise ValueError('unequal scratch file was modified or unexpectedly deduplicated')
        done, status = dedupe(source, same)
        if status != 0 or done != SIZE:
            raise ValueError(f'equal scratch range not fully deduplicated: status={status} bytes={done}')
        if {p.name: digest(p) for p in (source, same, different)} != original:
            raise ValueError('scratch bytes changed')
        after = extent(source, same, different)
    print(json.dumps({'status': 'passed', 'bytes': SIZE, 'equalBytesDeduped': done,
                      'differentStatus': mismatch_status, 'beforeExtents': before, 'afterExtents': after,
                      'freeBefore': free_before, 'freeAfterScratchCleanup': shutil.disk_usage(SCRATCH_PARENT).free,
                      'scope': 'temporary test files only; no experiment data modified'}, indent=2))


if __name__ == '__main__': main()
