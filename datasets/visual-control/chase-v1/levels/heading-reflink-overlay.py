#!/usr/bin/env python3
"""Prototype: privately reflink an aggregate, then replace student game slots.

This library has no production CLI. It writes only a new private staging
directory, rechecks source identity and bytes, audits every slot and atomically
publishes without replacement. Validation equivalence between two arms and
source/model provenance require separate audits before any training.
"""
import ctypes
import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import stat
import struct
import subprocess
import tempfile
from pathlib import Path


FICLONE = 0x40049409
HORIZON = 300
IMAGE = 21168
OLD_WIDTH = 21212
NEW_WIDTH = 21224
MAP_WIDTH = 144
PER_GAME_HEADROOM = 512 * 1024 * 1024  # CoW extent and metadata slack, not a disk reservation


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''): h.update(block)
    return h.hexdigest()


def physical_map(path):
    output = subprocess.run(['filefrag', '-v', str(path)], check=True, capture_output=True, text=True).stdout
    spans = []
    for line in output.splitlines():
        found = re.match(r'^\s*\d+:\s*(\d+)\.\.\s*(\d+):\s*(\d+)\.\.\s*(\d+):', line)
        if not found: continue
        first, last, physical_first, physical_last = map(int, found.groups())
        if physical_first <= 0 or last - first != physical_last - physical_first:
            raise ValueError('physical mapping unavailable')
        if spans and spans[-1][1] + 1 == first and spans[-1][3] + 1 == physical_first:
            spans[-1] = (spans[-1][0], last, spans[-1][2], physical_last)
        else:
            spans.append((first, last, physical_first, physical_last))
    if not spans: raise ValueError('physical mapping is empty')
    return spans


def stat_signature(s):
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_mode, s.st_uid, s.st_gid, s.st_nlink)


def signature(path):
    if path.is_symlink(): raise ValueError(f'symlink input is not permitted: {path}')
    s = path.stat()
    if not stat.S_ISREG(s.st_mode): raise ValueError(f'input is not a regular file: {path}')
    return stat_signature(s)


def header(path, magic, width):
    with path.open('rb') as f: raw = f.read(32)
    if len(raw) != 32 or raw[:8] != magic:
        raise ValueError(f'invalid magic: {path}')
    n, fitting, horizon = struct.unpack_from('<qqq', raw, 8)
    if not 2 <= n <= 1024 or not 1 <= fitting < n or horizon != HORIZON or path.stat().st_size != 32 + n * horizon * width:
        raise ValueError(f'invalid dimensions: {path}')
    return n, fitting


def clone(source, target, expected):
    with source.open('rb') as src, target.open('xb') as dst:
        if stat_signature(os.fstat(src.fileno())) != expected:
            raise ValueError('source identity changed before clone')
        fcntl.ioctl(dst.fileno(), FICLONE, src.fileno())
        dst.flush(); os.fsync(dst.fileno())


def write_at(fd, data, offset):
    view = memoryview(data)
    while view:
        n = os.pwrite(fd, view, offset)
        if n <= 0: raise OSError('short write to new overlay')
        view = view[n:]; offset += n


def student_game(data, episode):
    stride = HORIZON * OLD_WIDTH; start = 32 + episode * stride
    images_size = HORIZON * IMAGE
    images = os.pread(data, images_size, start)
    rows = os.pread(data, HORIZON * 44, start + images_size)
    if len(images) != images_size or len(rows) != HORIZON * 44:
        raise ValueError('truncated source game')
    out = bytearray(HORIZON * NEW_WIDTH); out[:images_size] = images
    for i in range(HORIZON):
        old = rows[i * 44:(i + 1) * 44]; position = images_size + i * 56
        steering, speed, weight = struct.unpack_from('<2f4xf', old, 28)
        if not all(math.isfinite(x) and abs(x) <= 1 for x in (steering, speed)) or weight != 1:
            raise ValueError('invalid or masked student label')
        out[position:position + 44] = old
        out[position + 44:position + 48] = struct.pack('<f', 1)
        out[position + 48:position + 56] = old[28:36]
    return out


