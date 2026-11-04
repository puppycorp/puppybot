# Linear probes of policy memory: fit ridge regression on even games, report on odd games.
# Usage: probe.py WIDTH NAME=DIR [NAME=DIR ...]; each DIR holds */memory.bin from run --record-memory.
import sys, glob, json
import numpy as np

width = int(sys.argv[1])
cols = 16 + width
TARGETS = [
    # name, kind, value(f), mask(f) over fact array F
    ('carrying', 'bin', lambda F: F[:, 5], lambda F: np.ones(len(F), bool)),
    ('brick detected now', 'bin', lambda F: F[:, 6], lambda F: F[:, 5] == 0),
    ('saw brick in last 10 steps', 'bin', lambda F: (F[:, 7] <= 10).astype(float), lambda F: F[:, 5] == 0),
    ('log steps since brick seen', 'reg', lambda F: np.log1p(F[:, 7]), lambda F: F[:, 5] == 0),
    ('turned a full circle since brick appeared', 'bin', lambda F: (F[:, 9] >= 2 * np.pi).astype(float), lambda F: (F[:, 5] == 0) & (F[:, 7] >= 300)),
    ('steps since brick appeared', 'reg', lambda F: F[:, 8], lambda F: np.ones(len(F), bool)),
    ('box forward (m)', 'reg', lambda F: F[:, 10], lambda F: np.ones(len(F), bool)),
    ('box left (m)', 'reg', lambda F: F[:, 11], lambda F: np.ones(len(F), bool)),
    ('box distance (m)', 'reg', lambda F: F[:, 12], lambda F: np.ones(len(F), bool)),
    ('room', 'bin', lambda F: F[:, 13], lambda F: F[:, 15] == F[:, 15]),
    ('brick forward (m), seen before', 'reg', lambda F: F[:, 14], lambda F: (F[:, 5] == 0) & (F[:, 7] < 300) & (F[:, 6] == 0)),
    ('brick left (m), seen before', 'reg', lambda F: F[:, 15], lambda F: (F[:, 5] == 0) & (F[:, 7] < 300) & (F[:, 6] == 0)),
]

def load(directory):
    games = []
    for path in sorted(p for d in directory.split(',') for p in glob.glob(f'{d}/**/memory.bin', recursive=True)):
        a = np.fromfile(path, dtype=np.float32).reshape(-1, cols).astype(np.float64)
        games.append(a)
    return games

def ridge(X, y, lam=1.0):
    X1 = np.hstack([X, np.ones((len(X), 1))])
    A = X1.T @ X1 + lam * np.eye(X1.shape[1]); A[-1, -1] -= lam
    return np.linalg.solve(A, X1.T @ y)

def score(train, test, name, kind, value, mask):
    Ftr = np.vstack([g[:, :16] for g in train]); Htr = np.vstack([g[:, 16:] for g in train])
    Fte = np.vstack([g[:, :16] for g in test]); Hte = np.vstack([g[:, 16:] for g in test])
    mtr, mte = mask(Ftr), mask(Fte)
    if name == 'room':  # only meaningful on two-room layouts: rows where both rooms occur in the game set
        pass
    ytr, yte = value(Ftr)[mtr], value(Fte)[mte]
    if len(ytr) < 50 or len(yte) < 50 or np.std(ytr) == 0 or np.std(yte) == 0:
        return None
    w = ridge(Htr[mtr], ytr)
    p = np.hstack([Hte[mte], np.ones((mte.sum(), 1))]) @ w
    if kind == 'reg':
        r2 = 1 - np.sum((yte - p) ** 2) / np.sum((yte - yte.mean()) ** 2)
        return ('R2', r2, len(yte))
    pos = yte > 0.5; pred = p > 0.5
    bal = 0.5 * (np.mean(pred[pos]) + np.mean(~pred[~pos])) if pos.any() and (~pos).any() else float('nan')
    return ('balanced acc', bal, len(yte))

results = {}
for spec in sys.argv[2:]:
    name, directory = spec.split('=', 1)
    games = load(directory)
    train, test = games[0::2], games[1::2]
    results[name] = {}
    for t in TARGETS:
        results[name][t[0]] = score(train, test, *t)
    results[name]['games'] = len(games)

names = list(results)
print(f"{'target':46s}" + ''.join(f'{n:>18s}' for n in names))
for t in TARGETS:
    row = f'{t[0]:46s}'
    for n in names:
        r = results[n][t[0]]
        row += f'{"-":>18s}' if r is None else f'{r[0][:3]} {r[1]:7.2f} n={r[2]:<6d}'.rjust(18)
    print(row)
print('games', {n: results[n]['games'] for n in names})
json.dump({n: {k: v for k, v in r.items()} for n, r in results.items()}, open(sys.argv[0] + '.last.json', 'w'), default=float)
