#!/usr/bin/env python3
"""Check offline coordinate labels, scene-balanced selection and saved splits."""
import argparse
import json
from pathlib import Path
import sys

sys.path = [p for p in sys.path if Path(p).resolve() != Path(__file__).resolve().parent]
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'flex/exploration'))
from native_data import VisibilityTeacher
from native_train import selection
from policy import Network, blend_scores, sha256


def coordinates():
    class Floor:
        def read_environment(self, path):
            return None, None

        def world_points(self, *args):
            return None, None

        def ground_truth(self, *args):
            return np.ones((200, 200), bool), None, None

    teacher = VisibilityTeacher(None, [4, -2, np.pi/2], Floor())
    own = np.array([1., 2., np.pi/3])
    actual = np.array([5., -1., np.pi/2+np.pi/3])
    points = teacher.local_truth([[1, 2], [2, 2]], own, actual)
    # Current robot lies at initial-frame (1,-1); its map X points along
    # initial-frame X despite an arbitrary nonzero initial world heading.
    assert np.allclose(points, [[1, -1], [2, -1]])
    known = np.zeros((200, 200), bool)
    candidates = [(1., [.35, .05, 0.], True), (0., [.05, .35, 0.], True)]
    labels, raw = teacher.labels(known, np.zeros(3), [4, -2, np.pi/2], candidates,
                                {(100, 103): .3, (103, 100): .3})
    assert np.all(labels[:, 1] == 0) and np.all(raw > 0)
    assert np.allclose(labels[:, 0], 1)


def ranking():
    heuristic = np.array([-40., -10., 3., 15.])
    learned = np.array([.9, .1, .2, .3])
    assert np.argmax(blend_scores(learned, heuristic, 0)) == np.argmax(heuristic)
    assert np.array_equal(blend_scores(learned, heuristic, 1), learned)

    class Scores:
        def predict(self, x):
            return x[:, 0], None, None

    values = np.zeros((8, 24))
    values[:, 0] = [0, 1]*4
    data = dict(features=values,
                targets=np.array([[1., 0.], [0., 0.]]*3+[[0., 0.], [1., 0.]]),
                groups=np.repeat(np.arange(4), 2), scenes=np.array([1]*6+[2]*2),
                heuristic=np.arange(8))
    result = selection(Scores(), data, 1.)
    assert result['sceneRegret'] == {1: 1., 2: 0.}
    assert result['meanSceneRegret'] == .5, 'large scenes must not dominate selection'
    values = np.zeros((3, 24))
    values[:, 0] = [0., .8, .2]
    values[:, 2] = [0., 1., 1.]
    data = dict(features=values, targets=np.array([[0., 0.], [1., 0.], [0., 0.]]),
                groups=np.zeros(3), scenes=np.ones(3), heuristic=np.array([-100., 1., 10.]))
    assert selection(Scores(), data, .5)['meanSceneRegret'] == 0, 'normalize before comfortable-tier filtering, as runtime does'


def artifacts(directory):
    manifest = json.loads((directory/'data/dataset-manifest.json').read_text())
    splits = manifest['splits']
    assert not set(splits['train']) & set(splits['validation'])
    plan = json.loads((directory/'experiment-plan.json').read_text())
    assert not (set(splits['train']) | set(splits['validation'])) & set(plan['heldoutSeeds'])
    assert all(replay['mapsByteMatched'] for replay in manifest['replays'])
    for name in ('train', 'validation'):
        path = directory/'data'/(name+'.npz')
        assert sha256(path) == manifest['files'][name]['sha256']
        with np.load(path) as data:
            assert np.isfinite(data['features']).all() and np.isfinite(data['targets']).all()
            assert set(data['scenes']) == set(splits[name])
    report = json.loads((directory/'training/training-report.json').read_text())
    assert sha256(directory/'training/checkpoint.npz') == report['checkpointSHA256']
    assert sha256(directory/'training/runtime.json') == report['runtimeSHA256']
    model = Network.load(directory/'training/checkpoint.npz')
    with np.load(directory/'data/validation.npz') as data:
        assert np.isfinite(model.predict(data['features'])[0]).all()
    assert report['selectedNetworkWeight'] > 0
    for seed in report['seeds']:
        folder = directory/'training'/f'seed-{seed}'
        trained = json.loads((folder/'training-report.json').read_text())
        assert trained['updates'] > 0 and trained['finalValidation']['loss'] < trained['initialValidation']['loss']
        initial, final = Network.load(folder/'initial.npz'), Network.load(folder/'checkpoint.npz')
        assert any(not np.array_equal(initial.params[key], final.params[key]) for key in initial.params)
        curves = json.loads((folder/'curves.json').read_text())
        assert abs(min(row['validationLoss'] for row in curves)-trained['finalValidation']['loss']) < 1e-5


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', type=Path)
    args = parser.parse_args()
    coordinates()
    ranking()
    if args.artifacts:
        artifacts(args.artifacts)
    print(json.dumps(dict(passed=True, rotatedOfflineLabels=True, sceneBalancedSelection=True,
                         savedNativeDatasetAndCheckpointChecked=bool(args.artifacts))))


if __name__ == '__main__':
    main()
