#!/usr/bin/env python3
"""Replay a recorded hybrid docking state using recorded RGB-derived maps.

Usage: python3 -I flex/tests/hybrid-dock-replay.py TRIAL_DIR MAP_DIR

The inputs must be the retained 29980-tick selection run and its dock-1
mapping directory; this is a CPU-only feasibility probe, not a delivery test.
"""
import hashlib,json,re,struct,subprocess,sys,tempfile
from pathlib import Path
if len(sys.argv) != 3:
 raise SystemExit(__doc__)
root=Path(__file__).resolve().parents[2]
trial=Path(sys.argv[1]).resolve()
mappath=Path(sys.argv[2]).resolve()
trace=trial/'run/trace.jsonl'
inputs=json.loads((trial/'run/inputs.json').read_text())
result=json.loads((trial/'run/result.json').read_text())
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
 return h.hexdigest()
if sha(trace)!=result['traceSHA256'] or sha(trial/'inputs/case.json')!=inputs['caseSHA256'] or sha(trial/'inputs/environment.bin')!=inputs['environmentSHA256'] or sha(root/'build/flex/sim/puppybot.bin')!=inputs['robotAssetSHA256']:
 raise ValueError('trial input or trace hash mismatch')
expected={'observed':'aa7e818729a1e01736647a52e4916f33a273e8839cf5388654839fe2371974c9','safe':'6d14bb131701b9f9ffc659279467e9f84a4de83fbd77ad5ea534c8e5a1772613','observed-detail':'54eebf005e44cfea5657b36c8b4d912acdb49f75204d27cf1d4b5174f242cc6d'}
for name,value in expected.items():
 if sha(mappath/f'{name}-27255.bin')!=value:raise ValueError(f'map snapshot mismatch: {name}')
capture=current=home=None
for line in trace.open():
 s=json.loads(line)
 if home is None and s['discovery']['pickup']['boxLearned']:home=s['localization']['pose']
 if capture is None and s['gripper']['held']:capture=s
 if s['step']==28065: current=s; break
if not capture or not current or home is None or not current['gripper']['held']:
 raise ValueError('missing captured grasp, local home or held object at the requested frame')
dock=current['case']['dockVision']
if not dock['valid'] or dock['stableObservations']<3:
 raise ValueError('recorded box estimate was not fresh and stable')
