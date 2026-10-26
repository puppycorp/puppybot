#!/usr/bin/env python3
"""Check fresh box initialization from an occluded RGB rim pattern."""
import argparse
import json
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile

sys.path=[p for p in sys.path if Path(p).resolve()!=Path(__file__).resolve().parent]
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[2]


def compile_probe(directory):
    source=(ROOT/'flex/sim/main.flex').read_text().replace('fn main(argc, argv)','fn ps_application_main(argc, argv)')
    source=re.sub(r'^import "([^"]+)";',lambda m:'import '+json.dumps(str(ROOT/'flex/sim'/m[1]))+';',source,flags=re.MULTILINE)
    source+=r'''
fn main(argc,argv) {
    if !pl_init() || !ps_catalog_load() || !ps_case_load(ps_case_find("discover-house-blocks-into-box")) {return 1;}
    let capacity=16+8*(104+640*480*3);let data=alloc(capacity+1);let size=pl_read_file(load64(argv+8),data,capacity);let count=load64(data);
    if count<1 || count>8 || size!=16+count*(104+640*480*3) {return 2;}
    if load64(data+8) {store64(ps_case_bin+32,load64(ps_case_bin+24));}
    ps_brick_rgb=alloc(640*480*3);ps_brick_pose=alloc(96);ps_brick_mask=alloc(640*480);ps_brick_queue=alloc(640*480*8);ps_dock_reset();
    // Current RGB must initialize without a remembered or true box pose.
    ps_environment=1;ps_environment_start=1;ps_x=f64_from_i64(99);ps_y=f64_from_i64(-99);ps_heading=PB_PI;
    store64(ps_dock_frame+96,ps_x);store64(ps_dock_frame+104,ps_y);ps_dock_yaw=PB_PI;
    let text=alloc(4096);let b=alloc(32);pl_builder(b,text,4096);pl_char(b,91);let i=0;
    while i<count {
        let frame=data+16+i*(104+640*480*3);ps_total=load64(frame);pb_copy(ps_brick_pose,frame+8,96);pb_copy(ps_brick_rgb,frame+104,640*480*3);
        let valid=ps_dock_detect();if i {pl_char(b,44);}pl_text(b,"{\"valid\":");pj_bool_text(b,valid);pl_text(b,",\"patches\":");pl_int(b,ps_dock_count);pl_text(b,",\"used\":");pl_int(b,ps_dock_used);pl_text(b,",\"stable\":");pl_int(b,ps_dock_stable);pl_text(b,",\"frameId\":");pl_int(b,ps_dock_seen);
        pl_text(b,",\"pose\":[");pl_float(b,load64(ps_dock_frame+96));pl_char(b,44);pl_float(b,load64(ps_dock_frame+104));pl_char(b,44);pl_float(b,ps_dock_yaw);pl_text(b,"]}");i=i+1;
    }
    pl_text(b,"]\n");pl_print(1,text);return 0;
}
'''
    entry,binary=directory/'probe.flex',directory/'probe';entry.write_text(source)
    subprocess.run([os.environ.get('FLEXSCRIPT_COMPILER',str(ROOT/'build/flex/pup-compiler')),str(entry),'-o',str(binary)],cwd=ROOT,check=True)
    return binary


def detect(binary,directory,name,frames,square=False):
    records=[]
    for i,frame in enumerate(frames):
        image,calibration=frame[:2];frame_id=frame[2] if len(frame)>2 else (i+1)*10
        records.append(struct.pack('<Q12d',frame_id,*calibration)+image.tobytes())
    path=directory/(name+'.bin');path.write_bytes(struct.pack('<2Q',len(frames),square)+b''.join(records))
    result=subprocess.run([str(binary),str(path)],cwd=ROOT,capture_output=True,text=True,check=True)
    states=json.loads(result.stdout);(directory/(name+'.json')).write_text(json.dumps(states,indent=2)+'\n');return states


