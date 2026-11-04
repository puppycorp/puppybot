#!/usr/bin/env python3
"""Experimental explicit scene guard; callers must consume returned bytes.

This module is not integrated into the existing control or trainer.
"""
import hashlib
import json
import math
import os
import re
import stat
from pathlib import Path


HASH = re.compile(r'^[0-9a-f]{64}$')
GAMES = 32


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


def start_pose(value):
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError('invalid start pose')
    if any(type(x) not in (int, float) or not math.isfinite(x) for x in value):
        raise ValueError('invalid start pose')
    return tuple(float(x) for x in value)


def read_snapshot(path, limit):
    # Resolve catalog and file symlinks once; subsequent users must use the
    # returned bytes rather than reopening this mutable path.
    target = Path(path).resolve(strict=True)
    fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit or before.st_size < 1:
            raise ValueError('invalid or oversized scene file')
        chunks = []
        while True:
            chunk = os.read(fd, min(1048576, limit + 1))
            if not chunk:
                break
            chunks.append(chunk)
            if sum(map(len, chunks)) > limit:
                raise ValueError('scene file exceeds limit')
        after = os.fstat(fd)
        if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise ValueError('scene file changed during read')
        data = b''.join(chunks)
        if len(data) != before.st_size:
            raise ValueError('scene file size changed')
        return data
    finally:
        os.close(fd)


def load_manifest(path, expected, kind):
    if not isinstance(expected, str) or not HASH.fullmatch(expected):
        raise ValueError('pinned manifest digest required')
    raw = read_snapshot(path, 4 * 1024 * 1024)
    if digest(raw) != expected:
        raise ValueError('manifest digest differs')
    value = json.loads(raw)
    status = 'selection_not_evaluated' if kind == 'selection' else 'reserved_not_evaluated'
    if (not isinstance(value, dict) or value.get('status') != status or
            value.get('task') != 'virtual-fetch' or value.get('gamesPerLevel') != GAMES or
            not isinstance(value.get('rows'), list) or len(value['rows']) != 5 * GAMES):
        raise ValueError('manifest header differs')
    if kind == 'selection' and any(not isinstance(value.get(key), str) or not HASH.fullmatch(value[key])
                                   for key in ('generatorSourceSHA256', 'generatorSHA256')):
        raise ValueError('generator identity not pinned')
    rows = {}
    for row in value['rows']:
        if not isinstance(row, dict):
            raise ValueError('invalid row')
        level, index = row.get('level'), row.get('index')
        if type(level) is not int or type(index) is not int or not (1 <= level <= 5 and 0 <= index < GAMES):
            raise ValueError('invalid row index')
        key = (level, index)
        layout = (290 + index if level <= 3 else 291 + 2 * index) if kind == 'selection' else (
            226 + index if level <= 3 else 227 + 2 * index)
        seed = (1800000000 if kind == 'selection' else 1700000000) + level * 100 + index
        if (key in rows or type(row.get('layoutId')) is not int or row['layoutId'] != layout or
                type(row.get('seed')) is not int or row['seed'] != seed or
                row.get('scene') != f'generated/{layout}/{index % 16}'):
            raise ValueError('manifest mapping differs')
        keys = ('caseSHA256', 'environmentSHA256', 'layoutSHA256') if kind == 'selection' else (
            'caseSHA256', 'environmentSHA256')
        if any(not isinstance(row.get(key), str) or not HASH.fullmatch(row[key]) for key in keys):
            raise ValueError('invalid manifest file digest')
        if kind == 'selection':
            start_pose(row.get('startPose'))
        rows[key] = row
    if kind == 'selection':
        for level in range(1, 6):
            group = [rows[level, index] for index in range(GAMES)]
            if (len({item['environmentSHA256'] for item in group}) != GAMES or
                    len({start_pose(item['startPose']) for item in group}) != GAMES):
                raise ValueError('selection level has duplicate environment or start pose')
    return rows


class SceneGuard:
    def __init__(self, selection_path, selection_sha, heldout_path, heldout_sha):
        self.selection = load_manifest(selection_path, selection_sha, 'selection')
        self.heldout = load_manifest(heldout_path, heldout_sha, 'heldout')
        self.selection_cases = {r['caseSHA256'] for r in self.selection.values()}
        self.selection_environments = {r['environmentSHA256'] for r in self.selection.values()}
        self.heldout_cases = {r['caseSHA256'] for r in self.heldout.values()}
        self.heldout_environments = {r['environmentSHA256'] for r in self.heldout.values()}
        if self.selection_cases & self.heldout_cases or self.selection_environments & self.heldout_environments:
            raise ValueError('selection overlaps reserved heldout bytes')

    def snapshot(self, scene, purpose, *, level=None, index=None, seed=None):
        if purpose not in ('fit', 'validation', 'selection'):
            raise ValueError('explicit scene role required')
        root = Path(scene)
        files = {name: read_snapshot(root / name, 4 * 1024 * 1024 if name == 'layout.json' else 32 * 1024 * 1024)
                 for name in ('layout.json', 'case.json', 'environment.bin')}
        layout = json.loads(files['layout.json'])
        if not isinstance(layout, dict) or type(layout.get('layoutId')) is not int or type(layout.get('fit')) is not bool:
            raise ValueError('invalid layout metadata')
        selected = layout.get('selectionOnly', False)
        reserved = layout.get('reservedHeldOut', False)
        if type(selected) is not bool or type(reserved) is not bool or reserved:
            raise ValueError('invalid or reserved scene role')
        case_sha, env_sha = digest(files['case.json']), digest(files['environment.bin'])
        if case_sha in self.heldout_cases or env_sha in self.heldout_environments or 226 <= layout['layoutId'] <= 289:
            raise ValueError('heldout scene cannot be ingested')
        if purpose == 'selection':
            if type(level) is not int or type(index) is not int or (level, index) not in self.selection:
                raise ValueError('selection identity required')
            row = self.selection[level, index]
            if (type(seed) is not int or seed != row['seed'] or layout['layoutId'] != row['layoutId'] or
                    layout['fit'] is not False or not selected or layout.get('wideHeading', False) is not False or
                    layout.get('generator') != 'diverse-v1' or start_pose(layout.get('startPose')) != start_pose(row['startPose']) or
                    not isinstance(layout.get('obstacles'), list) or len(layout['obstacles']) != 1 or
                    case_sha != row['caseSHA256'] or env_sha != row['environmentSHA256'] or
                    digest(files['layout.json']) != row['layoutSHA256']):
                raise ValueError('selection scene differs from manifest')
        else:
            if (selected or 290 <= layout['layoutId'] <= 353 or case_sha in self.selection_cases or
                    env_sha in self.selection_environments or layout['fit'] is not (purpose == 'fit')):
                raise ValueError('selection scene cannot be ingested for training or validation')
        return files
