#!/usr/bin/env python3
"""Train a small NumPy frontier scorer on explicitly idealized partial maps."""
import argparse
import importlib.util
import json
import math
from pathlib import Path
import sys
import time

import cv2
import numpy as np

from policy import FEATURE_NAMES, Network, RISK_COST, evaluate, features, sha256


def module(name, path):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


def reference(layout):
    yy,xx=np.indices((200,200));x=(xx+.5)*.1-10;y=(yy+.5)*.1-10
    spawn=layout['spawn'];c,s=math.cos(spawn[2]),math.sin(spawn[2])
    wx,wy=spawn[0]+c*x-s*y,spawn[1]+s*x+c*y;b=layout['bounds']
    free=(wx>b[0])&(wx<b[2])&(wy>b[1])&(wy<b[3])
    for obj in layout['objects']:
        if not obj['collision'] or obj['centre'][2]+obj['half'][2]<=.02 or obj['centre'][2]-obj['half'][2]>=.45:continue
        c,s=math.cos(obj['yaw']),math.sin(obj['yaw']);dx,dy=wx-obj['centre'][0],wy-obj['centre'][1]
        free&=~((np.abs(c*dx+s*dy)<=obj['half'][0])&(np.abs(-s*dx+c*dy)<=obj['half'][1]))
    return free


def ray_paths():
    y,x=np.indices((27,27))-13;valid=x*x+y*y<=169
    ends=np.column_stack((y[valid],x[valid]))
    return ends,np.rint(ends[:,None,:]*np.linspace(0,1,27)[None,:,None]).astype(int)


ENDS,PATHS=ray_paths()


def visibility(free,xy):
    col,row=np.floor((np.asarray(xy)+10)/.1).astype(int)
    r=np.clip(PATHS[:,:,0]+row,0,199);c=np.clip(PATHS[:,:,1]+col,0,199)
    hit=~free[r,c];clear=~hit.any(axis=1)
    visible=np.zeros_like(free);blocked=np.zeros_like(free)
    er,ec=np.clip(ENDS[:,0]+row,0,199),np.clip(ENDS[:,1]+col,0,199)
    visible[er[clear],ec[clear]]=True
    have=hit.any(axis=1);first=hit.argmax(axis=1)
    blocked[r[have,first[have]],c[have,first[have]]]=True
    return visible,blocked


def distances(safe,pose):
    col,row=np.floor((np.asarray(pose[:2])+10)/.1).astype(int)
    result={(int(row),int(col)):0.};queue=[(int(row),int(col))]
    for r,c in queue:
        for dr,dc in ((-1,0),(1,0),(0,-1),(0,1)):
            rr,cc=r+dr,c+dc
            if 0<=rr<200 and 0<=cc<200 and safe[rr,cc] and (rr,cc) not in result:
                result[(rr,cc)]=result[(r,c)]+.1;queue.append((rr,cc))
    return result


def corpus(generator,mapper,seeds,states):
    rows=[];targets=[];groups=[];scene_ids=[];heuristics=[];gains=[];group=0
    for number,seed in enumerate(seeds,1):
        rng=np.random.default_rng(seed);truth=reference(generator.generate(seed,3+seed%2))
        unsafe=cv2.dilate((~truth).astype(np.uint8),cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(5,5))).astype(bool)
        known=np.zeros_like(truth);occupied=np.zeros_like(truth);revealed=np.zeros_like(truth)
        actual=np.zeros(2);bias=np.zeros(2,dtype=int);visits=[];heading=0.
        for tick in range(states):
            seen,hits=visibility(truth,actual);revealed|=seen
            transform=np.float32([[1,0,bias[0]],[0,1,bias[1]]])
            fresh=cv2.warpAffine(seen.astype(np.uint8),transform,(200,200)).astype(bool)
            blocked=cv2.warpAffine(hits.astype(np.uint8),transform,(200,200)).astype(bool)
            known|=fresh;occupied=(occupied&~fresh)|blocked;known&=~occupied
            pose=np.r_[actual+bias*.1,heading];visits.append(pose.tolist())
            col,row=np.floor((pose[:2]+10)/.1).astype(int)
            known[row-1:row+2,col-1:col+2]=True;occupied[row-1:row+2,col-1:col+2]=False
            safe,_,_,goals=mapper.navigation(known.astype(np.int32)*10,occupied.astype(np.int32)*2,pose,visits)
            if not goals:break
            route=distances(safe,pose);unknown=~known&~occupied
            candidates=[];gain=[]
            for goal in goals:
                c,r=np.floor((np.asarray(goal[:2])+10)/.1).astype(int)
                value=float(unknown[max(0,r-4):r+5,max(0,c-4):c+5].sum())/(1+route[(int(r),int(c))])
                penalty=sum(math.exp(-float(np.sum((np.asarray(goal[:2])-v[:2])**2))/.12) for v in np.asarray(visits))
                candidates.append((value-20*penalty,goal,True));gain.append(value)
            x=features(known,occupied,pose,visits,candidates,route);y=[]
            for candidate in candidates:
                xy=np.asarray(candidate[1][:2])-bias*.1;c,r=np.floor((xy+10)/.1).astype(int)
                risk=not(0<=r<200 and 0<=c<200) or unsafe[np.clip(r,0,199),np.clip(c,0,199)]
                view,_=visibility(truth,xy);c0,r0=np.floor((np.asarray(candidate[1][:2])+10)/.1).astype(int)
                utility=float((view&~revealed).sum())*.01/(1+route[(int(r0),int(c0))])
                y.append([0. if risk else utility,float(risk)])
            rows.extend(x);targets.extend(y);groups.extend([group]*len(y));scene_ids.extend([seed]*len(y))
            heuristics.extend(c[0] for c in candidates);gains.extend(gain);group+=1
            legal=[i for i,t in enumerate(y) if not t[1]]
            if not legal:break
            kind=rng.random()
            index=max(legal,key=lambda i:y[i][0]) if kind<.5 else max(legal,key=lambda i:candidates[i][0]) if kind<.75 else int(rng.choice(legal))
            next_actual=np.asarray(candidates[index][1][:2])-bias*.1
            heading=math.atan2(next_actual[1]-actual[1],next_actual[0]-actual[0]);actual=next_actual
            if tick%2:bias=np.clip(bias+rng.integers(-1,2,2),-2,2)
        if number%10==0:print(json.dumps(dict(corpusScenes=number,rows=len(rows))),flush=True)
    return dict(features=np.asarray(rows,np.float32),targets=np.asarray(targets,np.float32),groups=np.asarray(groups,np.int32),scenes=np.asarray(scene_ids,np.int32),heuristic=np.asarray(heuristics,np.float32),gain=np.asarray(gains,np.float32))


