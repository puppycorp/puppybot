# Average PUPV0001 weight files of models fine-tuned from one start (a model soup); headers must match.
# Usage: soup.py OUT IN...
import sys
import numpy as np
raws = [np.fromfile(p, dtype=np.uint8) for p in sys.argv[2:]]
start = int(np.frombuffer(raws[0][16:24].tobytes(), dtype=np.int64)[0])
assert bytes(raws[0][:8]) == b'PUPV0001' and all(len(r) == len(raws[0]) and (r[:start] == raws[0][:start]).all() for r in raws)
mean = np.mean([np.frombuffer(r[start:].tobytes(), dtype=np.float32).astype(np.float64) for r in raws], axis=0)
out = raws[0].copy(); out[start:] = np.frombuffer(mean.astype(np.float32).tobytes(), dtype=np.uint8)
out.tofile(sys.argv[1])
