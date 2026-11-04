#!/usr/bin/env python3
"""Compare saved back-and-forth counts with the terminal window included.

Reads only the fresh selection's saved JSON and decision logs. It does not
rerun a policy, independently attest execution, or repair the failed monitor.
"""
import hashlib
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / 'build/flex/sim/levels-v2/pitch82/fresh-policy-selection-v2'
MONITOR = ROOT / 'build/flex/sim/levels-v2/pitch82/fresh-policy-selection-monitored-v2'
ARMS = ('control', 'treatment', 'teacher')
GAMES = 32
HORIZON = 300


def marks(rows, start, include_final):
    """Union action indices covered by the existing 20-action heuristic."""
    poses = [start] + [row['state']['pose'] for row in rows]
    speeds = [row['action'][1] for row in rows]
    for pose in poses:
        if len(pose) < 3 or any(not isinstance(x, (int, float)) or isinstance(x, bool) or
                                not math.isfinite(x) for x in pose[:3]):
            raise ValueError('invalid pose')
    if any(not isinstance(x, (int, float)) or isinstance(x, bool) or not math.isfinite(x) for x in speeds):
        raise ValueError('invalid action')
    signs = [(x > 0) - (x < 0) for x in speeds]
    flagged = set()
    end = len(rows) + int(include_final)
    for t in range(20, end):
        flips = sum(signs[k] * signs[k - 1] < 0 for k in range(t - 19, t))
        turn = abs((poses[t][2] - poses[t - 20][2] + math.pi) % (2 * math.pi) - math.pi)
        if flips >= 4 and math.dist(poses[t][:2], poses[t - 20][:2]) < .25 and turn < math.radians(45):
            flagged.update(range(t - 20, t))
    return flagged


def stable_read(path):
    """Read a regular file and reject basic evidence changes during the read."""
    before = path.stat()
    if not path.is_file() or path.is_symlink():
        raise ValueError('invalid evidence file: ' + str(path))
    data = path.read_bytes()
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError('evidence changed during read: ' + str(path))
    return data


def audit():
    monitor_bytes = stable_read(MONITOR / 'monitor-result.json')
    if json.loads(monitor_bytes) != {'status': 'failed', 'reason': 'unsafe or vanished output directory'}:
        raise ValueError('original failed monitor status changed')
    report_bytes = stable_read(OUTPUT / 'report.json')
    report = json.loads(report_bytes)
    identity = hashlib.sha256()
    results = {}
    for level in range(1, 6):
        task = 'L' + str(level); results[task] = {}
        for arm in ARMS:
            old_total = 0; full_total = 0; changed = []
            for i in range(GAMES):
                seed = 7820000 + i
                name = str(seed) if arm != 'teacher' else 'expert-' + str(i % 8)
                directory = OUTPUT / task / arm / str(i // 8) / name
                blob = {}
                for filename in ('result.json', 'chase.jsonl', 'decisions.jsonl'):
                    data = stable_read(directory / filename)
                    identity.update(str((directory / filename).relative_to(ROOT)).encode() + b'\0')
                    identity.update(hashlib.sha256(data).digest())
                    blob[filename] = data
                result = json.loads(blob['result.json'])
                events = blob['chase.jsonl'].splitlines()
                rows = [json.loads(line) for line in blob['decisions.jsonl'].splitlines()]
                if len(rows) != HORIZON or result['seed'] != seed or result['steps'] != HORIZON:
                    raise ValueError('incorrect seed or horizon: ' + str(directory))
                start = json.loads(events[0])['robot']
                old = marks(rows, start, False); full = marks(rows, start, True)
                if len(old) != result['backForthSteps'] or not old.issubset(full):
                    raise ValueError('saved original count differs: ' + str(directory))
                extra = len(full - old)
                if extra: changed.append({'seed': seed, 'additionalActions': extra})
                old_total += len(old); full_total += len(full)
            prior = report['tasks'][task]['results'][arm]
            if not math.isclose(prior['backForthShare'], old_total / (GAMES * HORIZON), abs_tol=1e-14):
                raise ValueError('saved report share differs: ' + task + '/' + arm)
            results[task][arm] = {'originalActions': old_total, 'inclusiveActions': full_total,
                                  'additionalActions': full_total - old_total,
                                  'inclusiveShare': full_total / (GAMES * HORIZON),
                                  'changedGames': changed}
    if stable_read(OUTPUT / 'report.json') != report_bytes or stable_read(MONITOR / 'monitor-result.json') != monitor_bytes:
        raise ValueError('report or monitor changed during audit')
    return {'status': 'read_only_posthoc_diagnostic', 'originalMonitor': 'failed',
            'reportSHA256': hashlib.sha256(report_bytes).hexdigest(),
            'gameInputsSHA256': identity.hexdigest(), 'results': results,
            'scope': ('Training-family saved games, 20-action truth-pose heuristic, '
                      'not a monitor pass, complete loop measure, policy improvement or physical result')}


if __name__ == '__main__':
    print(json.dumps(audit(), sort_keys=True, indent=2, allow_nan=False))
