#!/usr/bin/env python3
"""Replay short observed-floor waypoint proposals against one saved map."""
import hashlib
import importlib.util
import json
import math
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / 'build/flex/sim/levels-v2/pitch82/dock-floor-refresh-build-v2'
TRACE = ROOT / 'build/flex/sim/levels-v2/pitch82/dock-short-waypoint-monitored-v1/trial/candidate-search/run/trace.jsonl'
MAP = ROOT / 'build/flex/sim/discovery-2701217/episode-1/dock-1'
COMPILER = ROOT / 'build/flex/control/compiler'
TRANSFORM = ROOT / 'experiments/dock-short-waypoint-v1/transform.py'
CASE = ROOT / 'build/flex/sim/levels-v2/pitch82/physical-hybrid-hidden-v1/inputs/case.json'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def bits(value):
    if not math.isfinite(value): raise ValueError('nonfinite recorded coordinate')
    return hex(struct.unpack('<Q', struct.pack('<d', value))[0])


def main():
    files = [TRACE, CASE, MAP / 'safe.bin', MAP / 'observed.bin', MAP / 'observed-detail.bin', MAP / 'map.json',
             ARCHIVE / 'build.json', ARCHIVE / 'source/sim/navigation.flex', COMPILER, TRANSFORM]
    hashes = {str(p.relative_to(ROOT)): sha(p) for p in files}
    important = {}
    with TRACE.open() as stream:
        for line in stream:
            last = json.loads(line)
            if last['step'] in (10820, 10821, 10861, 10862, 31038):
                important[last['step']] = last
    last = important[31038]
    if (last['discovery']['mapFrameId'] != 31037 or last['case']['phase'] != 'observing docking floor' or
        not last['gripper']['held'] or last['discovery']['output'] != str(MAP.relative_to(ROOT))):
        raise ValueError('unexpected saved terminal checkpoint')
    if last['case']['navigation']['rememberedRgbObstacles'] != 0:
        raise ValueError('checkpoint contains unreconstructed remembered obstacles')
    contacts = []
    for before, after, expected in ((10820, 10821, 1), (10861, 10862, 2)):
        old, event = important[before], important[after]
        drive = old['controller']['drive']
        if (event['case']['navigation']['failedCommandConstraints'] != expected or
                old['case']['navigation']['failedCommandConstraints'] != expected - 1 or
                not event['blocked'] or drive['leftSpeed'] != drive['rightSpeed'] or
                drive['leftSpeed'] == 0):
            raise ValueError('failed-command trace does not match reconstruction')
        contacts.append({'pose': event['localization']['pose'],
                         'direction': 1 if drive['leftSpeed'] > 0 else -1,
                         'steeringDegrees': drive['steeringAngleDeg'] - 90})
    x,y,h = last['localization']['pose']; centre = last['case']['boxSearch']['centreM']
    box = last['case']['dockVision']['positionM']; yaw = last['case']['dockVision']['yawRad']
    definition=json.loads(CASE.read_text());container=definition.get('container',{});size=container.get('innerSize');wall=container.get('wallThickness')
    if not isinstance(size,list) or len(size)!=3 or any(not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0 for v in size) or not isinstance(wall,(int,float)) or not math.isfinite(wall) or wall<=0:
        raise ValueError('invalid recorded box dimensions')
    with tempfile.TemporaryDirectory(prefix='dock-waypoint-probe-') as d:
        tmp = Path(d); source = tmp / 'source'; build = tmp / 'build'
        shutil.copytree(ARCHIVE / 'source', source); shutil.copytree(ARCHIVE / 'build', build)
        lib = build / 'flex/sim/library'; adapter = lib / 'lib/f64.flex'; text = adapter.read_text()
        # Archive adapter points at its own archived source, not ours.
        original = f'import "{ARCHIVE / "source/core/words.flex"}";'
        if text.count(original) != 1:
            raise ValueError('unexpected archived source link')
        adapter.write_text(text.replace(original, f'import "{source / "core/words.flex"}";', 1))
        (lib.parent / 'dependencies.flex').write_text(f'import "{lib / "libs/render.flex"}";\nimport "{lib / "libs/physics/physics.flex"}";\n')
        sim = source / 'sim/main.flex'; text = sim.read_text()
        spec=importlib.util.spec_from_file_location('waypoint_transform',TRANSFORM)
        transform=importlib.util.module_from_spec(spec);spec.loader.exec_module(transform)
        dock=source/'sim/dock-search.flex';new_dock,text=transform.transform(dock.read_text(),text);dock.write_text(new_dock)
        if text.count('fn main(argc, argv) {') != 1: raise ValueError('unexpected simulator entrypoint')
        template = r'''
fn main(argc, argv) {
 if !pl_init() {return 1;}
 ps_local_mode=1;ps_local_x=X;ps_local_y=Y;ps_local_heading=H;ps_discovery_enabled=1;
 ps_collect_enabled=1;ps_collect_busy=1;ps_house_ready=1;ps_house_returning=1;ps_case_camera=2;
 if !ps_nav_init() {return 2;}ps_discovery_detail=alloc(1000000);ps_discovery_detail_ready=1;
 if pl_read_file(SAFE,ps_nav_map,40000)!=40000 || pl_read_file(OBS,ps_discovery_observed,40000)!=40000 || pl_read_file(DETAIL,ps_discovery_detail,1000000)!=1000000 {return 3;}
 ps_dock_frame=alloc(128);ps_case_bin=alloc(128);store64(ps_case_bin+24,WX);store64(ps_case_bin+32,WY);store64(ps_case_bin+48,WT);
 store64(ps_dock_frame,f64_cos(YAW));store64(ps_dock_frame+8,f64_sin(YAW));store64(ps_dock_frame+96,BX);store64(ps_dock_frame+104,BY);ps_dock_yaw=YAW;
 let bearing=f64_atan2(f64_sub(CY,ps_local_y),f64_sub(CX,ps_local_x));let b=alloc(32);let out=alloc(16384);pl_builder(b,out,16384);pl_char(b,91);
 let group=0;let n=0;while group<=1 {ps_nav_contact_count=0;ps_nav_contact_next=0;if group {CONTACTS}
 let dist=20;while dist<=40 {let off= -1;while off<=1 {
 let angle=f64_add(bearing,ps_number(off*35,100));let x=f64_add(ps_local_x,f64_mul(ps_number(dist,100),f64_cos(angle)));let y=f64_add(ps_local_y,f64_mul(ps_number(dist,100),f64_sin(angle)));
 let clear=ps_nav_clear(x,y,ps_local_heading);let plan=0;if clear {plan=ps_nav_plan(x,y,ps_local_heading);}
 let end=alloc(24);if plan {ps_nav_end_pose(end);}
 if n {pl_char(b,44);}pl_text(b,"{\"reconstructedContacts\":");pj_bool_text(b,group);pl_text(b,",\"distanceCm\":");pl_int(b,dist);pl_text(b,",\"offsetIndex\":");pl_int(b,off);pl_text(b,",\"goal\":[");pl_float(b,x);pl_char(b,44);pl_float(b,y);pl_text(b,"],\"goalClear\":");pj_bool_text(b,clear);pl_text(b,",\"planned\":");pj_bool_text(b,plan);pl_text(b,",\"pathCount\":");if plan {pl_int(b,ps_nav_path_count);}else {pl_int(b,0);}pl_text(b,",\"endpoint\":");if plan {pl_char(b,91);pl_float(b,load64(end));pl_char(b,44);pl_float(b,load64(end+8));pl_char(b,44);pl_float(b,load64(end+16));pl_char(b,93);}else {pl_text(b,"null");}pl_char(b,125);n=n+1;off=off+1;}dist=dist+10;}group=group+1;}
 ps_dock_search_anchor=alloc(32);ps_dock_search_goal=alloc(24);store64(ps_dock_search_anchor,CX);store64(ps_dock_search_anchor+8,CY);
 let result=ps_dock_waypoint_plan();if n {pl_char(b,44);}pl_text(b,"{\"candidate\":true,\"result\":");pl_int(b,result);pl_text(b,",\"attemptedPlans\":");pl_int(b,ps_dock_waypoint_plans);pl_text(b,",\"pathCount\":");pl_int(b,ps_nav_path_count);pl_text(b,",\"goal\":[");pl_float(b,load64(ps_dock_search_goal));pl_char(b,44);pl_float(b,load64(ps_dock_search_goal+8));pl_char(b,93);pl_char(b,125);
 pl_char(b,93);pl_print(1,out);return 0;
}
'''
        import re
        contact_code = []
        for i, contact in enumerate(contacts):
            p = contact['pose']; angle = contact['steeringDegrees']
            contact_code.append(f'let r{i}=ps_nav_contacts+{i * 40};store64(r{i},{bits(p[0])});store64(r{i}+8,{bits(p[1])});store64(r{i}+16,{bits(p[2])});store64(r{i}+24,{contact["direction"]});')
            contact_code.append(f'let a{i}=pb_radians(f64_from_i64({angle}));store64(r{i}+32,pb_neg(f64_div(f64_sin(a{i}),f64_mul(ps_number(18,100),f64_cos(a{i})))));')
        contact_code.append('ps_nav_contact_count=2;ps_nav_contact_next=2;')
        replace = {'X':bits(x),'Y':bits(y),'H':bits(h),'CX':bits(centre[0]),'CY':bits(centre[1]),
                   'BX':bits(box[0]),'BY':bits(box[1]),'YAW':bits(yaw),
                   'WX':bits(size[0]),'WY':bits(size[1]),'WT':bits(wall),
                   'SAFE':json.dumps(str(MAP/'safe.bin')),'OBS':json.dumps(str(MAP/'observed.bin')),
                   'DETAIL':json.dumps(str(MAP/'observed-detail.bin')), 'CONTACTS':''.join(contact_code)}
        for name,val in replace.items(): template=re.sub(r'\b'+name+r'\b',lambda _:val,template)
        sim.write_text(text.replace('fn main(argc, argv) {','fn waypoint_previous_main(argc, argv) {',1)+'\n'+template)
        binary=tmp/'probe';subprocess.run([str(COMPILER),str(sim),'-o',str(binary)],cwd=ROOT,check=True,capture_output=True,text=True,timeout=120)
        out=subprocess.run([str(binary)],cwd=ROOT,check=True,capture_output=True,text=True,timeout=90)
        rows=json.loads(out.stdout)
    if hashes != {str(p.relative_to(ROOT)): sha(p) for p in files}: raise ValueError('input changed')
    print(json.dumps({'scope':'one saved post-waypoint map and pose; failed-command constraints reconstructed from adjacent saved trace rows, exact in-memory insertion timing unproven; not clearance or a driven route',
                      'pose':[x,y,h], 'cachedSearchCentre':centre, 'rememberedBox':box,'reconstructedContacts':contacts,'mapFrameId':json.loads((MAP/'map.json').read_text())['frameId'],
                      'sourceHashes':hashes,'rows':rows},indent=2))


if __name__ == '__main__': main()
