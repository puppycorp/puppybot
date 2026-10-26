#!/usr/bin/env python3
"""Bounded real wrist-RGB comparisons in the frozen private simulator workspace."""
import argparse
import csv
import importlib.util
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import time

import cv2
import numpy as np

from policy import sha256


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


def summarize_trace(run,evaluator,camera_checks):
    requests=[json.loads(p.read_text()) for p in (run/'map/episode-0').glob('input-*.json')]
    needed={r['frameId'] for r in requests}|{f['frameId'] for r in requests for f in r['frames']}
    states={};first=previous=None;poses=[];distance=0.;goals=[]
    with (run/'trace.jsonl').open('rb') as source:
        for line in source:
            if not line.endswith(b'\n'):break
            s=json.loads(line);d=s['discovery']
            assert not d['suppliedMap'] and not d['worldPoseInput'] and s['case'] is None
            assert not s['physicsFault'] and not s['vehicle']['queryFault'] and not s['gripper']['held']
            if first is None:
                first=s
                assert s['localization']['pose']==[0,0,0] and d['freeCells']==d['occupiedCells']==d['images']==0
                assert s['environment']['sensorCameras']==['tcp']
            if s['step'] in needed:states[s['step']]=s
            if s['step']%50==0 or s is first:poses.append((s['step'],s['pose'],s['localization']['pose']))
            if previous:
                drive=previous['controller']['drive'];travel=(drive['leftSpeed']+drive['rightSpeed'])/20000
                x,y,h=previous['pose'];h=(h-travel/.18*math.tan(math.radians(drive['steeringAngleDeg']-90))+math.pi)%(2*math.pi)-math.pi
                expected=previous['pose'] if s['blocked'] else [x+travel*math.cos(h),y+travel*math.sin(h),h]
                assert math.dist(s['pose'][:2],expected[:2])<1e-7
                assert abs((s['pose'][2]-expected[2]+math.pi)%(2*math.pi)-math.pi)<1e-7
                distance+=math.dist(s['pose'][:2],previous['pose'][:2])
                if d['phase']==5 and previous['discovery']['phase']!=5:
                    # Waypoint itself is in the discovery focus; native cases are absent here.
                    goals.append(dict(step=s['step'],pose=s['localization']['pose']))
            previous=s
    assert first and previous
    images=set();max_eye=max_axis=0.
    for request in requests:
        assert set(request)=={'schema','frameId','newScan','pose','frames'}
        assert request['pose']==states[request['frameId']]['localization']['pose']
        for frame in request['frames']:
            assert set(frame)=={'rgb','frameId','calibration','robot'}
            index=frame['frameId'];meta=json.loads((run/'sensor'/f'frame-{index}.png.camera.json').read_text())
            eye,axis=camera_checks.camera_frame_error(states[index],frame['calibration'],meta)
            assert eye<.003 and axis<.00003
            max_eye,max_axis=max(max_eye,eye),max(max_axis,axis)
            rgb=Path(frame['rgb']).read_bytes();png=cv2.imread(str(run/'sensor'/f'frame-{index}.png'))
            assert png is not None and rgb==cv2.cvtColor(png,cv2.COLOR_BGR2RGB).tobytes()
            images.add(index)
    if poses[-1][0]!=previous['step']:poses.append((previous['step'],previous['pose'],previous['localization']['pose']))
    receipt=dict(passed=True,explorationOnly=True,collectionTested=False,initialMapEmpty=True,
                 actorReferenceInput=False,actualMotionIncrementsChecked=previous['step']-1,
                 stereoRequestsChecked=len(requests),savedRawRGBImagesMatched=len(images),
                 maxCameraEyeErrorM=max_eye,maxCameraAxisError=max_axis,distanceM=distance,
                 movementStarts=len(goals),throughStep=previous['step'])
    (run/'native-audit.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return first,previous,poses,receipt


def evaluate(run,scene,evaluator,camera_checks):
    initial,last,poses,audit=summarize_trace(run,evaluator,camera_checks)
    metadata,arrays,raw,free,occupied,fine=evaluator.checkpoint(run)
    bounds,boxes=evaluator.read_environment(scene/'environment.bin')
    assert list(bounds)==last['environment']['bounds']
    resolution=metadata['resolutionM']/5;cells=metadata['cells']*5
    x,y=evaluator.world_points(cells,resolution,metadata['originM'],initial['pose'])
    true_free,true_occupied,inside=evaluator.ground_truth(x,y,bounds,boxes)
    predicted_free=np.repeat(np.repeat(free,5,axis=0),5,axis=1)
    predicted_occupied=np.repeat(np.repeat(occupied,5,axis=0),5,axis=1)
    ignored=np.zeros_like(true_free)
    scores=evaluator.score(predicted_free,predicted_occupied,true_free,true_occupied,resolution,ignored)
    timeline=evaluator.history(run/'map/episode-0',metadata['frameId'],true_free,ignored,metadata['cells'])
    report=run/'benchmark';report.mkdir()
    (report/'checkpoint-evidence.npz').write_bytes(raw)
    result=dict(schema='puppybot.neural-native-map.v1',explorationOnly=True,collectionTested=False,
                mappedFrame=metadata['frameId'],alignment='fixed initial local frame; no best-fit alignment',
                initialActualPose=initial['pose'],obstacleHeightBandM=[.02,.45],taskExclusions=False,
                referenceEnvironmentSHA256=sha256(scene/'environment.bin'),coarseMap=scores,
                odometry=evaluator.pose_metrics(poses,initial['pose']),history=timeline,
                nativeAudit=audit,fullSixBrickSuccessClaimed=False)
    (report/'benchmark.json').write_text(json.dumps(result,indent=2)+'\n')
    evaluator.figure(report,metadata,true_free,true_occupied,predicted_free,predicted_occupied,ignored,scores,timeline)
    logs=[json.loads(p.read_text()) for p in (run/'map/episode-0').glob('ranking-*.json')]
    used=[r for r in logs if r['candidates']]
    return dict(steps=last['step'],scans=last['discovery']['scans'],reason=last['discovery']['reason'],
                driveStops=last['discovery']['protectiveStops'],armStops=last['discovery']['armProtectiveStops'],
                distanceM=audit['distanceM'],rankingCalls=len(used),modelFallbacks=sum(r['fallback'] for r in used),
                actorMasksChanged=any(r['masksChanged'] for r in used),
                freeFloorCoverage=scores['freeFloorCoverage'],freeSpacePrecision=scores['freeSpacePrecision'],
                falselyFreeM2=scores['falselyFreeM2'],positionRMSEM=result['odometry']['positionRMSEM'],auditPassed=True)


def run_trial(out,workspace,scene,seed,mode,scans,steps,timeout,index):
    run=out/'native'/f'seed-{seed}-{mode}-{index}';run.mkdir(parents=True,exist_ok=False)
    binary=out/'controller';weights=out/'training/checkpoint.npz'
    source_paths=[*workspace.glob('flex/sim/*.flex'),*workspace.glob('flex/core/*.flex'),
                  *workspace.glob('flex/host/*.flex'),*workspace.glob('flex/vendor/*.flex'),
                  *workspace.glob('build/flex/sim/library/**/*.flex'),
                  workspace/'build/flex/sim/dependencies.flex',workspace/'build/flex/sim/puppybot.bin',
                  workspace/'flex/vision/discovery.py',workspace/'flex/vision/explorer_policy.py',
                  workspace/'flex/vision/explorer_ranker.py',scene/'environment.bin',binary,weights]
    if (weights.parent/'runtime.json').exists():source_paths.append(weights.parent/'runtime.json')
    manifest={str(path):sha256(path) for path in source_paths}
    (run/'source-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    args=[str(binary),'--hidden','--discover','--environment',str(scene/'environment.bin'),
          '--steps',str(steps),'--mapping-scans',str(scans),'--until-done','--bind','127.0.0.1:0',
          '--map-output',str(run/'map'),'--record',str(run/'trace.jsonl'),
          '--search-output',str(run/'sensor'),'--capture',str(run/'outcome.png'),'--tcp-view']
    env=dict(os.environ,PUPPYBOT_EXPLORATION_POLICY=mode,PUPPYBOT_EXPLORATION_WEIGHTS=str(weights),
             OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MPLCONFIGDIR=str(out/'matplotlib-cache'))
    receipt=dict(args=args,cwd=str(workspace),policy=mode,seed=seed,binarySHA256=sha256(binary),
                 modelSHA256=sha256(weights),budget=dict(scans=scans,steps=steps,wallTimeoutSeconds=timeout),
                 sourceManifestSHA256=sha256(run/'source-manifest.json'),explorationOnly=True)
    if (weights.parent/'runtime.json').exists():receipt['runtimeConfigSHA256']=sha256(weights.parent/'runtime.json')
    (run/'launch.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(dict(startingNativeTrial=str(run),policy=mode,seed=seed)),flush=True)
    started=time.monotonic();timed_out=False
    with (run/'run.log').open('w') as log:
        child=subprocess.Popen(args,cwd=workspace,env=env,stdout=log,stderr=subprocess.STDOUT)
        try:code=child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out=True;child.send_signal(signal.SIGINT)
            try:code=child.wait(timeout=15)
            except subprocess.TimeoutExpired:child.kill();code=child.wait(timeout=5)
    duration=time.monotonic()-started
    (run/'exit.json').write_text(json.dumps(dict(exitCode=code,timedOut=timed_out,elapsedSeconds=duration))+'\n')
    assert all(sha256(Path(path))==value for path,value in manifest.items()),'runtime/model files changed during comparison'
    return run,dict(seed=seed,policy=mode,repeat=index,exitCode=code,timedOut=timed_out,wallSeconds=duration,
                    binarySHA256=receipt['binarySHA256'],modelSHA256=receipt['modelSHA256'])


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--artifacts',type=Path,required=True)
    parser.add_argument('--seeds',type=int,nargs='+',default=[60001,60002]);parser.add_argument('--policies',nargs='+',choices=('heuristic','gain','mlp'),default=['heuristic','gain','mlp'])
    parser.add_argument('--scans',type=int,default=4);parser.add_argument('--steps',type=int,default=30000);parser.add_argument('--timeout',type=int,default=420)
    parser.add_argument('--repeats',type=int,default=1)
    args=parser.parse_args();out=args.artifacts.resolve();workspace=out/'workspace'
    generator=module('frozen_native_generator',workspace/'flex/scripts/generate-layout.py')
    evaluator=module('frozen_native_evaluator',workspace/'flex/scripts/benchmark-map.py')
    camera_checks=module('frozen_camera_checks',workspace/'flex/tests/sim-discovery-pickup.py')
    rows=[]
    for seed in args.seeds:
        scene=out/'scenes'/f'seed-{seed}'
        if not scene.exists():generator.write(generator.generate(seed,3+seed%2),scene)
        for repeat in range(1,args.repeats+1):
            # Reverse policy order on alternate repeats to reduce order bias.
            policies=args.policies if repeat%2 else list(reversed(args.policies))
            for mode in policies:
                run,row=run_trial(out,workspace,scene,seed,mode,args.scans,args.steps,args.timeout,repeat)
                try:row.update(evaluate(run,scene,evaluator,camera_checks))
                except Exception as error:row.update(auditPassed=False,error=type(error).__name__+': '+str(error))
                rows.append(row)
                result=dict(schema='puppybot.neural-native-comparison.v1',rows=rows,explorationOnly=True,
                            sixBrickCollectionTested=False,nativeClosedLoopImprovementProven=False,
                            scope='Bounded wrist-RGB exploration; no broad generalization or collection claim')
                (out/'native-summary.json').write_text(json.dumps(result,indent=2)+'\n')
                print(json.dumps(row),flush=True)
    fields=sorted(set().union(*(row.keys() for row in rows)))
    with (out/'native-summary.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(rows)


if __name__=='__main__':main()
