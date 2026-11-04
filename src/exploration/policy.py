"""Small frontier utility/risk network; actor inputs contain only its own map."""
import hashlib
import math
from pathlib import Path

import cv2
import numpy as np

RISK_COST = .5
FEATURE_NAMES = tuple(f'{kind}_radius_{radius}' for radius in (2, 4, 8, 12)
                      for kind in ('unknown', 'occupied', 'free')) + tuple(
    f'unknown_quadrant_{index}' for index in range(4)) + (
    'route_distance', 'local_unknown_gain', 'visit_density', 'free_clearance',
    'relative_forward', 'relative_lateral', 'relative_heading_cos', 'relative_heading_sin')


def features(known_free, occupied, pose, visits, candidates, distances):
    """No reference geometry, actual pose, scene identity or room count is accepted."""
    unknown = ~known_free & ~occupied
    images = [unknown.astype(np.float32), occupied.astype(np.float32), known_free.astype(np.float32)]
    means = [cv2.boxFilter(image, -1, (radius*2+1, radius*2+1), normalize=True)
             for radius in (2, 4, 8, 12) for image in images]
    clearance = cv2.distanceTransform(known_free.astype(np.uint8), cv2.DIST_L2, 5)
    result = []
    c, s = math.cos(pose[2]), math.sin(pose[2])
    for candidate in candidates:
        xy = np.asarray(candidate[1][:2], dtype=float)
        col, row = np.floor((xy+10)/.1).astype(int)
        values = [float(image[row, col]) for image in means]
        for dr, dc in ((-1, -1), (-1, 1), (1, -1), (1, 1)):
            r0, r1 = sorted((row, int(np.clip(row+dr*8, 0, known_free.shape[0]))))
            c0, c1 = sorted((col, int(np.clip(col+dc*8, 0, known_free.shape[1]))))
            patch = unknown[r0:r1, c0:c1]
            values.append(float(patch.mean()) if patch.size else 0.)
        penalty = sum(math.exp(-float(np.sum((xy-np.asarray(visit[:2]))**2))/.12) for visit in visits)
        dx, dy = xy-pose[:2]
        angle = candidate[1][2]-pose[2]
        gain = unknown[max(0, row-4):row+5, max(0, col-4):col+5].sum()
        values.extend((distances[(int(row), int(col))]/10, gain/81, penalty/10,
                       min(float(clearance[row, col]), 20)/10,
                       (c*dx+s*dy)/10, (-s*dx+c*dy)/10, math.cos(angle), math.sin(angle)))
        result.append(values)
    return np.asarray(result, np.float32).reshape(-1, len(FEATURE_NAMES))


def sigmoid(values):
    return 1/(1+np.exp(-np.clip(values, -30, 30)))


def blend_scores(predicted, heuristic, weight):
    """Combine state-relative learned utility with a normalized baseline score."""
    assert 0 <= weight <= 1
    spread = float(np.ptp(heuristic))
    baseline = (heuristic-heuristic.min())/spread if spread > 1e-9 else np.zeros_like(heuristic)
    return weight*predicted+(1-weight)*baseline


class Network:
    def __init__(self, seed=7):
        rng = np.random.default_rng(seed)
        sizes = [len(FEATURE_NAMES), 64, 32, 2]
        self.params = {}
        for index, (a, b) in enumerate(zip(sizes, sizes[1:]), 1):
            self.params[f'w{index}'] = rng.normal(0, 1/math.sqrt(a), (a, b)).astype(np.float32)
            self.params[f'b{index}'] = np.zeros(b, np.float32)
        self.mean = np.zeros(sizes[0], np.float32)
        self.std = np.ones(sizes[0], np.float32)
        self.target_mean = np.float32(0)
        self.target_std = np.float32(1)

    def forward(self, x):
        x = (x-self.mean)/self.std
        a = np.tanh(x@self.params['w1']+self.params['b1'])
        b = np.tanh(a@self.params['w2']+self.params['b2'])
        return b@self.params['w3']+self.params['b3'], (x, a, b)

    def loss_gradient(self, x, targets):
        y, (x, a, b) = self.forward(x)
        error = y[:, 0]-(targets[:, 0]-self.target_mean)/self.target_std
        risk = targets[:, 1]
        ce = np.maximum(y[:, 1], 0)-y[:, 1]*risk+np.log1p(np.exp(-np.abs(y[:, 1])))
        loss = float(np.mean(error**2)+.25*np.mean(ce))
        delta = np.column_stack((2*error, .25*(sigmoid(y[:, 1])-risk)))/len(x)
        gradients = dict(w3=b.T@delta, b3=delta.sum(axis=0))
        delta = (delta@self.params['w3'].T)*(1-b*b)
        gradients.update(w2=a.T@delta, b2=delta.sum(axis=0))
        delta = (delta@self.params['w2'].T)*(1-a*a)
        gradients.update(w1=x.T@delta, b1=delta.sum(axis=0))
        return loss, gradients

    def predict(self, x):
        y, _ = self.forward(x)
        utility = y[:, 0]*self.target_std+self.target_mean
        risk = sigmoid(y[:, 1])
        return utility-RISK_COST*risk, utility, risk

    def save(self, path):
        np.savez_compressed(path, **self.params, mean=self.mean, std=self.std,
                            target_mean=self.target_mean, target_std=self.target_std,
                            feature_names=np.asarray(FEATURE_NAMES))

    @classmethod
    def load(cls, path):
        network = cls()
        with np.load(path, allow_pickle=False) as data:
            assert tuple(data['feature_names']) == FEATURE_NAMES
            network.params = {key: data[key].copy() for key in network.params}
            network.mean, network.std = data['mean'].copy(), data['std'].copy()
            network.target_mean, network.target_std = data['target_mean'], data['target_std']
        assert all(np.isfinite(value).all() for value in network.params.values())
        return network


def evaluate(network, data):
    predictions, _, risk = network.predict(data['features'])
    target = data['targets'][:, 0]-RISK_COST*data['targets'][:, 1]
    selected = {name: [] for name in ('network', 'heuristic', 'gain_per_cost', 'oracle')}
    chosen_risk = {name: [] for name in selected}
    for group in np.unique(data['groups']):
        indices = np.flatnonzero(data['groups'] == group)
        scores = dict(network=predictions, heuristic=data['heuristic'], gain_per_cost=data['gain'], oracle=target)
        for name, values in scores.items():
            index = indices[np.argmax(values[indices])]
            selected[name].append(float(target[index]))
            chosen_risk[name].append(float(data['targets'][index, 1]))
    oracle = np.asarray(selected['oracle'])
    result = {name: dict(meanTeacherUtility=float(np.mean(values)),
                         meanRegret=float(np.mean(oracle-np.asarray(values))),
                         selectedRiskFraction=float(np.mean(chosen_risk[name])))
              for name, values in selected.items()}
    loss, _ = network.loss_gradient(data['features'], data['targets'])
    return dict(decisions=len(oracle), candidates=len(target), loss=loss, policies=result,
                networkWinFractionVsHeuristic=float(np.mean(np.asarray(selected['network']) > selected['heuristic'])),
                riskBrier=float(np.mean((risk-data['targets'][:, 1])**2)))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
