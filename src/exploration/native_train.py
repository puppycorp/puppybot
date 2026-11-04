#!/usr/bin/env python3
"""Train on real RGB-derived partial maps; select only on separate scene seeds."""
import argparse
import json
import math
from pathlib import Path
import shutil
import time

import numpy as np

from policy import Network, RISK_COST, blend_scores, evaluate, sha256


def selection(model, data, weight):
    predicted = model.predict(data['features'])[0]
    target = data['targets'][:, 0]-RISK_COST*data['targets'][:, 1]
    per_scene = {}
    for group in np.unique(data['groups']):
        ids = np.flatnonzero(data['groups'] == group)
        scores = blend_scores(predicted[ids], data['heuristic'][ids], weight)
        # Match navigation's first tier: the whole 5x5 patch must be observed
        # free and the original novelty score positive. Feature 2 is that
        # exact patch's free fraction; reference labels never set eligibility.
        comfortable = (data['features'][ids, 2] > .999999) & (data['heuristic'][ids] > 0)
        if comfortable.any():
            scores = scores[comfortable]
            ids = ids[comfortable]
        selected = ids[np.argmax(scores)]
        scene = int(data['scenes'][ids[0]])
        per_scene.setdefault(scene, []).append(float(target[ids].max()-target[selected]))
    means = {scene: float(np.mean(values)) for scene, values in per_scene.items()}
    return dict(meanSceneRegret=float(np.mean(list(means.values()))), sceneRegret=means,
                networkWeight=weight)


def train(data, validation, output, seed, epochs):
    output.mkdir()
    model = Network(seed)
    model.mean = data['features'].mean(0)
    model.std = np.maximum(data['features'].std(0), .01)
    model.target_mean = data['targets'][:, 0].mean()
    model.target_std = max(float(data['targets'][:, 0].std()), .05)
    model.save(output/'initial.npz')
    initial = evaluate(model, validation)
    rng = np.random.default_rng(seed)
    groups = [np.flatnonzero(data['groups'] == group) for group in np.unique(data['groups'])]
    momentum = {key: np.zeros_like(value) for key, value in model.params.items()}
    variance = {key: np.zeros_like(value) for key, value in model.params.items()}
    best = float('inf')
    step = 0
    curves = []
    for epoch in range(epochs):
        losses = []
        for _ in range(max(1, len(data['features'])//512)):
            chosen = rng.integers(0, len(groups), size=32)
            ids = np.concatenate([rng.choice(groups[index], 16, replace=True) for index in chosen])
            loss, gradient = model.loss_gradient(data['features'][ids], data['targets'][ids])
            losses.append(loss)
            step += 1
            norm = math.sqrt(sum(float(np.sum(g*g)) for g in gradient.values()))
            for key in model.params:
                g = gradient[key]*min(1., 10/max(norm, 1e-9))
                momentum[key] = .9*momentum[key]+.1*g
                variance[key] = .999*variance[key]+.001*g*g
                model.params[key] -= .001*(momentum[key]/(1-.9**step))/(np.sqrt(variance[key]/(1-.999**step))+1e-8)
        val, _ = model.loss_gradient(validation['features'], validation['targets'])
        row = dict(epoch=epoch+1, updates=step, trainLoss=float(np.mean(losses)), validationLoss=val)
        if val < best:
            best = val
            model.save(output/'checkpoint.npz')
            row['selected'] = True
        curves.append(row)
        (output/'curves.json').write_text(json.dumps(curves, indent=2)+'\n')
        if epoch % 20 == 0 or epoch == epochs-1:
            print(json.dumps(dict(seed=seed, **row)), flush=True)
    model = Network.load(output/'checkpoint.npz')
    report = dict(seed=seed, epochs=epochs, updates=step, genuineGradientOptimization=True,
        initialValidation=initial, finalValidation=evaluate(model, validation),
        mixtures=[selection(model, validation, weight) for weight in (0., .25, .5, .75, 1.)],
        checkpointSHA256=sha256(output/'checkpoint.npz'))
    (output/'training-report.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--seeds', type=int, nargs='+', default=[7, 19, 43])
    parser.add_argument('--epochs', type=int, default=120)
    parser.add_argument('--reselect', action='store_true', help='recompute validation selection from retained trained seeds')
    parser.add_argument('--visual', action='store_true', help='train the 154-input frozen-YOLO fusion head')
    args = parser.parse_args()
    if args.visual:
        global Network
        from visual_policy import VisualNetwork
        Network = VisualNetwork
    if not args.reselect:
        args.output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    with np.load(args.data/'train.npz') as source:
        data = {key: source[key].copy() for key in source.files}
    with np.load(args.data/'validation.npz') as source:
        validation = {key: source[key].copy() for key in source.files}
    assert not set(data['scenes']) & set(validation['scenes'])
    if args.reselect:
        reports = []
        for seed in args.seeds:
            folder = args.output/f'seed-{seed}'
            report = json.loads((folder/'training-report.json').read_text())
            model = Network.load(folder/'checkpoint.npz')
            report['mixtures'] = [selection(model, validation, weight) for weight in (0., .25, .5, .75, 1.)]
            (folder/'training-report.json').write_text(json.dumps(report, indent=2)+'\n')
            reports.append(report)
    else:
        reports = [train(data, validation, args.output/f'seed-{seed}', seed, args.epochs) for seed in args.seeds]
    choices = [(mixture['meanSceneRegret'], report['seed'], mixture['networkWeight'])
               for report in reports for mixture in report['mixtures'] if mixture['networkWeight'] > 0]
    regret, seed, weight = min(choices)
    shutil.copyfile(args.output/f'seed-{seed}/checkpoint.npz', args.output/'checkpoint.npz')
    config = dict(schema='puppybot.native-frontier-runtime.v1', networkWeight=weight,
                  selection='Normalize full proposal pool, then minimize equal-scene regret within the native comfortable-first tier; held-out trials untouched', seed=seed)
    (args.output/'runtime.json').write_text(json.dumps(config, indent=2)+'\n')
    report = dict(schema='puppybot.native-frontier-training.v1', genuineGradientOptimization=True,
        parameters=sum(p.size for p in Network().params.values()), epochs=args.epochs, seeds=args.seeds, selectedSeed=seed, selectedNetworkWeight=weight,
        validationSceneRegret=regret, baselineValidationSceneRegret=reports[0]['mixtures'][0]['meanSceneRegret'],
        sceneSplit=json.loads((args.data/'dataset-manifest.json').read_text())['splits'],
        checkpointSHA256=sha256(args.output/'checkpoint.npz'), runtimeSHA256=sha256(args.output/'runtime.json'),
        nativeClosedLoopImprovementProven=False,
        teacherLimit='Real RGB-derived actor inputs; approximate geometric future-visibility labels, not counterfactual sensor outcomes')
    report['selectionElapsedSeconds' if args.reselect else 'elapsedSeconds'] = time.monotonic()-started
    (args.output/'training-report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
