#!/usr/bin/env python3
"""Audit or deduplicate exactly three pre-reviewed training-data copies.

Default `--check` performs only reads and reports current identity, byte
comparisons, process observations, Btrfs extents and free space. `--execute`
uses FIDEDUPERANGE on only the hard-coded destination files, preserving every
path and byte. Execute only after independent review and with related work idle.
The shared lock covers cooperating workflows, not every possible process.
"""
import argparse
import fcntl
import hashlib
import json
import os
import shutil
import stat
import struct
import subprocess
import sys
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[4]
P = PROJECT / 'build/flex/sim/levels-v2/pitch82'
A = P / 'search-dagger-l35-4workers/data/data.bin'
B = P / 'search-dagger-l4-matched/data/data.bin'
PAIRS = ((A, P / 'search-dagger-l35-4workers/student-s0/data.bin', '6ab86898f321508af3001267e96cff2d81b6ec489bd42cafd3ee17ea28ac28d3'),
         (A, P / 'search-dagger-l4-matched/control-s0/data.bin', '6ab86898f321508af3001267e96cff2d81b6ec489bd42cafd3ee17ea28ac28d3'),
         (B, P / 'search-dagger-l4-matched/treatment-s0/data.bin', 'ab37d6937c4e83dbcdd05787dccc8ee55db6acc0695cd5c3ae5780a1347c1611'))
SIZE = 6520012832
CHUNK = 16 * 1024 * 1024
FIDEDUPERANGE = 0xC0189436
HOST_PID_NAMESPACE = 'pid:[4026531836]'


def verify_host_visibility(pid_namespace, init_namespace, init_comm, init_uid, namespace_pids, effective_uid):
    # This machine uses systemd in the kernel's initial PID namespace. A
    # container-local /proc can make an otherwise clean lsof scan misleading.
    if (pid_namespace != HOST_PID_NAMESPACE or init_namespace != HOST_PID_NAMESPACE or
            init_comm != 'systemd' or init_uid != 0 or len(namespace_pids) != 1 or effective_uid != 0):
        raise ValueError('host-root PID visibility not established; refusing process audit or dedupe')


def require_host_visibility():
    lines = Path('/proc/self/status').read_text().splitlines()
    matches = [line for line in lines if line.startswith('NSpid:')]
    if len(matches) != 1:
        raise ValueError('cannot verify PID namespace nesting')
    values = matches[0].split()[1:]
    if not values or not all(value.isdigit() for value in values):
        raise ValueError('invalid NSpid record')
    verify_host_visibility(os.readlink('/proc/self/ns/pid'), os.readlink('/proc/1/ns/pid'),
                           Path('/proc/1/comm').read_text().strip(), Path('/proc/1').stat().st_uid, values, os.geteuid())


def signature(st):
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_mode, st.st_uid, st.st_gid, st.st_nlink)


def process_check(paths, identities):
    result = subprocess.run(['lsof', '-nP', '-w', '-t', '--', *(str(p) for p in paths)], capture_output=True, text=True)
    if result.returncode not in (0, 1) or result.stderr.strip():
        raise ValueError(f'lsof could not complete: {result.stderr.strip()}')
    try:
        pids = {int(line) for line in result.stdout.splitlines() if line}
    except ValueError as error:
        raise ValueError('unexpected lsof output') from error
    if pids - {os.getpid()}:
        raise ValueError(f'candidate files open by processes: {sorted(pids - {os.getpid()})}')
    # Inspect all visible processes as root. Processes that vanish are harmless
    # races; an inaccessible surviving process fails closed.
    watched = set(identities)
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit() or int(proc.name) == os.getpid():
            continue
        try:
            proc.stat()
            for fd in (proc / 'fd').iterdir():
                try:
                    st = fd.stat()
                except FileNotFoundError:
                    continue
                if (st.st_dev, st.st_ino) in watched:
                    raise ValueError(f'candidate fd open by process {proc.name}')
            for line in (proc / 'maps').read_text(errors='strict').splitlines():
                fields = line.split(maxsplit=5)
                if len(fields) < 5 or not fields[4].isdigit(): continue
                major, minor = (int(x, 16) for x in fields[3].split(':'))
                if (os.makedev(major, minor), int(fields[4])) in watched:
                    raise ValueError(f'candidate mapped by process {proc.name}')
        except ProcessLookupError:
            continue
        except FileNotFoundError:
            if proc.exists():
                raise ValueError(f'cannot inspect existing process {proc.name}')
        except PermissionError as error:
            raise ValueError(f'cannot inspect process {proc.name}') from error


def compare(left, right, expected):
    left.seek(0); right.seek(0); a = hashlib.sha256(); b = hashlib.sha256(); total = 0
    while True:
        x = left.read(CHUNK); y = right.read(CHUNK)
        if x != y: raise ValueError('candidate byte comparison failed')
        if not x: break
        a.update(x); b.update(y); total += len(x)
    if total != SIZE or a.hexdigest() != expected or b.hexdigest() != expected:
        raise ValueError('candidate size or SHA-256 differs')
    return a.hexdigest()


