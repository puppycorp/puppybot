#!/usr/bin/env python3
"""Reconstruct a saved arm state and test survey-target kinematics offline."""
import hashlib
import json
import math
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRACE = ROOT / 'build/flex/sim/levels-v2/pitch82/observed-footprint-matched-monitored-v2/trial/candidate-search/run/trace.jsonl'
MAIN = ROOT / 'flex/sim/main.flex'
COMPILER = ROOT / 'build/flex/control/compiler'
ASSET = ROOT / 'build/flex/sim/puppybot.bin'
RGB = ROOT / 'build/flex/sim/levels-v2/pitch82/observed-footprint-matched-monitored-v2/trial/candidate-search/diagnostic/survey-60.rgb'
RGB_REFERENCE = ROOT / 'build/flex/sim/levels-v2/pitch82/dock-barrier-rendered-monitored-v1/trial/candidate-search/diagnostic/survey-60.rgb'
REFERENCE = ROOT / 'experiments/dock-marker-blue-support-v1/barrier-inputs.json'
FRAME = 11477


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''): h.update(block)
    return h.hexdigest()


def num(value):
    if not isinstance(value, (float, int)) or not math.isfinite(value): raise ValueError('bad coordinate')
    return f'ps_number({round(value * 1000000000)},1000000000)'


def source(record):
    main = MAIN.read_text()
    if main.count('fn main(argc, argv)') != 1: raise ValueError('unexpected simulator entry')
    main = main.replace('fn main(argc, argv)', 'fn old_simulator_main(argc, argv)', 1)
    main = re.sub(r'^import "([^"]+)";', lambda m: 'import ' + json.dumps(str(ROOT/'flex/sim'/m[1])) + ';', main, flags=re.M)
    pose = record['localization']['pose']; old_box = record['case']['dockVision']['positionM']; ticks = record['ticks']
    if len(pose)!=3 or len(old_box)!=3 or len(ticks)!=4 or any(type(v)!=int for v in ticks): raise ValueError('invalid recorded state')
    base = r'''
fn main(argc, argv) {
 if !pl_init() {return 1;} h_environment(argc, argv);
 if !ps_model_load("build/flex/sim/puppybot.bin") {return 2;}
 ps_robot=alloc(8192);ps_system=alloc(2048);ps_config=alloc(448);ps_app=alloc(2048);ps_bus=alloc(16384);ps_plant=alloc(2048);ps_trace=alloc(69632);
 pb_config_default(ps_config);gs_init(ps_plant,ps_config,ps_bus,42,-1);if pb_robot_configure(ps_robot,ps_config,0) {return 3;}
 pb_system_init(ps_system,ps_robot);pr_init(ps_app,ps_robot,ps_system,ps_config,"build/flex/sim/config.json",1,pl_now());
 let i=0;while i<64 {gs_step(ps_plant);if pb_fake_cycle(ps_system,ps_bus,i*20,ps_trace,1024)<0 {return 4;}i=i+1;}
 ps_local_mode=2;ps_local_x=POSEX;ps_local_y=POSEY;ps_local_heading=POSEH;ps_camera_drive_mode=0;ps_pickup_targets=alloc(32);
 let initial=alloc(32);store64(initial,TICK0);store64(initial+8,TICK1);store64(initial+16,TICK2);store64(initial+24,TICK3);
 i=0;while i<4 {store64(ps_plant+128+i*64+16,load64(initial+i*8));i=i+1;}
 let camera=alloc(96);ps_local_camera(camera);let output=alloc(196608);let b=alloc(32);pl_builder(b,output,196608);
 pl_text(b,"{\"kind\":\"recordedCamera\",\"camera\":[");i=0;while i<12 {if i {pl_char(b,44);}pl_float(b,load64(camera+i*8));i=i+1;}pl_text(b,"]}\n");
 let frame=ps_asset+64+ps_groups*256+24;let c=f64_cos(ps_pose_heading());let s=f64_sin(ps_pose_heading());
 let x=f64_add(ps_pose_x(),f64_sub(f64_mul(c,load64(frame)),f64_mul(s,load64(frame+8))));
 let y=f64_add(ps_pose_y(),f64_add(f64_mul(s,load64(frame)),f64_mul(c,load64(frame+8))));
 let bearing=f64_atan2(f64_sub(BOXY,y),f64_sub(BOXX,x));let point=alloc(24);
 let radius=4;while radius<=16 {let height=340;while height<=400 {let pitch=65;while pitch<=90 {let turn=-40;while turn<=20 {
  i=0;while i<4 {store64(ps_plant+128+i*64+16,load64(initial+i*8));i=i+1;}
  let angle=f64_add(bearing,pb_radians(f64_from_i64(turn)));
  store64(point,f64_add(x,f64_mul(ps_number(radius,100),f64_cos(angle))));
  store64(point+8,f64_add(y,f64_mul(ps_number(radius,100),f64_sin(angle))));
  if ps_arm_solve(point,height,pitch) {
   let move=ps_arm_move_ticks();i=0;while i<4 {store64(ps_plant+128+i*64+16,load64(ps_pickup_targets+i*8));i=i+1;}
   ps_local_camera(camera);pl_text(b,"{\"kind\":\"candidate\",\"radiusCm\":");pl_int(b,radius);
   pl_text(b,",\"heightMm\":");pl_int(b,height);pl_text(b,",\"pitchDeg\":");pl_int(b,pitch);
   pl_text(b,",\"turnDeg\":");pl_int(b,turn);pl_text(b,",\"maxTravelTicks\":");pl_int(b,move);
   pl_text(b,",\"ticks\":[");i=0;while i<4 {if i {pl_char(b,44);}pl_int(b,load64(ps_pickup_targets+i*8));i=i+1;}
   pl_text(b,"],\"camera\":[");i=0;while i<12 {if i {pl_char(b,44);}pl_float(b,load64(camera+i*8));i=i+1;}pl_text(b,"]}\n");
  }turn=turn+10;}pitch=pitch+5;}height=height+20;}radius=radius+2;}
 if load64(b+24) {return 5;}pl_write(1,output,load64(b+8));return 0;
}
'''
    for key,value in {'POSEX':num(pose[0]), 'POSEY':num(pose[1]), 'POSEH':num(pose[2]), 'BOXX':num(old_box[0]), 'BOXY':num(old_box[1]), **{f'TICK{i}':str(t) for i,t in enumerate(ticks)}}.items():
        base = base.replace(key,value)
    return main+'\n'+base


