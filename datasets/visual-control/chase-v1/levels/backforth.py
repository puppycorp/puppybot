# Going back and forth without getting anywhere: share of actions inside 20-action stretches (4 s) that end under
# 0.25 m and 45 degrees from where they began with at least four drive reversals, as backForthSteps in result.json
# counts it (it also catches loops slower than ping-pong), for games recorded before that field.
# Usage: backforth.py GAME_DIR...
import sys, json, math
shares = []
for d in sys.argv[1:]:
    rows = [json.loads(l) for l in open(d + '/decisions.jsonl')]
    # The state logged with action i is the one after it; the pose before action 0 is the start event's.
    start = json.loads(open(d + '/chase.jsonl').readline())['robot']
    p = [start] + [r['state']['pose'] for r in rows[:-1]]; v = [(r['action'][1] > 0) - (r['action'][1] < 0) for r in rows]
    steps, marked = 0, -1
    for t in range(20, len(rows)):
        flips = sum(v[k] * v[k - 1] < 0 for k in range(t - 19, t))
        turn = abs((p[t][2] - p[t - 20][2] + math.pi) % (2 * math.pi) - math.pi)
        if flips >= 4 and math.dist(p[t][:2], p[t - 20][:2]) < 0.25 and turn < math.radians(45):
            steps += t - max(marked, t - 20); marked = t
    shares.append(steps / max(1, len(rows)))
print(f'{len(shares)} games: back-and-forth share {sum(shares) / max(1, len(shares)):.3f}, games above 20% {sum(s > 0.2 for s in shares)}')
