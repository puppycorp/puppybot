# Drop self-imitation games without any kept (weighted) row from a PVDATA04 chase shard, so no batch is empty.
# Usage: keep.py SHARD_DATA OUT_DATA; keeps at least one validation game by moving the last fitting game over.
import sys
import numpy as np

src, out = sys.argv[1], sys.argv[2]
raw = np.memmap(src, dtype=np.uint8, mode='r')
magic = bytes(raw[:8]); assert magic == b'PVDATA01'
n, fit, t = (int(x) for x in np.frombuffer(raw[8:32], dtype=np.int64))
game = t * 21212
assert raw.size == 32 + n * game
def kept(i):
    rows = np.frombuffer(raw[32 + i * game + t * 21168:32 + (i + 1) * game], dtype=np.uint8).reshape(t, 44)
    return np.frombuffer(rows[:, 40:44].tobytes(), dtype=np.float32).max() > 0
fits = [i for i in range(fit) if kept(i)]
vals = [i for i in range(fit, n) if kept(i)]
if not vals and len(fits) >= 2:
    vals = [fits.pop()]
if not fits or not vals:
    print(f'{src}: skip ({len(fits)} fitting, {len(vals)} validation kept)')
    sys.exit(3)
order = fits + vals
with open(out, 'wb') as f:
    f.write(magic + np.array([len(order), len(fits), t], dtype=np.int64).tobytes())
    for i in order:
        f.write(raw[32 + i * game:32 + (i + 1) * game].tobytes())
print(f'{src}: kept {len(fits)} fitting and {len(vals)} validation of {n}')
