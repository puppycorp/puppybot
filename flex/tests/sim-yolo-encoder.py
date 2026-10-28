#!/usr/bin/env python3
"""Check visual projection, candidate conditioning and native encoder parity."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path = [p for p in sys.path if Path(p).resolve() != Path(__file__).resolve().parent]
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'flex/exploration'))
from visual import Encoder, VisualMemory
from visual_policy import FEATURES, VisualNetwork


def memory():
    class Image:
        def encode(self, frame):
            image = np.zeros((128, 40, 40), np.float32)
            image[0, :, :20] = 1
            image[1, :, 20:] = 1
            return image, 'synthetic'

    request = dict(frameId=100, pose=[0, 0, 0], frames=[dict(frameId=90,
        calibration=[0, 0, .2, 1, 0, 0, 0, -1, 0, 0, 0, -1])])
    points = np.array([[.8, .35, 0], [.8, -.35, 0], [2., 0, 0]])
    state = VisualMemory()
    state.update(request, points, Image())
    candidates = [(0, [.8, .35, 0], True), (0, [.8, -.35, 0], True), (0, [-2, 0, 0], True)]
    features = state.features(candidates, 200)
    assert features.shape == (3, 130) and features[0, 0] == features[1, 1] == 1
    assert not features[0, 1] and not features[1, 0]
    assert features[0, -2] > 0 and features[2, -2] == 0 and features[2, -1] == 1
    assert (state.stamps >= 0).sum() == 2, 'unmeasured distant points cannot enter visual memory'
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary)/'memory.npz'
        state.path = path
        state.update(request, points, Image())
        restored = VisualMemory(path)
        np.testing.assert_array_equal(restored.features(candidates, 200), features)


def head():
    model = VisualNetwork()
    x = np.random.default_rng(7).normal(size=(12, len(FEATURES))).astype(np.float32)
    altered = x.copy()
    altered[:, 24:] = 0
    assert not np.allclose(model.predict(x)[0], model.predict(altered)[0])
    loss, gradient = model.loss_gradient(x, np.zeros((12, 2)))
    assert np.isfinite(loss) and all(np.isfinite(value).all() for value in gradient.values())
    assert np.linalg.norm(gradient['w1'][24:]) > 0
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary)/'checkpoint.npz'
        model.save(path)
        np.testing.assert_array_equal(model.predict(x)[0], VisualNetwork.load(path).predict(x)[0])


def ranking():
    import visual_runtime
    known = np.ones((200, 200), bool)
    blocked = np.zeros_like(known)
    before = known.tobytes(), blocked.tobytes()
    candidates = [(2., [.05, .05, 0.], True), (1., [1.05, .05, 0.], False)]
    distances = {(100, 100): .3, (100, 110): 1.3}
    memory = VisualMemory()
    memory.values[:] = .1
    memory.stamps[:] = 100
    with tempfile.TemporaryDirectory() as temporary:
        folder = Path(temporary)
        VisualNetwork().save(folder/'checkpoint.npz')
        (folder/'runtime.json').write_text(json.dumps(dict(networkWeight=.5)))
        visual_runtime._memory, visual_runtime._request, visual_runtime._output = memory, dict(frameId=200), folder
        with patch.dict(os.environ, PUPPYBOT_EXPLORATION_WEIGHTS=str(folder/'checkpoint.npz')):
            result = visual_runtime.rerank_candidates(candidates, known, blocked, np.zeros(3), [], distances)
        assert before == (known.tobytes(), blocked.tobytes())
        assert [(c[1], c[2]) for c in result] == [(c[1], c[2]) for c in candidates]
        receipt = json.loads((folder/'ranking-200.json').read_text())
        assert receipt['visualAblationMaxScoreDifference'] > 0 and receipt['featureCount'] == 154
        assert not receipt['masksChanged'] and not receipt['fallback']


def native(directory, reference, output, scene_index):
    output.mkdir(parents=True, exist_ok=False)
    source = ROOT/'build/flex/sim/neural-native-data-v2/data-inputs.json'
    run = Path(json.loads(source.read_text())[scene_index]['run'])
    request = json.loads(next((run/'map/episode-0').glob('input-*.json')).read_text())
    encoder = Encoder(directory, output/'cache')
    actual, digest = encoder.encode(request['frames'][0])
    assert np.linalg.norm(actual) > 0
    encoder.encode(request['frames'][1])
    repeated = output/'repeated.f32'
    encoder.execute(Path(request['frames'][0]['rgb']), repeated)
    np.testing.assert_array_equal(actual.ravel(), np.fromfile(repeated, '<f4'))
    result = dict(passed=True, shape=list(actual.shape), rgbSha256=digest, comparedElements=0,
                  repeatedAfterDifferentFrameByteMatched=True, requestedBackend=encoder.backend)
    if reference:
        import onnx
        from tinygrad import Tensor
        from tinygrad.nn.onnx import OnnxRunner
        model = onnx.load(ROOT/'build/flex/vision/yolo26n.onnx')
        targets = [name for node in model.graph.node for name in node.output if '/model.6/cv2/act/Mul' in name]
        assert len(targets) == 1, targets
        target = targets[0]
        needed, nodes = {target}, []
        for node in reversed(model.graph.node):
            if needed.intersection(node.output):
                nodes.append(node)
                needed.update(node.input)
        del model.graph.node[:]
        model.graph.node.extend(reversed(nodes))
        weights = [tensor for tensor in model.graph.initializer if tensor.name in needed]
        del model.graph.initializer[:]
        model.graph.initializer.extend(weights)
        del model.graph.output[:]
        size = encoder.manifest['inputShape'][2]
        model.graph.input[0].type.tensor_type.shape.dim[2].dim_value = size
        model.graph.input[0].type.tensor_type.shape.dim[3].dim_value = size
        model.graph.output.append(onnx.helper.make_tensor_value_info(target, onnx.TensorProto.FLOAT, encoder.manifest['outputShape']))
        path = output/'reference.onnx'
        onnx.save(model, path)
        rgb = np.fromfile(request['frames'][0]['rgb'], np.uint8).reshape(480, 640, 3)
        if size == 320:
            rgb = np.rint(rgb.reshape(240, 2, 320, 2, 3).mean(axis=(1, 3))).astype(np.uint8)
        padding = size//8
        image = np.pad(rgb, ((padding, padding), (0, 0), (0, 0)), constant_values=114).transpose(2, 0, 1)[None].astype(np.float32)/255
        expected = next(iter(OnnxRunner(str(path))({'images': Tensor(image, device='CPU')}).values())).numpy()[0]
        np.testing.assert_allclose(actual, expected, atol=5e-4, rtol=5e-3)
        result.update(comparedElements=actual.size, maxAbsoluteError=float(abs(actual-expected).max()))
    (output/'audit.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--encoder', type=Path)
    parser.add_argument('--reference', action='store_true')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--scene-index', type=int, default=1)
    args = parser.parse_args()
    memory()
    head()
    ranking()
    if args.encoder:
        assert args.output
        native(args.encoder.resolve(), args.reference, args.output.resolve(), args.scene_index)
    print('YOLO visual memory passed: calibrated projection, range limits, persistence, distinct candidate context and trainable visual weights')


if __name__ == '__main__':
    main()
