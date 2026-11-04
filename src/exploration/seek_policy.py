"""Phase-conditioned find-and-return goals, using only observed map/landmarks."""
import json
import math
import os
from pathlib import Path

import numpy as np

from policy import FEATURE_NAMES as MAP_FEATURES, Network, features, sha256

FEATURE_NAMES = MAP_FEATURES + ('returning', 'box_known', 'goal_box_distance',
    'goal_box_heading_cos', 'goal_box_heading_sin', 'robot_box_distance',
    'docking_candidate', 'goal_standoff_error')


class SeekNetwork(Network):
    def __init__(self, seed=7):
        super().__init__(seed)
        rng = np.random.default_rng(seed)
        self.params['w1'] = rng.normal(0, 1/math.sqrt(len(FEATURE_NAMES)),
                                      (len(FEATURE_NAMES), 64)).astype(np.float32)
        self.mean = np.zeros(len(FEATURE_NAMES), np.float32)
        self.std = np.ones(len(FEATURE_NAMES), np.float32)

    def save(self, path):
        np.savez_compressed(path, **self.params, mean=self.mean, std=self.std,
            target_mean=self.target_mean, target_std=self.target_std,
            feature_names=np.asarray(FEATURE_NAMES))

    @classmethod
    def load(cls, path):
        model = cls()
        with np.load(path, allow_pickle=False) as data:
            assert tuple(data['feature_names']) == FEATURE_NAMES
            model.params = {key: data[key].copy() for key in model.params}
            for name in ('mean', 'std', 'target_mean', 'target_std'):
                setattr(model, name, data[name].copy())
        assert all(np.isfinite(value).all() for value in model.params.values())
        return model


def proposals(candidates, safe, distances, pose, task):
    candidates = list(candidates)
    if task['returning'] and task['box'] is not None:
        box = np.asarray(task['box'])
        for (row, col), travelled in distances.items():
            xy = np.array([col, row])*.1-9.95
            radius = float(np.linalg.norm(xy-box))
            if .36 <= radius <= .58 and travelled >= .12:
                goal = [*xy.tolist(), math.atan2(box[1]-xy[1], box[0]-xy[0])]
                candidates.append((0., goal, True))
    return candidates


def inputs(known, blocked, pose, visits, candidates, distances, task):
    base = features(known, blocked, pose, visits, candidates, distances)
    extra = np.zeros((len(candidates), 8), np.float32)
    extra[:, 0] = task['returning']
    if task['box'] is not None:
        box = np.asarray(task['box'])
        extra[:, 1] = 1
        extra[:, 5] = math.dist(pose[:2], box)/10
        for index, (_, goal, _) in enumerate(candidates):
            delta = box-np.asarray(goal[:2])
            radius = float(np.linalg.norm(delta))
            angle = math.atan2(delta[1], delta[0])-goal[2]
            extra[index, 2:5] = radius/10, math.cos(angle), math.sin(angle)
            extra[index, 6] = task['returning'] and .36 <= radius <= .58
            extra[index, 7] = abs(radius-.46)/10
    return np.column_stack((base, extra))


def baseline(candidates, distances, task):
    scores = np.asarray([c[0] for c in candidates], dtype=float)
    if task['returning'] and task['box'] is not None:
        box = task['box']
        for i, (_, goal, _) in enumerate(candidates):
            col, row = np.floor((np.asarray(goal[:2])+10)/.1).astype(int)
            radius = math.dist(goal[:2], box)
            scores[i] = -20*abs(radius-.46)-distances[(row, col)]
    return scores


def rank(candidates, safe, known, blocked, pose, visits, distances, task, model=None):
    candidates = proposals(candidates, safe, distances, pose, task)
    x = inputs(known, blocked, pose, visits, candidates, distances, task)
    scores = baseline(candidates, distances, task) if model is None else model.predict(x)[0]
    assert np.isfinite(scores).all()
    order = np.argsort(-scores, kind='stable')
    return candidates, x, scores, order


def navigation(candidates, safe, known, blocked, pose, visits, distances, task, directory=None, frame=None):
    mode = os.environ.get('PUPPYBOT_SEEK_POLICY', 'heuristic')
    if mode not in ('heuristic', 'mlp'):
        raise ValueError('unknown find-return policy '+mode)
    path = Path(os.environ['PUPPYBOT_SEEK_WEIGHTS']) if mode == 'mlp' else None
    model = SeekNetwork.load(path) if path is not None else None
    candidates, x, scores, order = rank(candidates, safe, known, blocked, pose, visits, distances, task, model)
    goals = []
    for i in order:
        goal = candidates[int(i)][1]
        if all(math.dist(goal[:2], existing[:2]) > .24 for existing in goals):
            goals.append(goal)
        if len(goals) >= 8:
            break
    if directory is not None:
        receipt = dict(schema='puppybot.find-return-ranking.v1', frameId=frame, phase='return' if task['returning'] else 'search',
            policy=mode, weightsSHA256=sha256(path) if path is not None else None,
            actorInputs='own RGB map, own pose, visits, observed box and task phase',
            masksChanged=False, candidates=len(candidates), goals=goals,
            top=[dict(features=x[i].tolist(), score=float(scores[i])) for i in order[:8]])
        (Path(directory)/f'seek-ranking-{frame}.json').write_text(json.dumps(receipt)+'\n')
    return goals
