#!/usr/bin/env python3
"""Replay a recorded long-yaw release with fresh RGB and physical clearance checks."""
import argparse
import hashlib
import importlib.util
import json
import mmap
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def replay(recorded,frame,out):
    recorded=recorded.resolve();out=out.resolve()
    with recorded.open('rb') as stream:
        data=mmap.mmap(stream.fileno(),0,access=mmap.ACCESS_READ)
        index=data.find(f'"totalSteps":{frame},'.encode());assert index>=0
        start=data.rfind(b'\n',0,index)+1;end=data.find(b'\n',index);state=json.loads(data[start:end])
    assert state['case']['phase']=='carrying' and state['gripper']['held']
    target=state['controller']['arm']['joints'][0]['targetTick']
    assert target is not None and abs(target-state['ticks'][0])>3000
    spec=importlib.util.spec_from_file_location('dock_fixture',ROOT/'flex/tests/sim-discovery-dock.py')
    fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
    before='if !ps_dock_search_next() {return 8;}'
    assert fixture.NATIVE.count(before)==1
    fixture.NATIVE=fixture.NATIVE.replace(before,r'''
 if !ps_case_dock_approach() {return 8;}
 if !ps_case_drop_turning || ps_case_drop_timeout<=1000 || ps_case_drop_timeout>1500 {return 11;}
 let axis=1;while axis<4 {
  if load64(ps_pickup_targets+axis*8)!=load64(ps_plant+144+axis*64) {return 12;}axis=axis+1;
 }
''')
    files=[*ROOT.glob('flex/sim/*.flex'),ROOT/'flex/core/kinematics.flex',ROOT/'flex/vision/discovery.py',ROOT/'flex/sim/cases/discover-house-blocks-into-box.json',ROOT/'build/flex/sim/puppybot.bin',ROOT/'build/flex/sim/environments/apartment/apartment.bin',Path(__file__).resolve(),ROOT/'flex/tests/sim-discovery-dock.py',ROOT/'flex/tests/sim-discovery-pickup.py']
    manifest={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    fixture.replay(recorded,frame,out)
    assert all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest for name,digest in manifest.items())
    first_command=None;lowering=None;release=None;first=previous=None;held_pose=None
    for line in (out/'trace.jsonl').open():
        s=json.loads(line)
        if first is None:first=s
        assert s['pose']==first['pose'] and s['localization']['pose']==first['localization']['pose']
        assert not s['controller']['drive']['leftSpeed'] and not s['controller']['drive']['rightSpeed']
        joints=s['controller']['arm']['joints']
        if first_command is None and s['case']['phase']=='carrying':
            first_command=s;held_pose=s['ticks'][1:]
            assert joints[0]['targetTick'] is not None and abs(joints[0]['targetTick']-s['ticks'][0])>3000
            assert all(joint['targetTick'] in (None,tick) for joint,tick in zip(joints[1:],held_pose))
        if first_command and lowering is None and any(joint['targetTick'] is not None and joint['targetTick']!=tick for joint,tick in zip(joints[1:],held_pose)):
            lowering=s['step']
        if first_command and lowering is None:assert s['ticks'][1:]==held_pose
        if previous and previous['gripper']['held'] and not s['gripper']['held']:release=s['step']
        previous=s
    assert first_command and lowering and release and first_command['step']<lowering<release
    assert lowering-first_command['step']>1000, 'fixture did not exercise the old fixed deadline'
    assert previous['case']['inside']==previous['case']['placed']==state['case']['placed']+1
    manifest[str((out/'probe.flex').relative_to(ROOT))]=hashlib.sha256((out/'probe.flex').read_bytes()).hexdigest()
    manifest[str((out/'probe').relative_to(ROOT))]=hashlib.sha256((out/'probe').read_bytes()).hexdigest()
    (out/'source-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    result=dict(passed=True,checkpointReplayOnly=True,fullMissionVerified=False,recordedCommandStep=frame,stagedYawCommandStep=first_command['step'],loweringCommandStep=lowering,yawStageExceededOldDeadline=True,freshRGBReleaseStep=release,baseStayedStationary=True,heldClearanceVerified=True,originalDeliveriesRetained=state['case']['placed'],settledInside=previous['case']['inside'],sourceManifestMatches=True)
    (out/'release-audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recorded',type=Path,required=True);parser.add_argument('--frame',type=int,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    replay(args.recorded,args.frame,args.output)


if __name__=='__main__':main()
