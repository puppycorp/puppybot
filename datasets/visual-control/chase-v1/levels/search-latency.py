# Compare first search episodes in two sets of saved chase games, matched by seed.
# Usage: search-latency.py BASELINE_DIR CANDIDATE_DIR
# A first return phase marks the end of search. Unfinished searches are censored
# at the recorded horizon; the capped mean is not a mean over completed searches.
import glob
import hashlib
import json
import math
import statistics
import sys
from pathlib import Path


def load(root):
    games = {}
    for name in glob.glob(f'{root}/**/result.json', recursive=True):
        directory = Path(name).parent
        result = json.loads(Path(name).read_text())
        seed = result['seed']
        if seed in games:
            raise ValueError(f'duplicate seed {seed} in {root}')
        start = json.loads((directory / 'chase.jsonl').read_text().splitlines()[0])
        with (directory / 'decisions.jsonl').open() as f:
            states = [json.loads(line)['state'] for line in f]
        phases = [state['findReturn']['phase'] for state in states]
        if len(phases) != result['steps'] or start['event'] != 'start':
            raise ValueError(f'incomplete game: {directory}')
        first = next((i for i, phase in enumerate(phases) if phase == 'return'), len(phases))
        closest = min(math.dist(s['pose'][:2], s['ball'][:2]) for s in states[:first]) if first else 0.0
        scene = tuple(hashlib.sha256((directory / 'scene' / name).read_bytes()).hexdigest()
                      for name in ('case.json', 'environment.bin'))
        games[seed] = (result, start, first, phases.count('search'), closest, scene)
    if not games:
        raise ValueError(f'no games in {root}')
    return games


def summarize(name, games):
    values = list(games.values())
    print(f'{name}: games={len(values)} first_returns={sum(v[2] < v[0]["steps"] for v in values)} '
          f'capped_first_mean={statistics.mean(v[2] for v in values):.2f} '
          f'capped_first_median={statistics.median(v[2] for v in values):.2f} '
          f'mean_search_steps={statistics.mean(v[3] for v in values):.2f} '
          f'deliveries={sum(v[0]["deliveries"] for v in values)}')


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__ or 'usage: search-latency.py BASELINE_DIR CANDIDATE_DIR')
    left, right = (load(root) for root in sys.argv[1:])
    if left.keys() != right.keys():
        raise ValueError('game seeds do not match')
    for seed in left:
        a, b = left[seed], right[seed]
        if a[1] != b[1] or a[5] != b[5] or any(a[0].get(k) != b[0].get(k) for k in ('steps', 'level', 'levelPlacement')):
            raise ValueError(f'scene, initial placement, horizon or level mismatch at seed {seed}')
    summarize(sys.argv[1], left)
    summarize(sys.argv[2], right)
    print('first return only in first:', sorted(s for s in left if left[s][2] < left[s][0]['steps'] and right[s][2] == right[s][0]['steps']))
    print('first return only in second:', sorted(s for s in left if right[s][2] < right[s][0]['steps'] and left[s][2] == left[s][0]['steps']))
    for seed in sorted(left):
        if left[seed][2] == left[seed][0]['steps'] or right[seed][2] == right[seed][0]['steps']:
            print(f'{seed}: first_return_steps={left[seed][2]},{right[seed][2]} '
                  f'closest_before_return_m={left[seed][4]:.2f},{right[seed][4]:.2f}')


if __name__ == '__main__':
    main()