def audit(base, stage, mapping, n):
    for name, width in (('data.bin', NEW_WIDTH), ('map.bin', MAP_WIDTH)):
        with (base / name).open('rb') as old, (stage / name).open('rb') as new:
            if old.read(32) != new.read(32): raise ValueError('aggregate headers differ')
            for index in range(n):
                size = HORIZON * width
                a, b = old.read(size), new.read(size)
                if len(a) != size or len(b) != size: raise ValueError('truncated aggregate')
                if index not in mapping:
                    if a != b: raise ValueError(f'unchanged game differs: {index} {name}')
                else:
                    shard, episode = mapping[index]
                    if name == 'data.bin':
                        with (shard / 'data.bin').open('rb') as source: expected = student_game(source.fileno(), episode)
                    else:
                        with (shard / 'map.bin').open('rb') as source:
                            expected = os.pread(source.fileno(), size, 32 + episode * size)
                    if b != expected: raise ValueError(f'replaced game differs: {index} {name}')


def overlay(base, shards, output, fit_offset, validation_offset, floor_bytes, validation_peer=None):
    base, output = Path(base), Path(output); shards = [Path(s) for s in shards]
    if output.exists() or output.is_symlink(): raise ValueError('output exists; retain and inspect')
    if not shards: raise ValueError('at least one source shard is required')
    if shutil.disk_usage(output.parent).free < floor_bytes + PER_GAME_HEADROOM: raise ValueError('disk reserve exhausted')
    n, fit = header(base / 'data.bin', b'PVDATA04', NEW_WIDTH)
    if header(base / 'map.bin', b'PVMAP001', MAP_WIDTH) != (n, fit): raise ValueError('base data/map mismatch')
    dimensions = []
    for shard in shards:
        dims = header(shard / 'data.bin', b'PVDATA01', OLD_WIDTH)
        if header(shard / 'map.bin', b'PVMAP001', MAP_WIDTH) != dims: raise ValueError('source data/map mismatch')
        dimensions.append(dims)
    fitting = sum(f for _, f in dimensions); validating = sum(x - f for x, f in dimensions)
    if not 0 <= fit_offset <= fit - fitting or not fit <= validation_offset <= n - validating:
        raise ValueError('replacement slots do not fit split')
    paths = [base / name for name in ('data.bin', 'map.bin')] + [s / name for s in shards for name in ('data.bin', 'map.bin', 'report.json')]
    if len({p.resolve() for p in paths}) != len(paths): raise ValueError('duplicate input path')
    pins = {str(p): {'stat': signature(p), 'sha256': digest(p)} for p in paths}
    if len({pins[str(path)]['stat'][:2] for path in paths}) != len(paths):
        raise ValueError('distinct source paths must not share an inode')
    if any(signature(path) != pins[str(path)]['stat'] for path in paths):
        raise ValueError('input changed while pinning')
    if header(base / 'data.bin', b'PVDATA04', NEW_WIDTH) != (n, fit) or header(base / 'map.bin', b'PVMAP001', MAP_WIDTH) != (n, fit):
        raise ValueError('base header changed while pinning')
    for shard, dims in zip(shards, dimensions):
        if header(shard / 'data.bin', b'PVDATA01', OLD_WIDTH) != dims or header(shard / 'map.bin', b'PVMAP001', MAP_WIDTH) != dims:
            raise ValueError('source header changed while pinning')
        report = json.loads((shard / 'report.json').read_text())
        if (report.get('complete') is not True or report.get('studentDriven') is not True or
                (report.get('episodes'), report.get('trainingEpisodes'), report.get('sequenceLength')) != (*dims, HORIZON) or
                report.get('dataSHA256') != pins[str(shard / 'data.bin')]['sha256'] or
                report.get('mapSHA256') != pins[str(shard / 'map.bin')]['sha256']):
            raise ValueError('source student report or checksum differs')
    if any(signature(path) != pins[str(path)]['stat'] for path in paths):
        raise ValueError('input changed during pinned header check')
    stage = Path(tempfile.mkdtemp(prefix=f'.{output.name}.partial-', dir=output.parent))
    mapping = {}; fit_index, validation_index = fit_offset, validation_offset; published = False
    try:
        for name in ('data.bin', 'map.bin'):
            clone(base / name, stage / name, pins[str(base / name)]['stat'])
        target_data = os.open(stage / 'data.bin', os.O_RDWR | os.O_CLOEXEC)
        try:
            target_map = os.open(stage / 'map.bin', os.O_RDWR | os.O_CLOEXEC)
            try:
                for shard, (count, train) in zip(shards, dimensions):
                    with (shard / 'data.bin').open('rb') as data, (shard / 'map.bin').open('rb') as maps:
                        for file, path in ((data, shard / 'data.bin'), (maps, shard / 'map.bin')):
                            if stat_signature(os.fstat(file.fileno())) != pins[str(path)]['stat']:
                                raise ValueError('source shard identity changed')
                        for i in range(count):
                            if shutil.disk_usage(output.parent).free < floor_bytes + PER_GAME_HEADROOM: raise ValueError('disk reserve exhausted')
                            if i < train:
                                index = fit_index; fit_index += 1
                            else:
                                index = validation_index; validation_index += 1
                            mapping[index] = (shard, i)
                            game = student_game(data.fileno(), i)
                            map_bytes = os.pread(maps.fileno(), HORIZON * MAP_WIDTH, 32 + i * HORIZON * MAP_WIDTH)
                            if len(map_bytes) != HORIZON * MAP_WIDTH: raise ValueError('truncated source map')
                            write_at(target_data, game, 32 + index * HORIZON * NEW_WIDTH)
                            write_at(target_map, map_bytes, 32 + index * HORIZON * MAP_WIDTH)
                            if shutil.disk_usage(output.parent).free < floor_bytes: raise ValueError('disk reserve crossed after game write')
                os.fsync(target_data); os.fsync(target_map)
            finally:
                os.close(target_map)
        finally:
            os.close(target_data)
        if len(mapping) != fitting + validating: raise ValueError('overlapping slot mapping')
        audit(base, stage, mapping, n)
        for path in paths:
            if signature(path) != pins[str(path)]['stat'] or digest(path) != pins[str(path)]['sha256']:
                raise ValueError(f'input changed: {path}')
        validation_status = 'not_checked'
        peer_pins = {}
        if validation_peer is not None:
            peer = Path(validation_peer)
            peer_pins = {str(peer / name): {'stat': signature(peer / name), 'sha256': digest(peer / name)} for name in ('data.bin', 'map.bin')}
            for name, width, magic in (('data.bin', NEW_WIDTH, b'PVDATA04'), ('map.bin', MAP_WIDTH, b'PVMAP001')):
                if header(peer / name, magic, width) != (n, fit): raise ValueError('peer validation dimensions differ')
                offset = 32 + fit * HORIZON * width; size = (n - fit) * HORIZON * width
                with (peer / name).open('rb') as a, (stage / name).open('rb') as b:
                    a.seek(offset); b.seek(offset)
                    while size:
                        amount = min(size, 1024 * 1024); x, y = a.read(amount), b.read(amount)
                        if len(x) != amount or x != y: raise ValueError('paired validation differs')
                        size -= amount
            for name in ('data.bin', 'map.bin'):
                path = peer / name
                if signature(path) != peer_pins[str(path)]['stat'] or digest(path) != peer_pins[str(path)]['sha256']:
                    raise ValueError('paired validation input changed')
            validation_status = 'byte_equal_at_check'
        receipt = {'status': 'prototype_only', 'games': n, 'fittingGames': fit, 'replacedFittingGames': fitting,
                   'replacedValidationGames': validating, 'unchangedGames': n - len(mapping), 'inputPins': pins,
                   'slotMapping': [{'target': index, 'sourceShard': str(shard), 'sourceEpisode': episode}
                                   for index, (shard, episode) in sorted(mapping.items())],
                   'dataSHA256': digest(stage / 'data.bin'), 'mapSHA256': digest(stage / 'map.bin'),
                   'pairedValidation': validation_status, 'validationPeerPins': peer_pins,
                   'scope': 'all output slots checked; source/model provenance and native equivalence require separate audits'}
        with (stage / 'manifest.json').open('x') as file:
            json.dump(receipt, file, sort_keys=True, indent=2); file.write('\n'); file.flush(); os.fsync(file.fileno())
        dirfd = os.open(stage, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try: os.fsync(dirfd)
        finally: os.close(dirfd)
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.renameat2(-100, os.fsencode(stage), -100, os.fsencode(output), 1) != 0:
            raise OSError(ctypes.get_errno(), 'atomic no-replace publication failed')
        published = True
        parentfd = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try: os.fsync(parentfd)
        finally: os.close(parentfd)
    except BaseException as error:
        if published:
            raise RuntimeError(f'overlay published at {output}; durability unconfirmed, inspect before retry: {error}') from error
        raise RuntimeError(f'overlay failed; private partial retained at {stage}: {error}') from error
    return receipt