def train(data,validation,output,epochs,seed):
    model=Network(seed);model.mean=data['features'].mean(0);model.std=np.maximum(data['features'].std(0),.01)
    model.target_mean=data['targets'][:,0].mean();model.target_std=max(float(data['targets'][:,0].std()),.05)
    model.save(output/'initial.npz');initial=evaluate(model,validation)
    rng=np.random.default_rng(seed);m={k:np.zeros_like(v) for k,v in model.params.items()};v={k:np.zeros_like(a) for k,a in model.params.items()}
    best=float('inf');step=0;curves=[]
    for epoch in range(epochs):
        order=rng.permutation(len(data['features']));losses=[]
        for start in range(0,len(order),256):
            ids=order[start:start+256];loss,gradient=model.loss_gradient(data['features'][ids],data['targets'][ids]);losses.append(loss);step+=1
            norm=math.sqrt(sum(float(np.sum(g*g)) for g in gradient.values()))
            for key in model.params:
                g=gradient[key]*min(1.,10/max(norm,1e-9));m[key]=.9*m[key]+.1*g;v[key]=.999*v[key]+.001*g*g
                model.params[key]-=.001*(m[key]/(1-.9**step))/(np.sqrt(v[key]/(1-.999**step))+1e-8)
        val,_=model.loss_gradient(validation['features'],validation['targets'])
        row=dict(epoch=epoch+1,trainLoss=float(np.mean(losses)),validationLoss=val,updates=step)
        if val<best:best=val;model.save(output/'checkpoint.npz');row['selected']=True
        curves.append(row);(output/'curves.json').write_text(json.dumps(curves,indent=2)+'\n')
        if epoch%5==0 or epoch==epochs-1:print(json.dumps(row),flush=True)
    return Network.load(output/'checkpoint.npz'),initial


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--workspace',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    for name,value in (('train-scenes',80),('validation-scenes',20),('test-scenes',30),('states',8),('epochs',80),('seed',7)):parser.add_argument('--'+name,type=int,default=value)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    sys.path.insert(0,str(args.workspace/'flex/vision'))
    generator=module('frozen_generator',args.workspace/'flex/scripts/generate-layout.py');mapper=module('frozen_mapper',args.workspace/'flex/vision/discovery.py')
    splits=dict(train=list(range(30000,30000+args.train_scenes)),validation=list(range(40000,40000+args.validation_scenes)),test=list(range(50000,50000+args.test_scenes)))
    assert all(not set(splits[a])&set(splits[b]) for a,b in (('train','validation'),('train','test'),('validation','test')))
    datasets={};started=time.monotonic()
    for name,seeds in splits.items():datasets[name]=corpus(generator,mapper,seeds,args.states);np.savez_compressed(args.output/(name+'.npz'),**datasets[name])
    manifest=dict(schema='puppybot.exploration-bootstrap-data.v1',splits=splits,trainingSeed=args.seed,actorFeatures=FEATURE_NAMES,actorContainsReferenceGeometry=False,
                  approximation='Idealized 10cm 2D raycast partial maps with full-circle 1.3m views, synthetic 0-20cm accumulated pose bias and instantaneous endpoint movement. No actual RGB, arm motion, Ackermann trajectories or native physics.',
                  teacher='Offline reference visibility gain divided by learned-map route distance; conservative 20cm-radius endpoint risk',
                  featureSourceSHA256=sha256(Path(__file__).with_name('policy.py')),generatorSourceSHA256=sha256(args.workspace/'flex/scripts/generate-layout.py'),
                  files={name:dict(path=name+'.npz',sha256=sha256(args.output/(name+'.npz')),scenes=len(splits[name]),decisions=len(np.unique(data['groups'])),candidates=len(data['features'])) for name,data in datasets.items()})
    (args.output/'dataset-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print(json.dumps(dict(trainingStarted=True,manifest=str(args.output/'dataset-manifest.json'))),flush=True)
    model,initial=train(datasets['train'],datasets['validation'],args.output,args.epochs,args.seed)
    report=dict(schema='puppybot.exploration-training.v1',genuineGradientOptimization=True,model='24-64-32-2 tanh MLP, NumPy Adam utility/risk heads',parameters=sum(v.size for v in model.params.values()),epochs=args.epochs,
                checkpointSelection='minimum validation loss; held-out test evaluated only after selection',initialValidation=initial,finalValidation=evaluate(model,datasets['validation']),heldoutTest=evaluate(model,datasets['test']),
                checkpointSHA256=sha256(args.output/'checkpoint.npz'),initialSHA256=sha256(args.output/'initial.npz'),elapsedSeconds=time.monotonic()-started,nativeClosedLoopImprovementProven=False)
    (args.output/'training-report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)


if __name__=='__main__':main()
