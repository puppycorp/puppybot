#!/usr/bin/env python3
"""Strict source transform for an isolated, simulator-only steering probe.

Both arms use the same instrumented binary. This module never edits the
worktree; generated sources and binaries must live in a fresh isolated build.
"""
from pathlib import Path

GLOBALS = '''global vw_steer_probe=0;
global vx_probe_trigger=0;
global vx_probe_cancelled=0;
global vx_probe_fd=-1;
global vx_probe_proposed=0;
global vx_probe_feedback=0;
global vx_probe_image_hash=0;
global vx_probe_hidden_hash=0;
'''

HOOKS = r'''// Diagnostic only: records policy inputs and actual applied actions. The
// existing carry cue is simulator task state, not a physical sensor.
fn vx_probe_begin(directory) {
    vx_probe_trigger=0;vx_probe_cancelled=0;vx_probe_proposed=alloc(8);vx_probe_feedback=alloc(28);
    vx_probe_fd=syscall(2,vc_path(directory,"steer-probe.jsonl"),0x800c1,384,0,0,0);
    vc_require(vx_probe_fd>=0,"cannot create steer probe journal");return 0;
}
fn vx_probe_capture(hidden) {
    vc_copy(vx_probe_feedback,ve_feedback,28);
    vx_probe_image_hash=vc_digest(ve_image,ve_image_bytes);
    vx_probe_hidden_hash=vc_digest(hidden,ve_memory_width*4);return 0;
}
fn vx_probe_apply(action) {
    vc_copy(vx_probe_proposed,action,8);
    if vx_carrying {vx_probe_cancelled=1;}
    if !ve_steps && !vx_carrying && f64_le(pb_read_float(action),vc_number(-1,2)) && f64_le(pb_read_float(action+4),vc_number(-8,10)) {vx_probe_trigger=1;}
    if vw_steer_probe==2 && vx_probe_trigger && !vx_probe_cancelled && ve_steps<3 && f64_gt(f64_magnitude(pb_read_float(action)),vc_number(0,1)) {
        pb_put32(action,pb_u32(action)^0x80000000);
    }return 0;
}
fn vx_probe_emit(action,hidden) {
    let text=alloc(4096);let b=alloc(32);pl_builder(b,text,4096);
    pl_text(b,"{\"step\":");pl_int(b,ve_steps);pl_text(b,",\"mode\":");pl_int(b,vw_steer_probe);
    pl_text(b,",\"trigger\":");pj_bool_text(b,vx_probe_trigger);pl_text(b,",\"cancelled\":");pj_bool_text(b,vx_probe_cancelled);
    pl_text(b,",\"proposed\":[");pl_int(b,pb_u32(vx_probe_proposed));pl_char(b,44);pl_int(b,pb_u32(vx_probe_proposed+4));
    pl_text(b,"],\"applied\":[");pl_int(b,pb_u32(action));pl_char(b,44);pl_int(b,pb_u32(action+4));
    pl_text(b,"],\"feedback\":[");let i=0;while i<7 {if i {pl_char(b,44);}pl_int(b,pb_u32(vx_probe_feedback+i*4));i=i+1;}
    pl_text(b,"],\"previousApplied\":[");pl_int(b,pb_u32(ve_previous));pl_char(b,44);pl_int(b,pb_u32(ve_previous+4));
    pl_text(b,"],\"command1000\":[");pl_int(b,ve_steering);pl_char(b,44);pl_int(b,ve_speed);
    let drive=pj_get(pj_get(ve_state,"controller"),"drive");pl_text(b,"],\"echo\":[");
    pl_int(b,vc_json_int(drive,"leftSpeed",0));pl_char(b,44);pl_int(b,vc_json_int(drive,"rightSpeed",0));pl_char(b,44);pl_int(b,vc_json_int(drive,"steeringAngleDeg",0));
    pl_text(b,"],\"imageSHA256\":");pj_text(b,vx_probe_image_hash);pl_text(b,",\"hiddenBeforeSHA256\":");pj_text(b,vx_probe_hidden_hash);
    let after=vc_digest(hidden,ve_memory_width*4);pl_text(b,",\"hiddenAfterSHA256\":");pj_text(b,after);pl_text(b,"}\n");
    vc_require(!load64(b+24) && !pl_write(vx_probe_fd,text,load64(b+8)),"cannot write steer probe journal");
    syscall(11,after,65,0,0,0,0);syscall(11,vx_probe_image_hash,65,0,0,0,0);syscall(11,vx_probe_hidden_hash,65,0,0,0,0);
    syscall(11,b,32,0,0,0,0);syscall(11,text,4096,0,0,0,0);return 0;
}
fn vx_probe_end() {
    vc_require(!syscall(3,vx_probe_fd,0,0,0,0,0),"cannot close steer probe journal");vx_probe_fd=-1;
    syscall(11,vx_probe_proposed,8,0,0,0,0);syscall(11,vx_probe_feedback,28,0,0,0,0);return 0;
}
'''


