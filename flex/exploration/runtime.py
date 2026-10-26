"""Private experiment hook: reorder existing candidates without changing masks."""
import json
import math
import os
from pathlib import Path
import time

import numpy as np

from explorer_policy import Network, blend_scores, features, sha256

_output = None
_frame = None


def configure_output(directory, frame):
    global _output, _frame
    _output, _frame = Path(directory), frame


def rerank_candidates(candidates, known_free, blocked, pose, visits, distances):
    if not candidates:
        return candidates
    started = time.perf_counter()
    mode = os.environ.get('PUPPYBOT_EXPLORATION_POLICY', 'heuristic')
    x = features(known_free, blocked, pose, visits, candidates, distances)
    original = np.asarray([candidate[0] for candidate in candidates])
    weights_hash = None
    fallback = False
    if mode == 'heuristic':
        scores = original
    elif mode == 'gain':
        penalties = [sum(math.exp(-float(np.sum((np.asarray(c[1][:2])-np.asarray(v[:2]))**2))/.12)
                         for v in visits) for c in candidates]
        scores = original+20*np.asarray(penalties)
    elif mode == 'mlp':
        path = Path(os.environ['PUPPYBOT_EXPLORATION_WEIGHTS'])
        model = Network.load(path)
        weights_hash = sha256(path)
        scores, _, _ = model.predict(x)
        configuration = path.parent/'runtime.json'
        if configuration.exists():
            config = json.loads(configuration.read_text())
            scores = blend_scores(scores, original, config['networkWeight'])
        if not np.isfinite(scores).all():
            scores, fallback = original, True
    else:
        raise ValueError('unknown exploration policy '+mode)
    order = np.argsort(-scores, kind='stable')
    if _output is not None:
        receipt = dict(schema='puppybot.neural-ranking.v1', frameId=_frame, policy=mode,
                       candidates=len(candidates), weightsSHA256=weights_hash,
                       inferenceMs=(time.perf_counter()-started)*1000, fallback=fallback,
                       actorInput='own partial map, own pose, scan visits and reachable candidate costs',
                       masksChanged=False,
                       top=[dict(goal=candidates[int(i)][1], score=float(scores[i]),
                                 heuristicScore=float(original[i]), features=x[i].tolist())
                            for i in order[:16]])
        (_output/f'ranking-{_frame}.json').write_text(json.dumps(receipt)+'\n')
    # Comfortable/narrow candidate classification stays exactly as the baseline.
    return [(float(score), candidate[1], candidate[2]) for score, candidate in zip(scores, candidates)]
