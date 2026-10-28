"""Frontier head with the same losses plus frozen YOLO scene features."""
import math

import numpy as np

from policy import FEATURE_NAMES, Network
from visual import VISUAL_NAMES

FEATURES = FEATURE_NAMES+VISUAL_NAMES


class VisualNetwork(Network):
    def __init__(self, seed=7):
        super().__init__(seed)
        self.params['w1'] = np.random.default_rng(seed).normal(0, 1/math.sqrt(len(FEATURES)),
                                                            (len(FEATURES), 64)).astype(np.float32)
        self.mean = np.zeros(len(FEATURES), np.float32)
        self.std = np.ones(len(FEATURES), np.float32)

    def save(self, path):
        np.savez_compressed(path, **self.params, mean=self.mean, std=self.std,
            target_mean=self.target_mean, target_std=self.target_std, feature_names=np.asarray(FEATURES))

    @classmethod
    def load(cls, path):
        model = cls()
        with np.load(path, allow_pickle=False) as data:
            assert tuple(data['feature_names']) == FEATURES
            for key in model.params:
                assert data[key].shape == model.params[key].shape and np.isfinite(data[key]).all()
                model.params[key] = data[key].copy()
            model.mean, model.std = data['mean'].copy(), data['std'].copy()
            model.target_mean, model.target_std = data['target_mean'], data['target_std']
        assert np.isfinite(model.mean).all() and np.isfinite(model.std).all() and (model.std > 0).all()
        return model
