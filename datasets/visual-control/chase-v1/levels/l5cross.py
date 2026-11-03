# For doorway-drill bricks past the doorway (level 4 since 2 Nov 2026, level 5 before): does the robot reach the brick's room before the next brick, how soon, and
# is the brick delivered. Usage: l5cross.py GAME_DIR...; decisions.jsonl line i is chase step i.
import sys, json, struct
entered, delivered, total, steps = 0, 0, 0, []
for d in sys.argv[1:]:
    raw = open(d + '/scene/environment.bin', 'rb').read()
    n = struct.unpack_from('<q', raw, 8)[0]
    wall = [struct.unpack_from('<d', raw, 256 + i * 128 + 48)[0] for i in range(n) if raw[256 + i * 128:].startswith(b'Wall.partition')][0]
    xs = [json.loads(l)['state']['pose'][0] for l in open(d + '/decisions.jsonl')]
    events = [json.loads(l) for l in open(d + '/chase.jsonl')]
    for i, e in enumerate(events):
        if (e['brick'][0] > wall) == (e['robot'][0] > wall):
            continue
        end = events[i + 1]['step'] if i + 1 < len(events) else len(xs)
        total += 1
        side = e['brick'][0] > wall
        hit = next((t for t in range(e['step'], min(end, len(xs))) if (xs[t] > wall) == side), None)
        if hit is not None:
            entered += 1; steps.append(hit - e['step'])
        delivered += i + 1 < len(events)
steps.sort()
print(f'{total} past-doorway bricks: robot entered their room for {entered}, median {steps[len(steps)//2] if steps else "-"} steps; delivered {delivered}')
