#!/usr/bin/env python3
"""Present complete episode results, retaining failed runs in the comparison."""
import argparse
import json
import os
from pathlib import Path

import numpy as np


def report(directory):
    result = json.loads((directory/'summary.json').read_text())
    assert result['complete'] and result['allAuditsPassed'], 'require the full independently audited trial set'
    rows = result['rows']
    seeds = sorted({r['seed'] for r in rows})
    modes = list(result['policies'])
    colors = dict(heuristic='tab:blue', yolo='tab:orange')
    os.environ.setdefault('MPLCONFIGDIR', str(directory/'matplotlib-cache'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    figure, axes = plt.subplots(len(seeds), 2, figsize=(12, 4*len(seeds)), squeeze=False, constrained_layout=True)
    for index, seed in enumerate(seeds):
        selected = [r for r in rows if r['seed'] == seed]
        for row in selected:
            run = directory/'episodes'/f'{seed}-{row["policy"]}-{row["repeat"]}'
            audit = json.loads((run/'audit.json').read_text())
            points = audit['deliveryTimeline']+[dict(step=round(row['actionSeconds']/.02), delivered=row['delivered'])]
            axes[index, 0].step([p['step']*.02/60 for p in points], [p['delivered'] for p in points],
                                where='post', color=colors[row['policy']], label=row['policy'])
            axes[index, 0].plot(row['actionSeconds']/60, row['delivered'],
                                marker='o' if row['taskPassed'] else 'x', color=colors[row['policy']])
        axes[index, 0].set(title=f'Unseen layout {seed}', xlabel='Simulation action minutes', ylabel='Settled bricks in box', ylim=(-.1, 6.3))
        axes[index, 0].legend()
        axis = axes[index, 1]
        for offset, (field, label) in enumerate((('actionSeconds', 'Simulated action'), ('wallSeconds', 'Full episode wall time'))):
            values = [np.mean([r[field]/60 for r in selected if r['policy'] == mode]) for mode in modes]
            axis.bar(np.arange(len(modes))+(offset-.5)*.32, values, width=.32, label=label)
        labels = [mode+'\n'+str(sum(r['taskPassed'] for r in selected if r['policy'] == mode))+' missions completed' for mode in modes]
        axis.set(xticks=range(len(modes)), xticklabels=labels, ylabel='Minutes', title='Runtime until success or failure')
        axis.legend()
    figure.suptitle('Complete pickup-system pilot: six bricks per episode; × marks failed episodes\nSimulation action time excludes stationary mapping waits; wall time includes all compute')
    figure.savefig(directory/'comparison.png', dpi=160)
    plt.close(figure)
    lines = ['# YOLO encoder versus heuristic: whole pickup episodes', '',
        'Frozen checkpoint; unseen layouts; identical robot, sensing, action budgets and physics. '+
        'Success requires all six bricks released and settled inside the box.', '',
        '| Layout | Method | Complete | Settled bricks | Action min | Mapping wait s | Wall min |',
        '| --- | --- | ---: | ---: | ---: | ---: | ---: |']
    for row in rows:
        lines.append(f'| {row["seed"]} | {row["policy"]} | {"yes" if row["taskPassed"] else "no"} | {row["delivered"]}/6 | '+
                     f'{row["actionSeconds"]/60:.2f} | {row["mappingWaitSeconds"]:.2f} | {row["wallSeconds"]/60:.2f} |')
    lines += ['', 'Action time excludes asynchronous mapping waits under the shared private scheduler. '+
        'Wall time includes the complete unpaced episode, encoder startup, inference, and rendering.', '',
        'All failed and timed-out episodes remain in success and throughput denominators. '+
        'The budget-normalized throughput charges early failures the full action budget.', '',
        'This is a two-layout pilot. Training used approximate visibility labels, not pickup rewards. '+
        'These results do not establish broad generalization or physical robot performance.', '']
    (directory/'report.md').write_text('\n'.join(lines))
    print(directory/'report.md')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', required=True, type=Path)
    args = parser.parse_args()
    report(args.artifacts.resolve())


if __name__ == '__main__':
    main()