def replace_one(source, old, new):
    if source.count(old) != 1: raise ValueError('unexpected source shape; refusing transformation')
    return source.replace(old, new, 1)


def transform(chase, main):
    if 'vw_steer_probe' in chase or '--steer-probe-control' in main or '--steer-probe-enabled' in main:
        raise ValueError('source already contains steering probe')
    chase = replace_one(chase, 'global vw_chase=0;', GLOBALS + 'global vw_chase=0;')
    chase = replace_one(chase, 'fn vx_episode(directory,scene,seed,mode,base,hidden) {', HOOKS + '\nfn vx_episode(directory,scene,seed,mode,base,hidden) {')
    chase = replace_one(chase, '    while ve_steps<vw_horizon {\n        if vw_fetch {let cue=0;',
                        '    if vw_steer_probe {vx_probe_begin(directory);}\n    while ve_steps<vw_horizon {\n        if vw_fetch {let cue=0;')
    # The capture point follows carry-cue construction and precedes policy I/O.
    capture = '        if (mode==0 || mode==3) && vw_fetch {vx_fetch_teacher(label);'
    chase = replace_one(chase, capture, '        if vw_steer_probe {vx_probe_capture(hidden);}\n' + capture)
    chase = replace_one(chase, '        if vw_action_noise {store8(vx_noise_marks+ve_steps,vx_noise(action));}',
                        '        if vw_steer_probe {vx_probe_apply(action);}\n        if vw_action_noise {store8(vx_noise_marks+ve_steps,vx_noise(action));}')
    chase = replace_one(chase, 'if ve_contact {vx_contacts=vx_contacts+1;}vx_track(action);ve_step(action);',
                        'if ve_contact {vx_contacts=vx_contacts+1;}vx_track(action);ve_step(action);if vw_steer_probe {vx_probe_emit(action,hidden);}')
    chase = replace_one(chase, '    syscall(3,vx_log,0,0,0,0,0);if vw_record_memory',
                        '    if vw_steer_probe {vx_probe_end();}\n    syscall(3,vx_log,0,0,0,0,0);if vw_record_memory')
    main = replace_one(main, '        else if pl_equal(flag,"--fetch") {',
                       '        else if pl_equal(flag,"--steer-probe-control") {vc_require(!vw_steer_probe,"duplicate steer probe");vw_steer_probe=1;}\n'
                       '        else if pl_equal(flag,"--steer-probe-enabled") {vc_require(!vw_steer_probe,"duplicate steer probe");vw_steer_probe=2;}\n'
                       '        else if pl_equal(flag,"--fetch") {')
    guard = '    vc_require(!vw_steer_probe || (pl_equal(command,"run") && vw_fetch && vw_policy && vw_level==5 && vw_horizon==300 && vw_episodes==1 && ve_wheel_odometry && ve_camera_pitch==82 && ve_image_side==84 && ve_memory_width==128 && !vw_blackout && !vw_hide_carry && !vw_search_cue && !vw_far_bricks && !vw_explore && !vw_straight_bias && !vw_action_noise && !vw_sample_actions && !vw_ensemble_count && !vw_chase_forward && !vw_record_memory && !ve_policy_raw),"steer probe requires the fixed simulator-only policy configuration");\n'
    main = replace_one(main, '    vc_require(!vw_level || (vw_fetch', guard + '    vc_require(!vw_level || (vw_fetch')
    return chase, main
