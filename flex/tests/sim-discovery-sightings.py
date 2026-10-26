#!/usr/bin/env python3
"""Replay distant wrist RGB sightings without permitting unknown-floor pickup."""
import argparse
import hashlib
import importlib.util
import json
import math
import mmap
import os
from pathlib import Path
import re
import subprocess
import sys

sys.path = [p for p in sys.path if Path(p).resolve() != Path(__file__).resolve().parent]
import cv2

ROOT = Path(__file__).resolve().parents[2]


def replay(recorded,frames,out):
    spec=importlib.util.spec_from_file_location('approach_fixture',ROOT/'flex/tests/sim-discovery-approach.py')
    fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
    states=[]
    with recorded.open('rb') as stream:
        data=mmap.mmap(stream.fileno(),0,access=mmap.ACCESS_READ)
        for frame in frames:
            index=data.find(f'"totalSteps":{frame},'.encode());assert index>=0
            start=data.rfind(b'\n',0,index)+1;end=data.find(b'\n',index);state=json.loads(data[start:end])
            assert state['case']['perception']['frameId']==frame and not state['gripper']['held']
            states.append(state)
    # The expectation is an archived RGB floor-ray estimate, not a body pose.
    points=[d['targetM'] for d in states[-1]['case']['perception']['detections'] if 1.3<math.dist(d['targetM'][:2],states[-1]['localization']['pose'][:2])<2]
    assert len(points)==1,'last frame must have one distant RGB target'
    expected=points[0]
    assert all(any(math.dist(d['targetM'][:2],expected[:2])<.06 and math.dist(d['targetM'][:2],s['localization']['pose'][:2])>1.3 for d in s['case']['perception']['detections']) for s in states)
    out.mkdir(parents=True,exist_ok=False)
    source=(ROOT/'flex/sim/main.flex').read_text().replace('fn main(argc, argv)','fn ps_application_main(argc, argv)')
    source=re.sub(r'^import "([^"]+)";',lambda m:'import '+json.dumps(str(ROOT/'flex/sim'/m[1]))+';',source,flags=re.M)
    source+=r'''
fn main() {
    if !pl_init() || !ps_catalog_load() || !ps_case_load(ps_case_find("discover-house-blocks-into-box")) || !ps_environment_load("build/flex/sim/environments/apartment/apartment.bin") || !ps_model_load("build/flex/sim/puppybot.bin") {return 1;}
    ps_robot=alloc(8192);ps_system=alloc(2048);ps_config=alloc(448);ps_app=alloc(2048);ps_bus=alloc(16384);ps_plant=alloc(2048);ps_trace=alloc(69632);pb_config_default(ps_config);pb_vset(ps_config+40,2,5);
    if !ps_reset() {return 2;}ps_case_phase(26);ps_discovery_phase=6;ps_collect_busy=0;ps_house_ready=1;ps_collect_map_until=0;ps_discovery_scans=1;
    ps_brick_rgb=alloc(640*480*3);ps_brick_mask=alloc(640*480);ps_brick_queue=alloc(640*480*8);ps_brick_records=alloc(16*128);ps_brick_pose=alloc(96);ps_brick_scratch=alloc(128);
    ps_x=f64_nan();ps_y=f64_nan();ps_heading=f64_nan();ps_environment=1;ps_environment_count=99999;
'''
    files=[];inputs=[]
    for index,state in enumerate(states):
        frame=state['step'];perception=state['case']['perception'];png=recorded.parent/'sensor'/f'frame-{frame}.png';raw=out/f'frame-{frame}.rgb'
        raw.write_bytes(cv2.cvtColor(cv2.imread(str(png)),cv2.COLOR_BGR2RGB).tobytes());files.extend([png,raw])
        source+=f'ps_total={frame};ps_time={frame*20};ps_camera_drive_mode={1 if state["camera"]["pose"]=="driving" else 0};'
        source+=''.join(f'{name}={fixture.word(value)};' for name,value in zip(['ps_local_x','ps_local_y','ps_local_heading'],state['localization']['pose']))
        for i,tick in enumerate(state['ticks']):
            source+=f'store64(ps_plant+{128+i*64},{tick*1000});store64(ps_plant+{136+i*64},0);store64(ps_plant+{144+i*64},{tick});pb_fake_servo(ps_bus,load64(ps_plant+{152+i*64}),{tick});pb_arm_feedback(ps_robot,{i},{tick},ps_time);'
        source+=''.join(f'store64(ps_brick_pose+{i*8},{fixture.word(value)});' for i,value in enumerate(perception['calibration']))
        source+=f'if pl_read_file({json.dumps(str(raw.resolve()))},ps_brick_rgb,640*480*3)!=640*480*3{{return 3;}}ps_collect_observe();'
        if index<2:source+='if ps_collect_attention(){return 4;}'
        inputs.append(dict(frameId=frame,pose=state['localization']['pose'],ticks=state['ticks'],calibration=perception['calibration'],rgb=str(raw.resolve())))
    source+=f'let found=0;let i=0;while i<ps_collect_count{{let p=ps_collect_points+i*64;if load64(p+32)>=3&&ps_floor_near({fixture.word(expected[0])},{fixture.word(expected[1])},p,ps_number(6,100)){{found=1;}}i=i+1;}}if !found{{return 5;}}'
    source+=r'''
    if ps_collect_select(){return 6;}let drive=pb_robot_drive(ps_robot);if load64(drive+48)||load64(drive+56)||pb_a(ps_robot,PB_A_MODE){return 7;}
    i=0;while i<40000{if load8(ps_nav_map+i)!=1||load8(ps_discovery_observed+i)!=1{return 8;}i=i+1;}
    pl_print(1,"Distant RGB target confirmed; unknown floor still forbids pickup and driving; poisoned world inputs unused.\n");return 0;
}
'''
    entry,binary=out/'probe.flex',out/'probe';entry.write_text(source)
    (out/'input.json').write_text(json.dumps(dict(scope='Recorded RGB and own pose/encoder calibration only',frames=inputs,expectedOwnRGBTarget=expected),indent=2)+'\n')
    files.extend([*ROOT.glob('flex/sim/*.flex'),ROOT/'flex/core/kinematics.flex',Path(__file__).resolve(),entry])
    manifest={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files};(out/'source-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    subprocess.run([os.environ.get('FLEXSCRIPT_COMPILER',str(ROOT/'build/flex/pup-compiler')),str(entry),'-o',str(binary)],cwd=ROOT,check=True)
    result=subprocess.run([str(binary)],cwd=ROOT,capture_output=True,text=True,timeout=120);(out/'run.log').write_text(result.stdout+result.stderr)
    assert result.returncode==0,(result.returncode,result.stdout,result.stderr)
    assert all(hashlib.sha256(Path(name).read_bytes()).hexdigest()==digest for name,digest in manifest.items())
    report=dict(passed=True,recordedImages=len(frames),confirmedDistantRGBTarget=True,unknownFloorStillBlocksPickup=True,poisonedWorldInputsUnused=True,sourceManifestMatches=True,fullMissionVerified=False)
    (out/'audit.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--recorded',type=Path,required=True);parser.add_argument('--frames',type=int,nargs='+',required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    assert len(args.frames)>=3 and args.frames==sorted(set(args.frames))
    replay(args.recorded,args.frames,args.output)


if __name__=='__main__':main()
