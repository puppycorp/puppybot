#!/usr/bin/env python3
"""Strict isolated source transform; does not edit the workspace or run GPU."""
import importlib.util
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
KICK=ROOT/'experiments/l5-steering-kick-v1/transform.py'


def load(path):
    spec=importlib.util.spec_from_file_location('base_kick_transform',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


base=load(KICK)


GLOBALS='''global vw_steer_hysteresis=0;
global vx_hys_fd=-1;
global vx_hys_ring=0;
global vx_hys_pose=0;
global vx_hys_kick=0;
global vx_hys_count=0;
global vx_hys_head=0;
global vx_hys_used=0;
global vx_hys_disabled=0;
global vx_hys_remaining=0;
global vx_hys_before=0;
global vx_hys_sign=0;
global vx_hys_trigger=0;
global vx_hys_carry_before=0;
global vx_hys_contact_before=0;
'''


HOOKS=r'''// Simulator-only bounded experiment. Never use world pose or target data.
fn vx_hys_validate() {
    let loc=pj_get(ve_state,"localization");let pose=pj_get(loc,"pose");
    vc_require(pl_equal(pj_string_field(loc,"mode"),"wheel-drift") && pl_equal(pj_string_field(loc,"source"),"wheel-steering-command-integration") && pj_kind(pose)==3 && pj_count(pose)==3,"invalid local wheel odometry");
    let i=0;while i<3 {let x=pj_real_node(pj_index(pose,i));vc_require(!pj_error && f64_is_finite(x),"nonfinite local wheel odometry");store64(vx_hys_pose+i*8,x);i=i+1;}
    let total=vc_json_int(ve_state,"totalSteps",0);let step=vc_json_int(ve_state,"step",0);let camera=pj_get(ve_state,"camera");
    vc_require(!pj_error && total==step && step==ve_last_step && pl_equal(pj_string_field(camera,"pose"),"driving") && pj_boolean(camera,"armSettled") && vc_json_int(pj_get(ve_state,"case"),"perception","frameId")==total && (ve_contact==0 || ve_contact==1),"stale or invalid feedback");return 0;
}
fn vx_hys_begin(directory) {
    vx_hys_ring=alloc(256);pb_zero(vx_hys_ring,256);vx_hys_pose=alloc(24);vx_hys_kick=alloc(8);
    vx_hys_count=0;vx_hys_head=0;vx_hys_used=0;vx_hys_disabled=0;vx_hys_remaining=0;vx_hys_sign=0;vx_hys_trigger=0;
    vx_hys_fd=syscall(2,vc_path(directory,"hysteresis.jsonl"),0x800c1,384,0,0,0);vc_require(vx_hys_fd>=0,"cannot create hysteresis journal");return 0;
}
fn vx_hys_check() {
    vx_hys_validate();vx_hys_trigger=0;vx_hys_carry_before=vx_carrying;vx_hys_contact_before=ve_contact;
    if vx_carrying {vx_hys_disabled=1;vx_hys_remaining=0;}
    if ve_contact && vx_hys_remaining {vx_hys_disabled=1;vx_hys_remaining=0;}
    if !vx_hys_used && !vx_hys_disabled && !ve_contact && vx_probe_trigger && vx_hys_count==8 {
        let first=vx_hys_ring+vx_hys_head*32;let last=vx_hys_ring+((vx_hys_head+7)%8)*32;
        let flips=0;let prev=load64(first);let valid=prev!=0;let i=1;
        while i<8 {let sign=load64(vx_hys_ring+((vx_hys_head+i)%8)*32);if !sign {valid=0;}if sign*prev<0 {flips=flips+1;}prev=sign;i=i+1;}
        let dx=f64_sub(load64(last+8),load64(first+8));let dy=f64_sub(load64(last+16),load64(first+16));let distance=f64_hypot(dx,dy);
        let turn=f64_magnitude(pb_wrap_pi(f64_sub(load64(last+24),load64(first+24))));
        if valid && flips>=6 && f64_lt(distance,vc_number(15,100)) && f64_lt(turn,pb_radians(f64_from_i64(45))) {
            vx_hys_used=1;vx_hys_remaining=2;vx_hys_sign=load64(last);vx_hys_trigger=1;
        }
    }
    vx_hys_before=vx_hys_remaining;return 0;
}
fn vx_hys_apply(action) {
    vc_copy(vx_hys_kick,action,8);let steering=pb_read_float(action);let speed=pb_read_float(action+4);
    vc_require(f64_is_finite(steering) && f64_is_finite(speed) && f64_le(f64_magnitude(steering),PB_ONE) && f64_le(f64_magnitude(speed),PB_ONE),"invalid hysteresis action");
    if vx_hys_remaining {
        let bits=pb_u32(action+4);if bits&0x7fffffff {let sign=1;if bits&0x80000000 {sign=-1;}if sign!=vx_hys_sign {pb_put32(action+4,bits^0x80000000);}}
        vx_hys_remaining=vx_hys_remaining-1;
    }return 0;
}
fn vx_hys_observe(action) {
    vx_hys_validate();let bits=pb_u32(action+4);let sign=0;if bits&0x7fffffff {sign=1;if bits&0x80000000 {sign=-1;}}
    let record=vx_hys_ring+vx_hys_head*32;store64(record,sign);store64(record+8,load64(vx_hys_pose));store64(record+16,load64(vx_hys_pose+8));store64(record+24,load64(vx_hys_pose+16));
    vx_hys_head=(vx_hys_head+1)%8;if vx_hys_count<8 {vx_hys_count=vx_hys_count+1;}
    let text=alloc(2048);let b=alloc(32);pl_builder(b,text,2048);pl_text(b,"{\"step\":");pl_int(b,ve_steps);
    pl_text(b,",\"trigger\":");pj_bool_text(b,vx_hys_trigger);pl_text(b,",\"used\":");pj_bool_text(b,vx_hys_used);
    pl_text(b,",\"disabled\":");pj_bool_text(b,vx_hys_disabled);pl_text(b,",\"remainingBefore\":");pl_int(b,vx_hys_before);
    pl_text(b,",\"remainingAfter\":");pl_int(b,vx_hys_remaining);pl_text(b,",\"heldSign\":");pl_int(b,vx_hys_sign);
    pl_text(b,",\"carryBefore\":");pj_bool_text(b,vx_hys_carry_before);pl_text(b,",\"contactBefore\":");pj_bool_text(b,vx_hys_contact_before);
    pl_text(b,",\"kick\":[");pl_int(b,pb_u32(vx_hys_kick));pl_char(b,44);pl_int(b,pb_u32(vx_hys_kick+4));
    pl_text(b,"],\"applied\":[");pl_int(b,pb_u32(action));pl_char(b,44);pl_int(b,pb_u32(action+4));pl_text(b,"]}\n");
    vc_require(!load64(b+24) && !pl_write(vx_hys_fd,text,load64(b+8)),"cannot write hysteresis journal");syscall(11,b,32,0,0,0,0);syscall(11,text,2048,0,0,0,0);return 0;
}
fn vx_hys_end() {
    vc_require(!syscall(3,vx_hys_fd,0,0,0,0,0),"cannot close hysteresis journal");
    syscall(11,vx_hys_ring,256,0,0,0,0);syscall(11,vx_hys_pose,24,0,0,0,0);syscall(11,vx_hys_kick,8,0,0,0,0);return 0;
}
'''


def transform(chase,main):
    chase,main=base.transform(chase,main);once=base.replace_one
    chase=once(chase,'global vw_chase=0;',GLOBALS+'global vw_chase=0;')
    chase=once(chase,'fn vx_episode(directory,scene,seed,mode,base,hidden) {',HOOKS+'\nfn vx_episode(directory,scene,seed,mode,base,hidden) {')
    chase=once(chase,'    if vw_steer_probe {vx_probe_begin(directory);}', '    if vw_steer_probe {vx_probe_begin(directory);}if vw_steer_hysteresis {vx_hys_begin(directory);}')
    chase=once(chase,'        if vw_steer_probe {vx_probe_capture(hidden);}', '        if vw_steer_hysteresis {vx_hys_check();}\n        if vw_steer_probe {vx_probe_capture(hidden);}')
    chase=once(chase,'        if vw_steer_probe {vx_probe_apply(action);}', '        if vw_steer_probe {vx_probe_apply(action);}\n        if vw_steer_hysteresis {vx_hys_apply(action);}')
    chase=once(chase,'if vw_steer_probe {vx_probe_emit(action,hidden);}', 'if vw_steer_probe {vx_probe_emit(action,hidden);}if vw_steer_hysteresis {vx_hys_observe(action);}')
    chase=once(chase,'    if vw_steer_probe {vx_probe_end();}', '    if vw_steer_probe {vx_probe_end();}if vw_steer_hysteresis {vx_hys_end();}')
    main=once(main,'        else if pl_equal(flag,"--steer-probe-control")', '        else if pl_equal(flag,"--steer-hysteresis") {vc_require(!vw_steer_hysteresis,"duplicate hysteresis");vw_steer_hysteresis=1;}\n        else if pl_equal(flag,"--steer-probe-control")')
    main=once(main,'    vc_require(!vw_steer_probe || (pl_equal(command,"run")', '    vc_require(!vw_steer_hysteresis || vw_steer_probe==2,"hysteresis requires kick mode");\n    vc_require(!vw_steer_probe || (pl_equal(command,"run")')
    return chase,main
