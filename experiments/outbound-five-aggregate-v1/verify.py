#!/usr/bin/env python3
"""Independently compare every derived episode against its source bytes."""
import hashlib
import mmap
import os
import struct
from pathlib import Path


ONE = struct.pack('<f', 1.0)
ZERO = b'\0' * 4


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def dims(data, magic, count, fitting, length, stride):
    if (len(data) != 32 + count * length * stride or data[:8] != magic or
            struct.unpack_from('<3q', data, 8) != (count, fitting, length)):
        raise ValueError('dataset header, split or size mismatch')


def same_range(a, aoff, b, boff, n):
    for start in range(0, n, 4 * 1024 * 1024):
        width = min(4 * 1024 * 1024, n - start)
        if a[aoff + start:aoff + start + width] != b[boff + start:boff + start + width]:
            raise ValueError('preserved episode bytes differ')


def verify(base_path, base_map_path, teacher_path, teacher_map_path, out_path, out_map_path,
           selected, *, old_count=1024, old_fit=928, teacher_count=12, teacher_fit=9,
           length=300, image=21168, raw_row=44, row=56, map_row=144):
    """Require all original rows byte-equal and exact selected teacher conversion.

    `selected` contains (source episode, first-consumption action), in final
    order. This verifies construction only; separate provenance checks must
    establish that the identities are qualified fitting episodes.
    """
    if (len(selected) < 1 or len({i for i, _ in selected}) != len(selected) or
            any(type(i) is not int or type(cutoff) is not int or
                not 0 <= i < teacher_fit or not 1 <= cutoff <= length for i, cutoff in selected)):
        raise ValueError('invalid selected teacher identities')
    paths = [Path(p) for p in (base_path, base_map_path, teacher_path, teacher_map_path, out_path, out_map_path)]
    handles = []
    maps = []
    try:
        for path in paths:
            if path.is_symlink() or not path.is_file():
                raise ValueError('dataset is not a regular non-symlink file')
            h = path.open('rb'); handles.append(h); maps.append(mmap.mmap(h.fileno(), 0, access=mmap.ACCESS_READ))
        base, bmap, teach, tmap, out, omap = maps
        n = old_count + len(selected); fit = old_fit + len(selected)
        dims(base, b'PVDATA04', old_count, old_fit, length, image + row)
        dims(bmap, b'PVMAP001', old_count, old_fit, length, map_row)
        dims(teach, b'PVDATA01', teacher_count, teacher_fit, length, image + raw_row)
        dims(tmap, b'PVMAP001', teacher_count, teacher_fit, length, map_row)
        dims(out, b'PVDATA04', n, fit, length, image + row)
        dims(omap, b'PVMAP001', n, fit, length, map_row)
        rstride = length * (image + raw_row); ostride = length * (image + row); mstride = length * map_row
        for i in range(old_count):
            j = i if i < old_fit else i + len(selected)
            same_range(base, 32 + i * ostride, out, 32 + j * ostride, ostride)
            same_range(bmap, 32 + i * mstride, omap, 32 + j * mstride, mstride)
        for j, (source, cutoff) in enumerate(selected, old_fit):
            a, b = 32 + source * rstride, 32 + j * ostride
            same_range(teach, a, out, b, length * image)
            same_range(tmap, 32 + source * mstride, omap, 32 + j * mstride, mstride)
            for step in range(length):
                x = a + length * image + step * raw_row
                y = b + length * image + step * row
                raw = teach[x:x + raw_row]
                if raw[40:44] not in (ZERO, ONE):
                    raise ValueError('teacher source weight not binary')
                expected = raw[:40] + (ZERO if step >= cutoff else raw[40:44]) + ONE + raw[28:36]
                if out[y:y + row] != expected:
                    raise ValueError('teacher label, history or mask mismatch')
        return {'episodes': n, 'fitting': fit, 'preservedEpisodes': old_count,
                'teacherEpisodes': len(selected), 'length': length}
    finally:
        for m in maps: m.close()
        for h in handles: h.close()
