// Shared exact replay checks for offline coverage-teacher diagnostics.
import "../../../flex/control/correction.flex";
import "../../../flex/control/verify.flex";
import "../../../flex/control/actions.flex";

global cr_compare=0;
global cr_base=0;
global cr_length=0;
fn cr_load(data_path,episode) {
    let data=vd_map(data_path);let bytes=vc_size;vc_require(bytes>=32 && vd_row_bytes(data)==56,"invalid packed demonstration data");let episodes=load64(data+8);cr_length=load64(data+24);
    vc_require(episodes>=2 && episodes<=vd_episode_limit(data) && cr_length>=1 && cr_length<=512 && bytes==32+episodes*cr_length*21224,"invalid packed demonstration dimensions");
    vc_require(episode>=0 && episode<episodes,"invalid packed episode");cr_base=data+32+episode*cr_length*21224;return 0;
}
fn cr_open(binary,scene,run,output) {
    cr_compare=ffi_symbol(ffi_open("libc.so.6"),"memcmp");vc_require(cr_compare,"memcmp unavailable");ve_open_buffers();ve_teacher_oracle=1;vw_coverage_teacher=1;
    ve_open(binary,output,scene,0,1,0);vw_correction_reset();va_lines(vc_path(run,"decisions.jsonl"));return 0;
}
fn cr_row(time) {return cr_base+cr_length*21168+time*56;}
fn cr_check_observation(run,time) {
    let step=vc_json_int(ve_state,"totalSteps",0);let stem=vc_concat("actor-",vc_int(step));
    let image=vc_map(vc_path(run,vc_concat(stem,".rgb")));vc_require(vc_size==21168 && !ffi_call(cr_compare,image,ve_image,21168,0,0,0),"replayed camera input differs from recording");syscall(11,image,21168,0,0,0,0);
    let feedback=vc_map(vc_path(run,vc_concat(stem,".feedback")));vc_require(vc_size==28 && !ffi_call(cr_compare,feedback,ve_feedback,28,0,0,0),"replayed feedback differs from recording");syscall(11,feedback,28,0,0,0,0);
    let row=cr_row(time);vc_require(pb_u32(row+44)==0x3f800000 && !ffi_call(cr_compare,cr_base+time*21168,ve_image,21168,0,0,0) && !ffi_call(cr_compare,row,ve_feedback,28,0,0,0),"replayed observation differs from packed training data");
    let phase=0;if ve_found {phase=0x3f800000;}vc_require(pb_u32(row+36)==phase,"replayed task phase differs from packed training data");return 0;
}
fn cr_replay_action(time,executed) {
    let record=va_next();vc_require(record,"recording ended before requested decision");let step=vc_json_int(record,"step",0);let hash=vc_string(pj_string_field(record,"actorSHA256"));let values=pj_get(record,"action");vc_require(pj_kind(values)==3 && pj_count(values)==2,"invalid recorded action");
    let k=0;while k<2 {let value=pj_real_node(pj_index(values,k));vc_require(!pj_error && f64_is_finite(value) && f64_le(f64_magnitude(value),PB_ONE),"invalid recorded action value");pb_put32(executed+k*4,pb_f64_to_f32(value));k=k+1;}
    let packed=cr_row(time);vc_require(pb_u32(packed+48)==pb_u32(executed) && pb_u32(packed+52)==pb_u32(executed+4),"recorded action differs from packed executed command");
    ve_step(executed);vc_require(ve_last_step==step && pl_equal(vc_digest(ve_image,21168),hash),"replayed action or resulting camera differs from recording");return 0;
}