def image_pattern(indices,angle=0,square=False,stretch=1):
    width=.228*stretch;depth=.228 if square else .208
    points=np.array([[-width/2,-depth/2],[width/2,-depth/2],[-width/2,depth/2],[width/2,depth/2],[-width/2,0],[width/2,0],[0,-depth/2],[0,depth/2]])
    c,s=math.cos(angle),math.sin(angle);points=points@np.array([[c,s],[-s,c]])
    image=np.full((480,640,3),80,np.uint8)
    for x,y in points[indices]:
        u,v=np.rint([320+x*415.6921938/.401,240-y*415.6921938/.401]).astype(int)
        image[v-3:v+3,u-3:u+3]=[220,20,200]
    return image,[.31,-.22,.5,0,0,-1,1,0,0,0,-1,0]


def check_geometry(state,expected):
    assert state['valid'],state
    assert math.dist(state['pose'][:2],expected[:2])<.004,(state,expected)
    delta=(state['pose'][2]-expected[2]+math.pi/2)%math.pi-math.pi/2
    assert abs(delta)<.03,(state,expected)


def check_pose(states,expected):
    for state in states:check_geometry(state,expected)
    assert states[-1]['stable']>=3 and states[-1]['frameId']==30


def recorded(binary,directory,path,frame):
    states=[]
    for line in path.open():
        state=json.loads(line)
        if state['step']==frame:states.append(state);break
    assert len(states)==1
    frames=[];expected=[]
    for state in states:
        p=state['case']['perception'];assert p['frameId']==state['step']
        image=cv2.cvtColor(cv2.imread(str(path.parent/'sensor'/p['image'])),cv2.COLOR_BGR2RGB)
        frames.append((image,p['calibration'],state['step']))
        x,y,h=state['pose'];ex,ey,eh=state['localization']['pose'];delta=eh-h;c,s=math.cos(delta),math.sin(delta)
        box=state['case']['container'];bx,by,_=box['position'];qx,qy,qz,qw=box['quaternion'];yaw=math.atan2(2*(qw*qz+qx*qy),1-2*(qy*qy+qz*qz))
        expected.append([ex+c*(bx-x)-s*(by-y),ey+s*(bx-x)+c*(by-y),yaw+delta])
    result=detect(binary,directory,'recorded',frames)
    for state,truth in zip(result,expected):check_geometry(state,truth)
    assert result[0]['used']>=4 and result[0]['stable']==1 and result[0]['frameId']==frame
    print('Recorded RGB passed: the occluded box initializes from a fresh image without a prior, with independent pose error below 4 mm')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--recorded',type=Path);parser.add_argument('--frame',type=int);parser.add_argument('--output',type=Path);args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='dock-patterns-',dir=ROOT/'build/flex/sim') as temporary:
        directory=args.output or Path(temporary)
        if args.output:directory.mkdir(parents=True,exist_ok=False)
        binary=compile_probe(directory)
        for name,indices,angle in [('depth-edge',[7,3,5,1],0),('rotated',[7,3,5,1],.37),('width-edge',[0,1,6,5],-1.1),('five-patches',[0,1,4,5,6],.2),('four-corners',[0,1,2,3],-.3)]:
            state=detect(binary,directory,name,[image_pattern(indices,angle)]*3);check_pose(state,[.31,-.22,angle])
        for name,indices,square,stretch in [('collinear',[1,3,5],False,1),('two-patches',[1,3],False,1),('square-ambiguous',[7,3,5,1],True,1),('wrong-size',[7,3,5,1],False,1.3)]:
            state=detect(binary,directory,name,[image_pattern(indices,square=square,stretch=stretch)]*3,square)
            assert not any(s['valid'] for s in state),(name,state)
        first=image_pattern([7,3,5,1]);partial=image_pattern([1,3])
        stale=detect(binary,directory,'stale',[(first[0],first[1],10),(partial[0],partial[1],2000),(partial[0],partial[1],2010)])
        assert stale[0]['valid'] and not any(s['valid'] for s in stale[1:])
        print('Rim pattern checks passed: rotated four-patch L views initialize from RGB; two/collinear patches, ambiguous squares and wrong dimensions cannot confirm a box')
        if args.recorded:
            if args.frame is None:parser.error('--recorded requires --frame')
            recorded(binary,directory,args.recorded,args.frame)


if __name__=='__main__':main()
