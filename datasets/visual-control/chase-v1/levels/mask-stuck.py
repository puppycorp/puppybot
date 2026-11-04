# Unlabel the teacher's back-and-forth (backforth.py's 20-action stretches) in a map-aggregate PVDATA04 file of whole
# games, so students see those frames but are not taught the loops. Actions where the robot is within NEAR m of the box,
# or of the brick while not carrying it, keep their labels: reversing to line up a pickup or delivery is needed.
# Usage: mask-stuck.py AGG_DATA [--teacher-only] SHARD_DIR...; shards in the order given to map-aggregate,
# AGG_DATA patched in place. --teacher-only leaves student-driven DAgger rows labelled: their executed loops
# are precisely where the teacher's corrective labels are needed.
import sys, json, math
import numpy as np

NEAR = 0.6
data = np.memmap(sys.argv[1], dtype=np.uint8, mode='r+')
assert bytes(data[:8]) == b'PVDATA04'
total, fitting, window = (int(x) for x in np.frombuffer(data[8:32], dtype=np.int64))
assert window == 300
game = window * 21224

def stuck(d):
    rows = [json.loads(l) for l in open(d + '/decisions.jsonl')]
    start = json.loads(open(d + '/chase.jsonl').readline())['robot']
    box = json.load(open(d + '/scene/case.json'))['container']['position']
    # The state logged with action i is the one after it; the pose before action 0 is the start event's.
    p = [start] + [r['state']['pose'] for r in rows[:-1]]; v = [(r['action'][1] > 0) - (r['action'][1] < 0) for r in rows]
    ball = [rows[0]['state']['ball']] + [r['state']['ball'] for r in rows[:-1]]
    marks = np.zeros(len(rows), bool)
    for t in range(20, len(rows)):
        flips = sum(v[k] * v[k - 1] < 0 for k in range(t - 19, t))
        turn = abs((p[t][2] - p[t - 20][2] + math.pi) % (2 * math.pi) - math.pi)
        if flips >= 4 and math.dist(p[t][:2], p[t - 20][:2]) < 0.25 and turn < math.radians(45):
            marks[t - 20:t] = True
    return marks, p, ball, box

args = sys.argv[2:]
teacher_only = bool(args and args[0] == '--teacher-only')
if teacher_only:
    args = args[1:]
games = []
for s in args:
    head = np.fromfile(s + '/data.bin', dtype=np.int64, count=4)
    student = json.load(open(s + '/report.json'))['studentDriven'] if teacher_only else False
    assert isinstance(student, bool)
    games.append((s, int(head[1]), int(head[2]), student))
order = [(s, i, student) for s, n, fit, student in games for i in range(fit)] + [(s, i, student) for s, n, fit, student in games for i in range(fit, n)]
assert len(order) == total and sum(fit for _, _, fit, _ in games) == fitting
masked, near, labelled = {}, 0, {}
for e, (s, i, student) in enumerate(order):
    if student:
        continue
    marks, p, ball, box = stuck(f'{s}/expert-{i}')
    rows = data[32 + e * game + window * 21168:32 + (e + 1) * game].reshape(window, 56)
    level = s.split('/')[-2]
    for t in np.flatnonzero(marks):
        carrying = np.frombuffer(rows[t, 24:28].tobytes(), dtype=np.float32)[0] > 0
        if math.dist(p[t][:2], box[:2]) < NEAR or (not carrying and math.dist(p[t][:2], ball[t][:2]) < NEAR):
            near += 1; continue
        rows[t, 40:44] = 0; masked[level] = masked.get(level, 0) + 1
    labelled[level] = labelled.get(level, 0) + window
data.flush()
print(json.dumps({'unlabelled': sum(masked.values()), 'keptNearBrickOrBox': near, 'share': {k: round(masked.get(k, 0) / labelled[k], 3) for k in sorted(labelled)}}))
