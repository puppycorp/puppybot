#!/usr/bin/env python3
"""Train find-and-return goals in a declared idealized grid curriculum.

Reference layouts supply an offline shortest-completion-path teacher. Actor
inputs never contain bricks, room labels, reference walls or the random seed.
Native RGB/Ackermann trials are separate; this curriculum is not that evidence.
"""
import argparse
import heapq
import json
import math
from pathlib import Path
import time

import cv2
import numpy as np

import bootstrap
from policy import sha256
from seek_policy import FEATURE_NAMES, SeekNetwork, baseline, inputs, proposals, rank

ROOT = Path(__file__).resolve().parents[2]


def grid_cell(xy):
    col, row = np.floor((np.asarray(xy)+10)/.1).astype(int)
    return int(row), int(col)


def local(xy, spawn):
    c, s = math.cos(spawn[2]), math.sin(spawn[2])
    dx, dy = np.asarray(xy)-spawn[:2]
    return np.array([c*dx+s*dy, -s*dx+c*dy])


def field(safe, seeds):
    result = np.full(safe.shape, np.inf)
    queue = []
    for row, col, cost in seeds:
        if safe[row, col] and cost < result[row, col]:
            result[row, col] = cost
            heapq.heappush(queue, (cost, row, col))
    while queue:
        cost, row, col = heapq.heappop(queue)
        if cost > result[row, col]+1e-9:
            continue
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            r, c = row+dr, col+dc
            if 0 <= r < 200 and 0 <= c < 200 and safe[r, c] and cost+.1 < result[r, c]-1e-9:
                result[r, c] = cost+.1
                heapq.heappush(queue, (cost+.1, r, c))
    return result


