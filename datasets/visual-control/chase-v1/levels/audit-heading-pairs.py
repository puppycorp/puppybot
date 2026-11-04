#!/usr/bin/env python3
"""Compare paired shard games or the complete aggregate validation suffix.

Usage: audit-heading-pairs.py shard CONTROL TREATMENT INDEX [INDEX ...]
       audit-heading-pairs.py aggregate CONTROL TREATMENT

Directories contain data.bin and map.bin. Production defaults are 32/30/300
for shards and 1024/928/300 for aggregates. For a smaller pilot, pass BOTH
--games N and --fitting N after the subcommand; horizon remains 300. This is a
byte comparison, not an audit of collection provenance or training history.
"""
import argparse
import contextlib
import hashlib
import json
import os
import struct
from pathlib import Path


HORIZON = 300
SHARD_DEFAULT = (32, 30)
AGGREGATE_DEFAULT = (1024, 928)
CHUNK = 1024 * 1024


def signature(stream):
    s = os.fstat(stream.fileno())
    return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns


def open_pair(stack, left, right, name, magic, games, fitting, width):
    streams = [stack.enter_context((directory / name).open('rb')) for directory in (left, right)]
    states = [signature(stream) for stream in streams]
    if states[0][:2] == states[1][:2]:
        raise ValueError(f'{name} must be two independent files')
    expected = magic + struct.pack('<3q', games, fitting, HORIZON)
    for stream, state in zip(streams, states):
        if stream.read(32) != expected or state[2] != 32 + games * HORIZON * width:
            raise ValueError(f'invalid {name} header or length: {stream.name}')
    return streams, states


def compare_bytes(streams, offset, size, label):
    for stream in streams:
        stream.seek(offset)
    digest = hashlib.sha256()
    remaining = size
    while remaining:
        amount = min(CHUNK, remaining)
        left, right = (stream.read(amount) for stream in streams)
        if len(left) != amount or len(right) != amount or left != right:
            raise ValueError(f'{label} differs or is truncated')
        digest.update(left)
        remaining -= amount
    return digest.hexdigest()


def dimensions(games, fitting, limit):
    if type(games) is not int or type(fitting) is not int or not 2 <= games <= limit or not 1 <= fitting < games:
        raise ValueError('invalid game/fitting dimensions')


def compare_shard(left, right, indices, games=SHARD_DEFAULT[0], fitting=SHARD_DEFAULT[1]):
    left, right = Path(left), Path(right)
    dimensions(games, fitting, 128)
    if not indices or any(type(i) is not int or not 0 <= i < games for i in indices) or len(set(indices)) != len(indices):
        raise ValueError('episode indices must be unique and in range')
    with contextlib.ExitStack() as stack:
        data, ds = open_pair(stack, left, right, 'data.bin', b'PVDATA01', games, fitting, 21212)
        maps, ms = open_pair(stack, left, right, 'map.bin', b'PVMAP001', games, fitting, 144)
        checked = []
        for index in indices:
            row = {'index': index, 'split': 'fitting' if index < fitting else 'validation'}
            for name, streams, width in (('dataSHA256', data, 21212), ('mapSHA256', maps, 144)):
                size = HORIZON * width
                row[name] = compare_bytes(streams, 32 + index * size, size, f'episode {index} {name}')
            checked.append(row)
        if any(signature(s) != state for s, state in zip(data + maps, ds + ms)):
            raise ValueError('shard file changed while comparing')
    return {'status': 'passed', 'games': games, 'fittingGames': fitting, 'horizon': HORIZON,
            'episodes': checked, 'scope': 'selected whole shard data and map bytes only; collection provenance is not established'}


def compare_validation(left, right, games=AGGREGATE_DEFAULT[0], fitting=AGGREGATE_DEFAULT[1]):
    left, right = Path(left), Path(right)
    dimensions(games, fitting, 1024)
    with contextlib.ExitStack() as stack:
        data, ds = open_pair(stack, left, right, 'data.bin', b'PVDATA04', games, fitting, 21224)
        maps, ms = open_pair(stack, left, right, 'map.bin', b'PVMAP001', games, fitting, 144)
        result = {}
        for name, streams, width in (('dataSHA256', data, 21224), ('mapSHA256', maps, 144)):
            per_game = HORIZON * width
            result[name] = compare_bytes(streams, 32 + fitting * per_game, (games - fitting) * per_game, f'validation {name}')
        if any(signature(s) != state for s, state in zip(data + maps, ds + ms)):
            raise ValueError('aggregate file changed while comparing')
    return {'status': 'passed', 'games': games, 'fittingGames': fitting, 'validationGames': games - fitting,
            'horizon': HORIZON, **result,
            'scope': 'complete validation suffix of aggregate data and map; fitting games and provenance not checked'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest='mode', required=True)
    for name in ('shard', 'aggregate'):
        p = modes.add_parser(name)
        p.add_argument('--games', type=int); p.add_argument('--fitting', type=int)
        p.add_argument('control', type=Path); p.add_argument('treatment', type=Path)
        if name == 'shard':
            p.add_argument('indices', type=int, nargs='+')
    args = parser.parse_args()
    if (args.games is None) != (args.fitting is None):
        parser.error('--games and --fitting must be supplied together')
    default = SHARD_DEFAULT if args.mode == 'shard' else AGGREGATE_DEFAULT
    games, fitting = default if args.games is None else (args.games, args.fitting)
    if args.mode == 'shard':
        report = compare_shard(args.control, args.treatment, args.indices, games, fitting)
    else:
        report = compare_validation(args.control, args.treatment, games, fitting)
    print(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    main()
