# Rocking in place: share of actions inside runs of at least six that flip drive direction every action and add up
# to at most one action's turn (right steering turns right going forward and left in reverse, so a three-point turn
# keeps turning one way and does not count), as pingPongSteps in result.json counts it, for games recorded before
# that field. Usage: pingpong.py GAME_DIR...
import sys, json
shares = []
for d in sys.argv[1:]:
    actions = [json.loads(l)['action'] for l in open(d + '/decisions.jsonl')]
    steps, chain, last, marked, turns = 0, 0, 0, -1, []
    for i, (s, v) in enumerate(actions):
        v = (v > 0) - (v < 0)
        turns = (turns + [((s > 0) - (s < 0)) * v])[-6:]
        chain = chain + 1 if v and v == -last else int(v != 0)
        last = v
        if chain >= 6 and abs(sum(turns)) <= 1:
            steps += i - max(marked, i - 6); marked = i
    shares.append(steps / max(1, len(actions)))
print(f'{len(shares)} games: ping-pong share {sum(shares) / max(1, len(shares)):.3f}, games above 20% {sum(s > 0.2 for s in shares)}')
