#!/usr/bin/env python3
"""Verify student games survived map aggregation and teacher-only masking.

Usage: audit-mixed-students.py AGGREGATE_DIR EXPECTED_STUDENT_GAMES SHARD...
SHARD order must match the order passed to map-aggregate. Checks saved image,
all 44 original feedback/teacher-label bytes, and all map bytes for each
student game, in the aggregator's fitting-then-validation order. Source
shards must separately pass audit-multi-shards.py first.
"""
import contextlib
import json
import mmap
import struct
import sys
from pathlib import Path


def main():
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    aggregate, expected = Path(sys.argv[1]), int(sys.argv[2])
    if expected < 1:
        raise ValueError('expected student count must be positive')
    with contextlib.ExitStack() as stack:
        def mapping(path):
            file = stack.enter_context(path.open('rb'))
            return stack.enter_context(mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ))

        merged, merged_map = mapping(aggregate / 'data.bin'), mapping(aggregate / 'map.bin')
        if merged[:8] != b'PVDATA04' or merged_map[:8] != b'PVMAP001':
            raise ValueError('invalid aggregate magic')
        total, fitting, horizon = struct.unpack_from('<qqq', merged, 8)
        if horizon != 300 or struct.unpack_from('<qqq', merged_map, 8) != (total, fitting, horizon):
            raise ValueError('aggregate data/map header mismatch')
        if len(merged) != 32 + total * horizon * 21224 or len(merged_map) != 32 + total * horizon * 144:
            raise ValueError('aggregate data/map length mismatch')
        shards = []
        for name in sys.argv[3:]:
            path = Path(name)
            report = json.loads((path / 'report.json').read_text())
            source, source_map = mapping(path / 'data.bin'), mapping(path / 'map.bin')
            n, fit, window = struct.unpack_from('<qqq', source, 8)
            if source[:8] != b'PVDATA01' or source_map[:8] != b'PVMAP001' or window != horizon or struct.unpack_from('<qqq', source_map, 8) != (n, fit, window):
                raise ValueError(f'invalid source header: {path}')
            if n != report['episodes'] or fit != report['trainingEpisodes'] or not isinstance(report.get('studentDriven'), bool):
                raise ValueError(f'source report mismatch: {path}')
            shards.append((path, source, source_map, n, fit, report['studentDriven']))
        order = [(s, i) for s in shards for i in range(s[4])] + [(s, i) for s in shards for i in range(s[4], s[3])]
        if len(order) != total or sum(s[4] for s in shards) != fitting:
            raise ValueError('source order or game count mismatch')
        checked = 0
        for target, (shard, episode) in enumerate(order):
            path, source, source_map, _, _, student = shard
            if not student:
                continue
            source_start = 32 + episode * horizon * 21212
            target_start = 32 + target * horizon * 21224
            image_bytes = horizon * 21168
            if source[source_start:source_start + image_bytes] != merged[target_start:target_start + image_bytes]:
                raise ValueError(f'student images differ: {path}, game {episode}')
            source_rows, target_rows = source_start + image_bytes, target_start + image_bytes
            for step in range(horizon):
                a, b = source_rows + step * 44, target_rows + step * 56
                if source[a:a + 44] != merged[b:b + 44]:
                    raise ValueError(f'student feedback or teacher label differs: {path}, game {episode}, step {step}')
                if struct.unpack_from('<f', merged, b + 40)[0] != 1:
                    raise ValueError(f'masked student correction: {path}, game {episode}, step {step}')
            a, b = 32 + episode * horizon * 144, 32 + target * horizon * 144
            if source_map[a:a + horizon * 144] != merged_map[b:b + horizon * 144]:
                raise ValueError(f'student coverage map differs: {path}, game {episode}')
            checked += 1
        if checked != expected:
            raise ValueError(f'expected {expected} student games; checked {checked}')
        print(json.dumps({'status': 'passed', 'studentGames': checked, 'stepsPerGame': horizon,
                          'scope': 'student images, original 44-byte rows and coverage maps preserved'}, sort_keys=True))


if __name__ == '__main__':
    main()