class SeekGym:
    """Partial ray observations, legal grid paths, persistent map and box memory.

    This is an inexpensive training environment, not native sensor/vehicle
    physics: full-circle range 1.3 m, exact odometry, grid drive and endpoint yaw.
    """
    def __init__(self, layout, mapper):
        self.mapper = mapper
        self.truth = bootstrap.reference(layout)
        self.box = local(layout['case']['container']['position'][:2], layout['spawn'])
        bricks = [local(item['position'][:2], layout['spawn']) for item in layout['case']['objects']]
        # One hidden brick makes the first curriculum unambiguous and requires
        # leaving home. Later tasks can keep all six without changing the API.
        self.brick = next((p for p in bricks if np.linalg.norm(p) > 1.6), bricks[0])
        self.known = np.zeros_like(self.truth)
        self.blocked = np.zeros_like(self.truth)
        self.pose = np.zeros(3)
        self.visits = []
        self.task = dict(returning=False, box=None)
        self.steps = self.distance = self.seconds = 0
        self.detection_step = None
        self.passed = False
        self.safe_truth = cv2.erode(self.truth.astype(np.uint8),
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))).astype(bool)
        yy, xx = np.indices(self.truth.shape)
        radius = np.hypot(xx*.1-9.95-self.box[0], yy*.1-9.95-self.box[1])
        self.dock_cells = np.argwhere(self.safe_truth & (radius >= .36) & (radius <= .58))
        self.home_cost = field(self.safe_truth, [(int(r), int(c), 0.) for r, c in self.dock_cells])
        visibility, _ = bootstrap.visibility(self.truth, self.brick)
        rows, cols = np.nonzero(visibility & self.safe_truth & np.isfinite(self.home_cost))
        self.search_cost = field(self.safe_truth, [(int(r), int(c), float(self.home_cost[r, c])) for r, c in zip(rows, cols)])

    def observe(self):
        view, hits = bootstrap.visibility(self.truth, self.pose[:2])
        self.known |= view
        self.blocked = (self.blocked & ~view) | hits
        self.known &= ~self.blocked
        if view[grid_cell(self.box)]:
            self.task['box'] = self.box.tolist()
        if not self.task['returning'] and view[grid_cell(self.brick)]:
            self.task['returning'] = True
            self.detection_step = self.steps
        if self.task['returning'] and view[grid_cell(self.box)]:
            delta = self.box-self.pose[:2]
            error = (math.atan2(delta[1], delta[0])-self.pose[2]+math.pi)%(2*math.pi)-math.pi
            self.passed = .30 <= np.linalg.norm(delta) <= .65 and abs(error) <= math.radians(35)

    def decision(self):
        self.observe()
        self.visits.append(self.pose.tolist())
        self.seconds += 8
        captured = []
        self.mapper.__dict__['seek_capture'] = captured
        safe, _, _, _ = self.mapper.navigation(self.known.astype(np.int32)*10,
            self.blocked.astype(np.int32)*2, self.pose, self.visits)
        candidates = captured[0]
        distances = bootstrap.distances(safe, self.pose)
        candidates = proposals(candidates, safe, distances, self.pose, self.task)
        return safe, distances, candidates

    def labels(self, candidates, distances):
        costs = self.home_cost if self.task['returning'] else self.search_cost
        targets = []
        for _, goal, _ in candidates:
            row, col = grid_cell(goal[:2])
            cost = costs[row, col]+distances[(row, col)]
            risk = not self.safe_truth[row, col] or not math.isfinite(cost)
            targets.append([-min(100., cost)/20 if not risk else -5., float(risk)])
        return np.asarray(targets, np.float32)

    def step(self, goal, safe):
        start, end = grid_cell(self.pose[:2]), grid_cell(goal[:2])
        previous = {start: None}
        queue = [start]
        for row, col in queue:
            if (row, col) == end:
                break
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                r, c = row+dr, col+dc
                if 0 <= r < 200 and 0 <= c < 200 and safe[r, c] and (r, c) not in previous:
                    previous[(r, c)] = (row, col)
                    queue.append((r, c))
        if end not in previous:
            return False
        path = [end]
        while path[-1] != start:
            path.append(previous[path[-1]])
        returning = self.task['returning']
        for row, col in reversed(path[:-1]):
            next_xy = np.array([col, row])*.1-9.95
            self.distance += float(np.linalg.norm(next_xy-self.pose[:2]))
            self.pose[:2] = next_xy
            self.steps += 1
            self.seconds += .1/.15
            self.observe()
            if self.task['returning'] != returning:
                break
        else:
            self.pose[2] = goal[2]
        self.observe()
        return True


def mapper_module():
    mapper = bootstrap.module('seek_grid_mapper', ROOT/'flex/vision/discovery.py')
    source = (ROOT/'flex/vision/discovery.py').read_text()
    marker = '    candidates.sort(key=lambda item: -item[0])'
    assert source.count(marker) == 1
    exec(compile(source.replace(marker, '    seek_capture[:] = [candidates.copy()]\n'+marker), str(ROOT/'flex/vision/discovery.py'), 'exec'), mapper.__dict__)
    return mapper


def episode(generator, mapper, seed, model=None, collect=False, budget=32, teacher="oracle"):
    env = SeekGym(generator.generate(seed, 2+seed%2), mapper)
    records = []
    rng = np.random.default_rng(seed)
    for decision in range(budget):
        safe, distances, candidates = env.decision()
        if env.passed or not candidates:
            break
        x = inputs(env.known, env.blocked, env.pose, env.visits, candidates, distances, env.task)
        heuristic = baseline(candidates, distances, env.task)
        if collect:
            targets = env.labels(candidates, distances)
            if teacher == 'heuristic':
                targets[:, 0] = heuristic/(10 if env.task['returning'] else 40)
            # Keep both the teacher and ordinary explorer in the demonstrations.
            scores = targets[:, 0]-.5*targets[:, 1] if teacher == 'oracle' and rng.random() < .5 else heuristic
            ids = np.unique(np.r_[np.argsort(-scores)[:8], rng.choice(len(x), min(40, len(x)), replace=False)])
            records.append(dict(features=x[ids], targets=targets[ids], heuristic=heuristic[ids], gain=heuristic[ids],
                groups=np.full(len(ids), decision, np.int32), scenes=np.full(len(ids), seed, np.int32)))
        else:
            scores = heuristic if model is None else model.predict(x)[0]
        if not env.step(candidates[int(np.argmax(scores))][1], safe):
            break
    return dict(seed=seed, passed=bool(env.passed), found=env.task['returning'], decisions=decision+1,
        distanceM=env.distance, approximateSeconds=env.seconds, detectionGridStep=env.detection_step), records


