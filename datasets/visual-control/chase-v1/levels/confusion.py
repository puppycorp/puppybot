# Teacher label vs executed action in student-driven (DAgger) shards: the next row's feedback holds the executed action.
# Usage: confusion.py SHARD_DATA...; classes 0-2 forward left/straight/right, 3-5 reverse, 6 stop.
import sys
import numpy as np
FRAME, ROW = 21168, 44
def cls(steer, speed):
    if abs(speed) < 0.5: return 6
    return (0 if steer < -0.3 else 1 if steer < 0.3 else 2) + (0 if speed > 0 else 3)
m = np.zeros((7, 7), int)
for p in sys.argv[1:]:
    raw = np.fromfile(p, dtype=np.uint8)
    n, fit, t = (int(x) for x in np.frombuffer(raw[8:32].tobytes(), dtype=np.int64))
    for g in range(n):
        start = 32 + g * t * (FRAME + ROW) + t * FRAME
        rows = raw[start:start + t * ROW].reshape(t, ROW)
        f = np.frombuffer(rows[:, :28].tobytes(), dtype=np.float32).reshape(t, 7)
        lab = np.frombuffer(rows[:, 28:36].tobytes(), dtype=np.float32).reshape(t, 2)
        for i in range(t - 1):
            m[cls(*lab[i]), cls(*f[i + 1, :2])] += 1
names = ['fwd-L', 'straight', 'fwd-R', 'rev-L', 'rev-S', 'rev-R', 'stop']
print('teacher \\ student ' + ' '.join(f'{x:>8}' for x in names))
for i in range(7):
    if m[i].sum(): print(f'{names[i]:>17} ' + ' '.join(f'{x:8d}' for x in m[i]) + f'   recall {m[i, i] / m[i].sum():.2f}')