fixture=struct.pack('<6d4q',*capture['localization']['pose'],*capture['case']['pickupTargetM'],*capture['ticks'])
fixture+=struct.pack('<3d4q3dq',*current['localization']['pose'],*current['ticks'],*dock['positionM'][:2],dock['yawRad'],current['case']['placed'])
fixture+=struct.pack('<5d',*current['case']['boxSearch']['centreM'],*home)
if len(fixture)!=208:raise ValueError('invalid replay fixture length')
source=(root/'flex/sim/main.flex').read_text().replace('fn main(argc, argv)','fn ps_application_main(argc, argv)')
source=re.sub(r'^import "([^"]+)";',lambda m:'import '+json.dumps(str(root/'flex/sim'/m[1]))+';',source,flags=re.MULTILINE)
source+=r'''
fn fixture_pose(data,offset,ticks) {
 ps_local_x=load64(data+offset);ps_local_y=load64(data+offset+8);ps_local_heading=load64(data+offset+16);let i=0;
 while i<4 {let tick=load64(data+ticks+i*8);store64(ps_plant+128+i*64,tick*1000);store64(ps_plant+128+i*64+16,tick);pb_arm_feedback(ps_robot,i,tick,ps_time);i=i+1;}return 1;
}
fn main(argc,argv) {
 if !pl_init() || !ps_catalog_load() {return 1;}let index=ps_case_file(load64(argv+8));if index<0 || !ps_case_load(index) || !ps_model_load("build/flex/sim/puppybot.bin") || !ps_environment_load(load64(argv+48)) {return 2;}
 ps_robot=alloc(8192);ps_system=alloc(2048);ps_config=alloc(448);ps_app=alloc(2048);ps_bus=alloc(16384);ps_plant=alloc(2048);ps_trace=alloc(69632);ps_json=alloc(16384);ps_builder=alloc(32);pb_config_default(ps_config);pb_vset(ps_config+40,2,5);ps_local_requested=2;
 if !ps_reset() {return 3;}let data=alloc(208);if pl_read_file(load64(argv+16),data,208)!=208 {return 4;}
 fixture_pose(data,0,48);pb_copy(ps_case_target,data+24,24);ps_case_attachment_capture();fixture_pose(data,80,104);ps_case_placed=load64(data+160);ps_gripper_held=1;ps_collect_busy=1;ps_agent_physical=1;ps_house_ready=1;ps_house_returning=1;ps_dock_seen=0;ps_dock_valid=1;ps_dock_stable=3;
 ps_identity(ps_dock_frame);ps_dock_yaw=load64(data+152);store64(ps_dock_frame,f64_cos(ps_dock_yaw));store64(ps_dock_frame+8,f64_sin(ps_dock_yaw));store64(ps_dock_frame+32,pb_neg(f64_sin(ps_dock_yaw)));store64(ps_dock_frame+40,f64_cos(ps_dock_yaw));store64(ps_dock_frame+96,load64(data+136));store64(ps_dock_frame+104,load64(data+144));
 if pl_read_file(load64(argv+24),ps_discovery_observed,40000)!=40000 || pl_read_file(load64(argv+32),ps_nav_map,40000)!=40000 || pl_read_file(load64(argv+40),ps_discovery_detail,1000000)!=1000000 {return 5;}ps_discovery_detail_ready=1;
 ps_dock_search_anchor=alloc(32);ps_dock_search_goal=alloc(24);pb_copy(ps_dock_search_anchor,data+168,16);store64(ps_dock_search_anchor+16,f64_atan2(f64_sub(load64(data+192),load64(data+176)),f64_sub(load64(data+184),load64(data+168))));store64(ps_dock_search_anchor+24,load64(data+200));
 let out=alloc(1024);let b=alloc(32);pl_builder(b,out,1024);pl_text(b,"floor=");pl_int(b,ps_floor_clear(ps_pose_x(),ps_pose_y(),ps_pose_heading()));pl_text(b," observed=");pl_int(b,ps_nav_observed_clear(ps_pose_x(),ps_pose_y(),ps_pose_heading()));pl_text(b," boxgap=");pl_float(b,ps_nav_box_gap(ps_pose_x(),ps_pose_y(),ps_pose_heading()));pl_text(b," nav=");pl_int(b,ps_nav_clear(ps_pose_x(),ps_pose_y(),ps_pose_heading()));pl_text(b," drop_find=");pl_int(b,ps_case_drop_find(180,ps_pose_x(),ps_pose_y(),ps_pose_heading()));pl_text(b," drop_clearance=");pl_int(b,ps_case_drop_clearance(180,ps_pose_x(),ps_pose_y(),ps_pose_heading()));pl_text(b," reachable=");pl_int(b,ps_dock_search_reachable());pl_text(b,"\n");pl_write(1,out,load64(b+8));
 ps_total=100;ps_dock_seen=0;if ps_dock_search_stage() {return 6;} // stale observations cannot enter the new fallback
 ps_dock_seen=ps_total;let start=pl_now();if !ps_dock_search_stage() {return 7;}let elapsed=pl_now()-start;
 let end=alloc(24);ps_nav_end_pose(end);let valid_end=ps_nav_clear(load64(end),load64(end+8),load64(end+16)) && ps_case_drop_clearance(180,load64(end),load64(end+8),load64(end+16));
 if !valid_end && !ps_house_parking_clear(end,ps_nav_goal) {return 8;}
 if !ps_nav_clear(load64(ps_dock_search_goal),load64(ps_dock_search_goal+8),load64(ps_dock_search_goal+16)) || !ps_case_drop_clearance(180,load64(ps_dock_search_goal),load64(ps_dock_search_goal+8),load64(ps_dock_search_goal+16)) {return 9;}
 pl_builder(b,out,1024);pl_text(b,"recorded-stage=1 wall-ms=");pl_int(b,elapsed);pl_text(b," goal=[");pl_float(b,load64(ps_dock_search_goal));pl_text(b,",");pl_float(b,load64(ps_dock_search_goal+8));pl_text(b,",");pl_float(b,load64(ps_dock_search_goal+16));pl_text(b,"]\n");pl_write(1,out,load64(b+8));
 let i=0;while i<40000 {store8(ps_discovery_observed+i,1);store8(ps_nav_map+i,1);i=i+1;}i=0;while i<1000000 {store8(ps_discovery_detail+i,1);i=i+1;}
 if ps_dock_search_stage() {return 10;}pl_print(1,"unknown-floor negative control rejected\n");return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='puppy-dock-replay-') as directory:
 entry=Path(directory)/'probe.flex';binary=Path(directory)/'probe';data=Path(directory)/'fixture.bin'
 entry.write_text(source);data.write_bytes(fixture)
 subprocess.run([str(root/'build/flex/control/compiler'),str(entry),'-o',str(binary)],cwd=root,check=True)
 case=trial/'inputs/case.json';environment=trial/'inputs/environment.bin'
 args=[str(binary),str(case),str(data)]+[str(mappath/f'{n}-27255.bin') for n in ('observed','safe','observed-detail')]+[str(environment)]
 print('trace capture',capture['step'],'dock',current['step'],'scene and map hashes verified',flush=True)
 subprocess.run(args,cwd=root,check=True,timeout=40)
