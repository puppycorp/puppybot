#!/usr/bin/env python3
"""Compare the unaffected whole games of two ordered PVDATA04 aggregates.

Arguments: CONTROL TREATMENT OLD_SHARD NEW_SHARD [OLD_SHARD NEW_SHARD ...].
Use the same shard pair for every unchanged slot. Replaced slots must have the
same episode and fitting counts. This checks exact data and map bytes, including
weights, for every unchanged game; it does not assess collection provenance.
"""
import contextlib
import json
import mmap
import struct
import sys
from pathlib import Path


def order(pairs):
    fit, validation, unchanged, replaced = [], [], 0, 0
    for old, new in pairs:
        a = json.loads((old / 'report.json').read_text())
        b = json.loads((new / 'report.json').read_text())
        n, f = a['episodes'], a['trainingEpisodes']
        if (n, f) != (b['episodes'], b['trainingEpisodes']) or not 0 <= f <= n:
            raise ValueError(f'slot counts differ: {old}, {new}')
        same = old.resolve() == new.resolve()
        unchanged += n if same else 0
        replaced += 0 if same else n
        fit.extend([same] * f)
        validation.extend([same] * (n - f))
    return fit + validation, len(fit), unchanged, replaced


def compare(control, treatment, pairs):
    flags, fitting, unchanged, replaced = order(pairs)
    with contextlib.ExitStack() as stack:
        def mapping(path):
            file = stack.enter_context(path.open('rb'))
            return stack.enter_context(mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ))

        datasets = []
        for directory in (control, treatment):
            data, maps = mapping(directory / 'data.bin'), mapping(directory / 'map.bin')
            header = (len(flags), fitting, 300)
            if (data[:8] != b'PVDATA04' or maps[:8] != b'PVMAP001'
                    or struct.unpack_from('<qqq', data, 8) != header
                    or struct.unpack_from('<qqq', maps, 8) != header
                    or len(data) != 32 + len(flags) * 300 * 21224
                    or len(maps) != 32 + len(flags) * 300 * 144):
                raise ValueError(f'invalid aggregate: {directory}')
            datasets.append((data, maps))
        for i, same in enumerate(flags):
            if not same:
                continue
            for j, width in enumerate((300 * 21224, 300 * 144)):
                start = 32 + i * width
                if datasets[0][j][start:start + width] != datasets[1][j][start:start + width]:
                    raise ValueError(f'unchanged game {i} differs in {"data" if j == 0 else "map"}')
    return {'status': 'passed', 'games': len(flags), 'fittingGames': fitting,
            'unchangedGames': unchanged, 'replacedGames': replaced,
            'scope': 'whole data and map bytes of unchanged slots, including weights'}


def main():
    if len(sys.argv) < 5 or len(sys.argv) % 2 != 1:
        raise SystemExit(__doc__)
    paths = [Path(p) for p in sys.argv[3:]]
    print(json.dumps(compare(Path(sys.argv[1]), Path(sys.argv[2]),
                             list(zip(paths[::2], paths[1::2]))), sort_keys=True))


if __name__ == '__main__':
    main()
