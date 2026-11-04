#!/usr/bin/env python3
"""Decode a completed native-control argv journal as base64 byte strings.

The initial argv is read from the running control process. Child records are
execve intent captured immediately before fork; they do not prove that execve
succeeded, which binary was loaded, what libraries ran, or the environment.
"""
import base64
import hashlib
import json
import struct
import sys
from pathlib import Path


def audit(path):
    data = path.read_bytes()
    if data[:8] != b'PBARGV01':
        raise ValueError('invalid argv journal header')
    at = 8; records = []; done = False
    while at < len(data):
        if len(data) - at < 16:
            raise ValueError('truncated argv record')
        kind, count = struct.unpack_from('<2q', data, at); at += 16
        if kind == 2:
            if count != 0 or at != len(data) or not records:
                raise ValueError('invalid argv footer')
            done = True
            break
        if kind not in (0, 1) or not 1 <= count <= 128 or (not records and kind != 0) or (records and kind != 1):
            raise ValueError('invalid argv record sequence')
        args = []
        for _ in range(count):
            if len(data) - at < 8:
                raise ValueError('truncated argument size')
            size, = struct.unpack_from('<q', data, at); at += 8
            if size < 0 or size > len(data) - at:
                raise ValueError('invalid argument size')
            arg = data[at:at + size]; at += size
            if b'\0' in arg:
                raise ValueError('embedded NUL in argv')
            args.append(base64.b64encode(arg).decode('ascii'))
        records.append({'kind': 'control' if kind == 0 else 'child_exec_intent', 'argvBase64': args})
    if not done:
        raise ValueError('argv journal is incomplete')
    return {'status': 'completed_argv_journal', 'sha256': hashlib.sha256(data).hexdigest(), 'records': records,
            'scope': 'control argv and parent-side child exec intent only; actual exec success, cwd, environment, loaded executables and runtime identity are not independently established'}


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    print(json.dumps(audit(Path(sys.argv[1])), sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, struct.error) as error:
        raise SystemExit(f'Invalid argv journal: {error}')