def main():
    paths = [Path(__file__).resolve(), COMPILER, ASSET, TRACE, RGB, RGB_REFERENCE, REFERENCE]
    paths += sorted((ROOT / 'flex/sim').glob('*.flex'))
    inputs = {str(p.relative_to(ROOT)):sha(p) for p in paths}
    reference = json.loads(REFERENCE.read_text())
    if sha(RGB) != sha(RGB_REFERENCE) or reference['files'][str(RGB_REFERENCE.relative_to(ROOT))] != sha(RGB_REFERENCE):
        raise ValueError('saved image differs from the prior offline fit')
    with TRACE.open() as f:
        matches = []
        for line in f:
            item = json.loads(line)
            if item.get('step') == FRAME: matches.append(item)
    if len(matches)!=1: raise ValueError('expected one recorded frame')
    record=matches[0]; text=source(record)
    with tempfile.TemporaryDirectory(prefix='puppy-dock-aim-') as temp:
        entry=Path(temp)/'probe.flex'; exe=Path(temp)/'probe'; entry.write_text(text)
        subprocess.run([str(COMPILER),str(entry),'-o',str(exe)],cwd=ROOT,check=True,capture_output=True,timeout=120)
        raw=subprocess.run([str(exe)],cwd=ROOT,check=True,capture_output=True,text=True,timeout=30).stdout
    rows=[json.loads(line) for line in raw.splitlines()]; baseline=rows[0]['camera']; saved=record['case']['perception']['calibration']
    if max(abs(a-b) for a,b in zip(baseline,saved))>1e-6: raise ValueError('reconstructed camera mismatch')
    # Use an offline saved native fit only for scoring, not for generating commands.
    target=[-1.366619883754643,-.40133213072795915,.099]; focal=415.69224
    candidates=[]
    for row in rows[1:]:
        camera=row['camera']; ray=[target[i]-camera[i] for i in range(3)];depth=sum(ray[i]*camera[i+3] for i in range(3))
        if depth<=0:continue
        row['estimatedPixel']=[320+focal*sum(ray[i]*camera[i+6] for i in range(3))/depth,240+focal*sum(ray[i]*camera[i+9] for i in range(3))/depth]
        row['depthM']=depth; candidates.append(row)
    baseline_targets = [r for r in candidates if (r['radiusCm'],r['heightMm'],r['pitchDeg'],r['turnDeg']) == (4,380,80,-20)]
    if len(baseline_targets) != 1 or baseline_targets[0]['ticks'] != record['case']['surveyHigh']['targetTicks']:
        raise ValueError('existing survey target does not reproduce')
    local = record['localization']['pose']; world = record['pose']; c, s = math.cos(local[2]), math.sin(local[2])
    dx, dy = target[0]-local[0], target[1]-local[1]
    relative = [c*dx+s*dy,-s*dx+c*dy]; c, s = math.cos(world[2]), math.sin(world[2])
    inferred = [world[0]+c*relative[0]-s*relative[1],world[1]+s*relative[0]+c*relative[1]]
    container = record['case']['container']['position'][:2]
    if inputs != {str(p.relative_to(ROOT)):sha(p) for p in paths}: raise ValueError('inputs changed')
    print(json.dumps({'schema':'puppybot.dock-aim-kinematics.v1','frame':FRAME,'inputSHA256':inputs,'estimatedBoxForCommand':record['case']['dockVision']['positionM'], 'offlineTarget':target,'offlineTargetRelative':relative,'offlineTargetTruthErrorM':math.dist(inferred,container),'savedCamera':saved,'reconstructedCamera':baseline,'validIKCandidates':len(candidates),'candidates':candidates},indent=2))


if __name__=='__main__': main()