def extents(paths):
    run = subprocess.run(['btrfs', 'filesystem', 'du', '-s', *(str(p) for p in paths)], capture_output=True, text=True, check=True)
    return run.stdout.strip()


def dedupe(source, destination):
    offset = 0
    while offset < SIZE:
        length = min(CHUNK, SIZE - offset)
        request = bytearray(struct.pack('=QQHHI', offset, length, 1, 0, 0) +
                            struct.pack('=qQQiI', destination.fileno(), offset, 0, 0, 0))
        fcntl.ioctl(source.fileno(), FIDEDUPERANGE, request, True)
        _, _, done, status, _ = struct.unpack_from('=qQQiI', request, 24)
        if status != 0 or done != length:
            raise ValueError(f'dedupe stopped at {offset}: status={status}, bytes={done}, expected={length}')
        offset += length
    return offset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(); mode.add_argument('--check', action='store_true'); mode.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    require_host_visibility()
    if subprocess.run(['stat', '-f', '-c', '%T', str(P)], text=True, capture_output=True, check=True).stdout.strip() != 'btrfs':
        raise ValueError('candidate filesystem is not Btrfs')
    paths = list(dict.fromkeys(path for a, b, _ in PAIRS for path in (a, b)))
    with (P / '.l4-matched.lock').open('r+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if shutil.disk_usage(P).free < 32 * 1024**3:
            raise ValueError('less than 32 GiB free')
        handles = {}; before = {}
        try:
            for path in paths:
                flags = os.O_CLOEXEC | os.O_NOFOLLOW | (os.O_RDWR if args.execute and path not in (A, B) else os.O_RDONLY)
                fd = os.open(path, flags); file = os.fdopen(fd, 'r+b' if flags & os.O_RDWR else 'rb'); handles[path] = file
                st = os.fstat(fd)
                if not stat.S_ISREG(st.st_mode) or st.st_size != SIZE or st.st_nlink != 1 or path.is_symlink():
                    raise ValueError(f'unsafe candidate identity: {path}')
                if signature(path.stat()) != signature(st): raise ValueError('path identity changed while opening')
                before[path] = signature(st)
            if len({v[0] for v in before.values()}) != 1 or len({v[:2] for v in before.values()}) != len(paths):
                raise ValueError('candidate files must be distinct inodes on one device')
            process_check(paths, [v[:2] for v in before.values()])
            free_before = shutil.disk_usage(P).free; extent_before = extents(paths)
            comparisons = []
            for source, target, expected in PAIRS:
                actual = compare(handles[source], handles[target], expected)
                comparisons.append({'source': str(source), 'target': str(target), 'sourceAndTargetSHA256': actual, 'bytes': SIZE})
            if any(signature(os.fstat(handles[p].fileno())) != before[p] or signature(p.stat()) != before[p] for p in paths):
                raise ValueError('candidate changed during checks')
            process_check(paths, [v[:2] for v in before.values()])
            print(json.dumps({'event': 'checked', 'mode': 'execute' if args.execute else 'check', 'freeBytes': free_before,
                              'extents': extent_before, 'candidates': {str(p): before[p] for p in paths}, 'comparisons': comparisons,
                              'scope': 'exact bytes and SHA-256 checked; process scan is a point-in-time observation'}, sort_keys=True), flush=True)
            if args.execute:
                for source, target, expected in PAIRS:
                    current = {p: signature(os.fstat(handles[p].fileno())) for p in (source, target)}
                    if any(current[p][:3] != before[p][:3] or current[p][5:] != before[p][5:] or signature(p.stat()) != current[p] for p in current):
                        raise ValueError('candidate path, inode, size or permissions changed before pair')
                    compare(handles[source], handles[target], expected)
                    if any(signature(os.fstat(handles[p].fileno())) != current[p] or signature(p.stat()) != current[p] for p in current):
                        raise ValueError('candidate changed during pair comparison')
                    process_check(paths, [v[:2] for v in before.values()])
                    amount = dedupe(handles[source], handles[target])
                    compare(handles[source], handles[target], expected)
                    print(json.dumps({'event': 'deduped', 'source': str(source), 'target': str(target), 'bytes': amount}, sort_keys=True), flush=True)
                for source, target, expected in PAIRS:
                    compare(handles[source], handles[target], expected)
                for path in paths:
                    after = signature(os.fstat(handles[path].fileno())); current = signature(path.stat())
                    if after[:3] != before[path][:3] or after[5:] != before[path][5:] or current[:3] != after[:3] or current[5:] != after[5:]:
                        raise ValueError('candidate path, inode, size or permissions changed')
                process_check(paths, [v[:2] for v in before.values()])
                print(json.dumps({'event': 'verified', 'freeBytes': shutil.disk_usage(P).free, 'extents': extents(paths),
                                  'scope': 'all five original paths, sizes, permissions, hashes and byte comparisons rechecked'}, sort_keys=True), flush=True)
        finally:
            for file in handles.values(): file.close()


if __name__ == '__main__': main()
