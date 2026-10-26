#!/usr/bin/env python3
"""Check actual gradients, optimization, actor isolation and frozen data splits."""
import argparse
import importlib.util
import inspect
import json
from pathlib import Path
import sys
import tempfile

sys.path = [p for p in sys.path if Path(p).resolve() != Path(__file__).resolve().parent]
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('exploration_policy',ROOT/'flex/exploration/policy.py')
policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(policy)


def gradients():
    rng=np.random.default_rng(19);x=rng.normal(size=(16,len(policy.FEATURE_NAMES))).astype(np.float32)
    y=np.column_stack((np.sin(x[:,0])+.2*x[:,1],x[:,2]>0)).astype(np.float32)
    model=policy.Network(11);loss,analytic=model.loss_gradient(x,y)
    probes=[('w1',(0,1)),('w1',(5,8)),('w2',(2,3)),('w3',(4,0)),('w3',(5,1)),('b3',(0,)),('b3',(1,))]
    errors=[]
    for name,index in probes:
        original=float(model.params[name][index]);epsilon=.001
        model.params[name][index]=original+epsilon;plus,_=model.loss_gradient(x,y)
        model.params[name][index]=original-epsilon;minus,_=model.loss_gradient(x,y)
        model.params[name][index]=original
        numerical=(plus-minus)/(2*epsilon);expected=float(analytic[name][index])
        assert abs(numerical-expected)<.002+abs(expected)*.02,(name,index,numerical,expected)
        errors.append(abs(numerical-expected))
    initial=loss
    for step in range(300):
        loss,gradient=model.loss_gradient(x,y)
        for name in model.params:model.params[name]-=.02*gradient[name]
    final,_=model.loss_gradient(x,y)
    assert final<initial*.5,(initial,final)
    with tempfile.TemporaryDirectory(prefix='exploration-learning-',dir=ROOT/'build/flex/sim') as temporary:
        path=Path(temporary)/'model.npz';model.save(path);loaded=policy.Network.load(path)
        assert np.array_equal(model.predict(x)[0],loaded.predict(x)[0])
    return dict(initialLoss=initial,optimizedLoss=final,maximumFiniteDifferenceError=max(errors))


def actor_inputs():
    assert list(inspect.signature(policy.features).parameters)==['known_free','occupied','pose','visits','candidates','distances']
    assert not any(any(word in name for word in ('seed','truth','bounds','reference','room_count')) for name in policy.FEATURE_NAMES)
    known=np.zeros((200,200),bool);known[94:108,94:108]=True
    occupied=np.zeros_like(known);occupied[94,99]=True
    before=known.copy(),occupied.copy()
    candidates=[(1.,[.35,.05,0.],True),(2.,[.05,.35,1.5],True)]
    distances={(100,103):.3,(103,100):.3}
    values=policy.features(known,occupied,np.zeros(3),[[0,0,0]],candidates,distances)
    assert values.shape==(2,len(policy.FEATURE_NAMES)) and np.isfinite(values).all()
    assert np.array_equal(known,before[0]) and np.array_equal(occupied,before[1]),'actor changed traversability masks'


def artifacts(directory):
    manifest=json.loads((directory/'dataset-manifest.json').read_text());splits=manifest['splits']
    for a,b in (('train','validation'),('train','test'),('validation','test')):assert not set(splits[a])&set(splits[b])
    for name in splits:
        path=directory/(name+'.npz');assert policy.sha256(path)==manifest['files'][name]['sha256']
        with np.load(path,allow_pickle=False) as data:
            assert data['features'].shape[1]==len(policy.FEATURE_NAMES)
            assert set(data['scenes'])<=set(splits[name])
            assert all(len(set(data['scenes'][data['groups']==group]))==1 for group in np.unique(data['groups']))
    report=json.loads((directory/'training-report.json').read_text())
    assert policy.sha256(directory/'checkpoint.npz')==report['checkpointSHA256']
    initial=policy.Network.load(directory/'initial.npz');model=policy.Network.load(directory/'checkpoint.npz')
    assert any(not np.array_equal(model.params[name],initial.params[name]) for name in model.params)
    curves=json.loads((directory/'curves.json').read_text())
    assert curves[-1]['updates']>0 and abs(min(row['validationLoss'] for row in curves)-report['finalValidation']['loss'])<1e-5
    assert report['finalValidation']['loss']<report['initialValidation']['loss']
    assert not report['nativeClosedLoopImprovementProven']


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--artifacts',type=Path);args=parser.parse_args()
    result=gradients();actor_inputs()
    if args.artifacts:artifacts(args.artifacts)
    print(json.dumps(dict(passed=True,gradientAndOptimization=result,actorMasksUnchanged=True,artifactSplitAndCheckpointChecks=bool(args.artifacts))))


if __name__=='__main__':main()
