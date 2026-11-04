#!/usr/bin/env python3
"""Summarize paired native explorer trials without selecting or changing models."""
import argparse
import json
import os
from pathlib import Path

import numpy as np

from policy import sha256


def assess(directory):
    plan = json.loads((directory/'experiment-plan.json').read_text())
    training = json.loads((directory/'training/training-report.json').read_text())
    rows = json.loads((directory/'native-summary.json').read_text())['rows']
    expected = {(seed, mode, repeat) for seed in plan['heldoutSeeds']
                for mode in plan['nativePolicies'] for repeat in range(1, plan['repeats']+1)}
    assert {(r['seed'], r['policy'], r['repeat']) for r in rows} == expected
    assert all(row.get('auditPassed') for row in rows), 'do not summarize unaudited trials as valid comparisons'
    assert all(row['modelSHA256'] == training['checkpointSHA256'] for row in rows)
    assert len({row['binarySHA256'] for row in rows}) == 1
    assert sha256(directory/'training/checkpoint.npz') == training['checkpointSHA256']
    assert sha256(directory/'training/runtime.json') == training['runtimeSHA256']
    summary = {}
    for mode in plan['nativePolicies']:
        selected = [row for row in rows if row['policy'] == mode]
        summary[mode] = dict(
            meanFreeFloorCoverage=float(np.mean([r['freeFloorCoverage'] for r in selected])),
            meanFreeSpacePrecision=float(np.mean([r['freeSpacePrecision'] for r in selected])),
            sumFalseFreeM2=sum(r['falselyFreeM2'] for r in selected),
            meanDistanceM=float(np.mean([r['distanceM'] for r in selected])),
            driveStops=sum(r['driveStops'] for r in selected),
            armStops=sum(r['armStops'] for r in selected),
            completedScanBudgets=sum(r['scans'] == plan['scanBudget'] and r['exitCode'] == 0 for r in selected),
            trials=len(selected))
    paired = []
    for seed in plan['heldoutSeeds']:
        for repeat in range(1, plan['repeats']+1):
            match = {r['policy']: r for r in rows if r['seed'] == seed and r['repeat'] == repeat}
            paired.append(dict(seed=seed, repeat=repeat,
                coverageChangePPVsHeuristic=100*(match['mlp']['freeFloorCoverage']-match['heuristic']['freeFloorCoverage']),
                coverageChangePPVsGain=100*(match['mlp']['freeFloorCoverage']-match['gain']['freeFloorCoverage'])))
    scene_means = {}
    for seed in plan['heldoutSeeds']:
        scene_means[seed] = {mode: float(np.mean([r['freeFloorCoverage'] for r in rows
            if r['seed'] == seed and r['policy'] == mode])) for mode in plan['nativePolicies']}
    result = dict(schema='puppybot.native-trained-exploration-assessment.v2',
        trainingPipelinePassed=True, nativeAuditsPassed=True, fullTrialSetCompleted=True,
        actorTrainingSource='Actual saved wrist-RGB partial maps, byte-matched to original native maps',
        selectedNetworkWeight=training['selectedNetworkWeight'], selectedSeed=training['selectedSeed'],
        validationSceneRegret=training['validationSceneRegret'],
        baselineValidationSceneRegret=training['baselineValidationSceneRegret'],
        nativeCoverageHigherThanBothBaselines=(summary['mlp']['meanFreeFloorCoverage'] > summary['heuristic']['meanFreeFloorCoverage']
            and summary['mlp']['meanFreeFloorCoverage'] > summary['gain']['meanFreeFloorCoverage']),
        robustGeneralizationProven=False, sixBrickCollectionTested=False,
        meanNative=summary, pairedTrials=paired, perSceneMeanCoverage=scene_means,
        limitations=[
            'Two held-out layouts with two repeats each remain a small pilot; repeats are not independent new layouts.',
            'Actor inputs are real RGB-derived maps, but offline labels are approximate 360-degree geometric visibility, not actual counterfactual sensor outcomes.',
            'The learned score can be mixed with a heuristic using a weight selected on separate validation layouts.',
            'Comfortable-first candidate tiers and the native route planner still determine which ranked goals can execute.',
            'No room-completion, collection, cross-generator or hardware improvement is established.',
            'Native workers are asynchronous; inspect paired repeats and travel as well as aggregate coverage.'
        ])
    (directory/'assessment.json').write_text(json.dumps(result, indent=2)+'\n')
    os.environ.setdefault('MPLCONFIGDIR', str(directory/'matplotlib-cache'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), constrained_layout=True)
    modes = plan['nativePolicies']
    seeds = plan['heldoutSeeds']
    for index, mode in enumerate(modes):
        offset = (index-1)*.24
        for axis, key, label in ((axes[0], 'freeFloorCoverage', 'Correct free-floor coverage (%)'),
                                  (axes[1], 'freeSpacePrecision', 'Free-space precision (%)')):
            values = [[100*r[key] for r in rows if r['seed'] == seed and r['policy'] == mode] for seed in seeds]
            means = np.array([np.mean(v) for v in values])
            ranges = np.array([[means[i]-min(v) for i, v in enumerate(values)],
                               [max(v)-means[i] for i, v in enumerate(values)]])
            axis.bar(np.arange(len(seeds))+offset, means, width=.24, yerr=ranges, capsize=4, label=mode)
            axis.set(xticks=range(len(seeds)), xticklabels=[str(s) for s in seeds], xlabel='Unseen layout seed', ylabel=label)
    axes[0].legend()
    axes[1].set_ylim(0, 101)
    fig.suptitle(f'Native RGB exploration: {plan["scanBudget"]} scans, {plan["repeats"]} repeats; bars show repeat range')
    fig.savefig(directory/'native-comparison.png', dpi=160)
    plt.close(fig)
    print(json.dumps(result), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', type=Path, required=True)
    args = parser.parse_args()
    assess(args.artifacts.resolve())


if __name__ == '__main__':
    main()
