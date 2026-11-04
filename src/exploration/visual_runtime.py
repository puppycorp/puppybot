"""Private experimental frontier scorer; scene truth is never an input."""
import json
import os
from pathlib import Path
import time

import numpy as np

from policy import blend_scores, features, sha256
from visual import Encoder, VisualMemory
from visual_policy import VisualNetwork

_output = None
_request = None
_memory = None


def configure_visual(directory, request, points):
    global _output, _request, _memory
    _output, _request = Path(directory), request
    _memory = None
    if os.environ.get('PUPPYBOT_EXPLORATION_POLICY', 'heuristic') == 'yolo':
        started = time.perf_counter()
        encoder = Encoder(os.environ['PUPPYBOT_ENCODER'], _output/'encoder-cache')
        _memory = VisualMemory(_output/'visual-memory.npz')
        frames = _memory.update(request, points, encoder)
        receipt = dict(schema='puppybot.visual-observation.v1', frameId=request['frameId'],
            encoderGraphSha256=encoder.manifest['modelSha256'], weightsSha256=encoder.manifest['weightsSha256'],
            elapsedSeconds=time.perf_counter()-started, frames=frames,
            actorInputs='wrist RGB, own calibration, metric stereo points and estimated pose only')
        (_output/f'visual-{request["frameId"]}.json').write_text(json.dumps(receipt)+'\n')


def rerank_candidates(candidates, known_free, blocked, pose, visits, distances):
    if not candidates or _memory is None:
        return candidates
    started = time.perf_counter()
    x = np.column_stack((features(known_free, blocked, pose, visits, candidates, distances),
                         _memory.features(candidates, _request['frameId'])))
    path = Path(os.environ['PUPPYBOT_EXPLORATION_WEIGHTS'])
    model = VisualNetwork.load(path)
    predicted = model.predict(x)[0]
    ablated = x.copy()
    ablated[:, 24:] = 0
    visual_effect = float(np.max(np.abs(predicted-model.predict(ablated)[0])))
    original = np.asarray([candidate[0] for candidate in candidates])
    weight = json.loads((path.parent/'runtime.json').read_text())['networkWeight']
    assert weight > 0 and np.isfinite(predicted).all()
    scores = blend_scores(predicted, original, weight)
    order = np.argsort(-scores, kind='stable')
    receipt = dict(schema='puppybot.visual-ranking.v1', frameId=_request['frameId'],
        policy='yolo', candidates=len(candidates), featureCount=x.shape[1], weightsSha256=sha256(path),
        networkWeight=weight, inferenceMs=(time.perf_counter()-started)*1000,
        masksChanged=False, fallback=False, candidatesWithVisualMemory=int((x[:, -2] > 0).sum()),
        topScoreVisualNorm=float(np.linalg.norm(x[order[0], 24:-2])),
        visualAblationMaxScoreDifference=visual_effect,
        highestScoreGoal=candidates[int(order[0])][1],
        goalSelection='Original comfortable-first tiers and route feasibility still apply',
        top=[dict(goal=candidates[int(i)][1], score=float(scores[i]), heuristicScore=float(original[i])) for i in order[:8]])
    (_output/f'ranking-{_request["frameId"]}.json').write_text(json.dumps(receipt)+'\n')
    return [(float(score), candidate[1], candidate[2]) for score, candidate in zip(scores, candidates)]
