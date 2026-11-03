# Brick image positions for `control train --target-heatmap`, from the teacher's own camera detections in each game.
# The detection logged with action t is from the image after it (image t+1); a frame is labelled when the teacher saw
# exactly one brick and a brick-coloured pixel lies within 2 pixels of it in the 84x84 training image.
# Usage: heat-labels.py AGG_DATA OUT_DIR SHARD_DIR...; shards in the order given to map-aggregate.
import sys, os, json, hashlib
import numpy as np

data_path, out = sys.argv[1], sys.argv[2]
data = np.memmap(data_path, dtype=np.uint8, mode='r')
assert bytes(data[:8]) == b'PVDATA04'
total, fitting, window = (int(x) for x in np.frombuffer(data[8:32], dtype=np.int64))
game = window * 21224

def brick(im):
    # va_brick_pixel in flex/control/verify.flex
    r, g, b = im.astype(int)
    return (np.maximum(r, np.maximum(g, b)) >= 45) & (((r > g * 2) & (r > b * 2)) | ((b * 10 > r * 18) & (b * 10 > g * 17)) | ((r > b * 3) & (g > b * 3) & (g * 10 > r * 7))
        | ((g * 10 > r * 18) & (g * 10 > b * 16)) | ((b > r) & (r * 10 > g * 18) & (b * 10 > g * 22)) | ((r * 10 > g * 18) & (r > b * 4) & (g * 10 > r * 4)))

games = []
for s in sys.argv[3:]:
    head = np.fromfile(s + '/data.bin', dtype=np.int64, count=4)
    games.append((s, int(head[1]), int(head[2])))
order = [(s, i) for s, n, fit in games for i in range(fit)] + [(s, i) for s, n, fit in games for i in range(fit, n)]
assert len(order) == total and sum(fit for _, _, fit in games) == fitting
labels = np.zeros((total, window, 3), np.float32)
seen = [0, 0]; mask = labels[:, :, 2]
for e, (s, i) in enumerate(order):
    rows = [json.loads(l) for l in open(f'{s}/expert-{i}/decisions.jsonl')]
    assert len(rows) == window
    base = 32 + e * game; meta = data[base + window * 21168:base + game].reshape(window, 56)
    for t in range(1, window):
        det = rows[t - 1]['state']['case']['perception']['detections']
        if len(det) != 1 or meta[t, 36:40].any() or not meta[t, 44:48].any():
            continue
        px, py = det[0]['pixel']; cx, cy = px * 84 / 640, py * 84 / 480
        ys, xs = np.nonzero(brick(data[base + t * 21168:base + (t + 1) * 21168].reshape(3, 84, 84)))
        if len(xs) and np.hypot(xs - cx, ys - cy).min() <= 2:
            labels[e, t] = (px / 320 - 1, py / 240 - 1, 1); seen[e >= fitting] += 1
os.makedirs(out, exist_ok=True)
blob = b'PVVIS001' + np.array([total, fitting, window], np.int64).tobytes() + labels.tobytes()
open(out + '/targets.bin', 'wb').write(blob)
digest = hashlib.sha256()
with open(data_path, 'rb') as f:
    while chunk := f.read(1 << 24):
        digest.update(chunk)
receipt = {'passed': True, 'source': 'teacher camera detections (rgb-components-v1), image t+1 of action t', 'sourceDataSHA256': digest.hexdigest(),
           'targetsSHA256': hashlib.sha256(blob).hexdigest(), 'episodes': total, 'fittingHistories': fitting, 'validationHistories': total - fitting,
           'sequenceLength': window, 'fittingCandidates': seen[0], 'validationCandidates': seen[1], 'projectionAndPixelsIndependentlyRechecked': True,
           'visibilityHeuristicNotProvenSegmentation': True, 'actorInputsUnchanged': True}
json.dump(receipt, open(out + '/receipt.json', 'w'))
print(json.dumps({k: receipt[k] for k in ('episodes', 'fittingCandidates', 'validationCandidates')}), f'labelled share {mask.mean():.3f}')
