# Advantage-weighted regression weights for sampled-action chase shards (collect --sample-actions).
# Each row's weight holds its discounted return G. The baseline is the mean G of rows with the same level,
# carrying state and 50-step slice of the game; z = (G - baseline) / max(std over the same group, FLOOR), so
# groups where nearly every return is 0 cannot blow up. Training takes only 0/1 weights, so each row is kept
# (weight 1) with probability exp(min(z, CAP) - CAP): AWR weights exp(z) capped at exp(CAP), up to a constant.
# Usage: awr.py FLOOR CAP SEED LEVEL=SHARD_DATA [...]; writes rl.bin beside each shard and prints a summary.
import sys
from collections import defaultdict
import numpy as np

floor, cap, seed = float(sys.argv[1]), float(sys.argv[2]), int(sys.argv[3])
specs = [a.split('=', 1) for a in sys.argv[4:]]
rng = np.random.default_rng(seed)
FRAME, ROW = 21168, 44

def rows(raw, t, g):
    start = 32 + g * t * (FRAME + ROW) + t * FRAME
    return raw[start:start + t * ROW].reshape(t, ROW)

shards = []
for level, path in specs:
    raw = np.fromfile(path, dtype=np.uint8)
    assert bytes(raw[:8]) == b'PVDATA01'
    n, fit, t = (int(x) for x in np.frombuffer(raw[8:32].tobytes(), dtype=np.int64))
    G = np.stack([np.frombuffer(rows(raw, t, g)[:, 40:44].tobytes(), dtype=np.float32) for g in range(n)]).astype(np.float64)
    carry = np.stack([np.frombuffer(rows(raw, t, g)[:, 24:28].tobytes(), dtype=np.float32) for g in range(n)]) > 0.5
    shards.append((level, path, raw, n, t, G, carry))

groups = defaultdict(list)
for level, _, _, n, t, G, carry in shards:
    slice_ = np.broadcast_to(np.arange(t) // 50, (n, t))
    for key in zip(np.full(G.size, level), carry.ravel(), slice_.ravel(), G.ravel()):
        groups[key[:3]].append(key[3])
stats = {k: (np.mean(v), max(np.std(v), floor)) for k, v in groups.items()}

weights = []
for level, path, raw, n, t, G, carry in shards:
    slice_ = np.broadcast_to(np.arange(t) // 50, (n, t))
    mean = np.vectorize(lambda c, s: stats[(level, c, s)][0])(carry, slice_)
    std = np.vectorize(lambda c, s: stats[(level, c, s)][1])(carry, slice_)
    weights.append(np.exp(np.minimum((G - mean) / std, cap) - cap))
kept = []
for (level, path, raw, n, t, G, carry), w in zip(shards, weights):
    out = raw.copy()
    keep = rng.random(w.shape) < w
    for g in range(n):
        rows(out, t, g)[:, 40:44] = np.frombuffer(np.where(keep[g], 1, 0).astype(np.float32).tobytes(), dtype=np.uint8).reshape(t, 4)
    kept.append(keep.mean())
    out.tofile(path[:-len('data.bin')] + 'rl.bin')
all_w = np.concatenate([w.ravel() for w in weights])
print(f'rows {all_w.size} keep probability p10 {np.quantile(all_w, 0.1):.3f} p50 {np.median(all_w):.3f} p90 {np.quantile(all_w, 0.9):.2f} '
      f'kept {np.mean(kept):.2f} effective share {all_w.sum() ** 2 / (all_w ** 2).sum() / all_w.size:.2f}')