def corpus(generator, mapper, seeds, output, teacher):
    records, episodes = [], []
    group_offset = 0
    for seed in seeds:
        result, rows = episode(generator, mapper, seed, collect=True, teacher=teacher)
        for row in rows:
            row['groups'] += group_offset
        group_offset += 32
        records.extend(rows)
        episodes.append(result)
        print(json.dumps(dict(corpusSeed=seed, found=result['found'], passed=result['passed'], decisions=result['decisions'])), flush=True)
    assert records
    data = {key: np.concatenate([row[key] for row in records]) for key in records[0]}
    np.savez_compressed(output, **data)
    return data, episodes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--teacher', choices=('oracle', 'heuristic'), default='heuristic')
    parser.add_argument('--test-seed-start', type=int, default=95000)
    parser.add_argument('--epochs', type=int, default=60)
    parser.add_argument('--train-scenes', type=int, default=24)
    parser.add_argument('--validation-scenes', type=int, default=6)
    parser.add_argument('--test-scenes', type=int, default=20)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    generator = bootstrap.module('seek_generator', ROOT/'flex/scripts/generate-layout.py')
    mapper = mapper_module()
    splits = dict(train=list(range(92000, 92000+args.train_scenes)), validation=list(range(93000, 93000+args.validation_scenes)), test=list(range(args.test_seed_start, args.test_seed_start+args.test_scenes)))
    manifest = dict(schema='puppybot.find-return-curriculum.v1', splits=splits, featureNames=FEATURE_NAMES,
        actorReferenceGeometry=False, teacher=('Successful heuristic find-and-return demonstrations; supervised imitation, not reinforcement learning' if args.teacher == 'heuristic' else 'Offline privileged shortest grid path to a first brick sighting and then box standoff; supervised imitation, not reinforcement learning'),
        approximation=SeekGym.__doc__, nativeSuccessProven=False,
        sources={str(p.relative_to(ROOT)): sha256(p) for p in (Path(__file__), ROOT/'flex/exploration/seek_policy.py', ROOT/'flex/vision/discovery.py', ROOT/'flex/scripts/generate-layout.py')})
    (args.output/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    train, train_episodes = corpus(generator, mapper, splits['train'], args.output/'train.npz', args.teacher)
    validation, validation_episodes = corpus(generator, mapper, splits['validation'], args.output/'validation.npz', args.teacher)
    bootstrap.Network = SeekNetwork
    model, initial = bootstrap.train(train, validation, args.output, args.epochs, 7)
    tests = {}
    for mode in ('heuristic', 'mlp'):
        tests[mode] = [episode(generator, mapper, seed, model if mode == 'mlp' else None)[0] for seed in splits['test']]
        print(json.dumps(dict(testPolicy=mode, successes=sum(r['passed'] for r in tests[mode]), episodes=len(tests[mode]))), flush=True)
    report = dict(schema='puppybot.find-return-training.v1', model='32-64-32-2 tanh MLP, utility/risk heads',
        parameters=sum(p.size for p in model.params.values()), gradientOptimization=True, initialValidation=initial,
        checkpointSHA256=sha256(args.output/'checkpoint.npz'), trainRows=len(train['features']), validationRows=len(validation['features']),
        trainEpisodes=train_episodes, validationEpisodes=validation_episodes, heldoutGridEpisodes=tests,
        nativeSuccessProven=False, elapsedSeconds=time.monotonic()-started)
    (args.output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(dict(trainingComplete=True, report=str(args.output/'report.json'))), flush=True)


if __name__ == '__main__':
    main()
