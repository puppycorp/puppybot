# Split doorway-drill bricks (level 4 since 2 Nov 2026, level 5 before) into same-room (level-1 style) and other-room (past the doorway) and count deliveries.
# Usage: l5split.py GAME_DIR...; the partition x comes from Wall.partition records in scene/environment.bin.
import sys, json, struct
from collections import Counter
count = Counter()
for d in sys.argv[1:]:
    raw = open(d + '/scene/environment.bin', 'rb').read()
    n = struct.unpack_from('<q', raw, 8)[0]
    xs = [struct.unpack_from('<d', raw, 256 + i * 128 + 48)[0] for i in range(n) if raw[256 + i * 128:].startswith(b'Wall.partition')]
    wall = xs[0]
    events = [json.loads(l) for l in open(d + '/chase.jsonl')]
    for i, e in enumerate(events):
        if e['event'] not in ('start', 'delivery'):
            continue
        kind = 'doorway' if (e['brick'][0] > wall) != (e['robot'][0] > wall) else 'same room'
        done = i + 1 < len(events) and events[i + 1]['event'] == 'delivery'
        count[kind, done] += 1
for kind in ('same room', 'doorway'):
    print(f'{kind}: {count[kind, True]} delivered of {count[kind, True] + count[kind, False]} bricks')
