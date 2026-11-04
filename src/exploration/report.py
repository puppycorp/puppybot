#!/usr/bin/env python3
"""Render retained training and comparison measurements without rerunning models."""
import argparse
import json
import os
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--artifacts',type=Path,required=True);args=parser.parse_args()
    root=args.artifacts;training=root/'training'
    os.environ.setdefault('MPLCONFIGDIR',str(root/'matplotlib-cache'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    curve=json.loads((training/'curves.json').read_text());report=json.loads((training/'training-report.json').read_text())
    fig,axes=plt.subplots(1,2,figsize=(12,4.8),constrained_layout=True)
    for key,label in (('trainLoss','Training'),('validationLoss','Validation')):
        axes[0].plot([row['epoch'] for row in curve],[row[key] for row in curve],label=label)
    axes[0].set(xlabel='Epoch',ylabel='Utility MSE + weighted risk cross entropy',title='Genuine NumPy Adam optimization')
    axes[0].legend();axes[0].grid(alpha=.25)
    policies=report['heldoutTest']['policies'];names=['heuristic','gain_per_cost','network','oracle']
    values=[policies[name]['meanTeacherUtility'] for name in names]
    axes[1].bar(['Heuristic','Gain / cost','Trained MLP','Teacher upper bound'],values,color=['#87949c','#b29d73','#258b70','#c5cbd0'])
    manifest=json.loads((training/'dataset-manifest.json').read_text())
    scenes=len(manifest['splits']['test']);decisions=report['heldoutTest']['decisions']
    axes[1].set(ylabel='Offline teacher utility',title=f'{scenes} held-out scene seeds / {decisions} decisions')
    axes[1].tick_params(axis='x',labelrotation=12)
    for i,value in enumerate(values):axes[1].text(i,value+.015,f'{value:.3f}',ha='center')
    fig.suptitle('Idealized partial-map bootstrap only; these are not real RGB closed-loop results',fontsize=11)
    fig.savefig(training/'training-curves.png',dpi=160);plt.close(fig)
    native=root/'native-summary.json'
    if native.exists():
        rows=json.loads(native.read_text())['rows'];seeds=sorted({row['seed'] for row in rows})
        fig,axes=plt.subplots(1,2,figsize=(12,4.8),constrained_layout=True)
        for index,name in enumerate(('heuristic','gain','mlp')):
            offset=(index-1)*.23
            for axis,key,label in ((axes[0],'freeFloorCoverage','Coverage (%)'),(axes[1],'freeSpacePrecision','Free-space precision (%)')):
                values=[100*next((row.get(key,0) or 0 for row in rows if row['seed']==seed and row['policy']==name),0) for seed in seeds]
                axis.bar([i+offset for i in range(len(seeds))],values,width=.23,label=name)
                axis.set(xticks=range(len(seeds)),xticklabels=[str(seed) for seed in seeds],ylabel=label,xlabel='Unseen scene seed')
        axes[0].legend();axes[1].set_ylim(0,101)
        fig.suptitle('Bounded native wrist-RGB exploration only; six-brick collection not tested')
        fig.savefig(root/'native-comparison.png',dpi=160);plt.close(fig)
    print(training/'training-curves.png')


if __name__=='__main__':main()
