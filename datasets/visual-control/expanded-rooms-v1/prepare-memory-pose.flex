// Create training-only initial-frame-relative pose labels from audited motion.
// No pose, map, or task phase is added to the actor's input.
import "../../../flex/control/verify.flex";
fn mp_pose_match(trace,step,total,pose) {
    vc_require(step>=0 && step<32768 && load64(trace+step*32+24)==total+1,"pose target has no matching physical trace frame");
    let saved=trace+step*32;let dx=f64_sub(load64(saved),load64(pose));let dy=f64_sub(load64(saved+8),load64(pose+8));let dh=pb_wrap_pi(f64_sub(load64(saved+16),load64(pose+16)));
    vc_require(f64_lt(f64_hypot(dx,dy),vc_number(1,10000000)) && f64_lt(f64_magnitude(dh),vc_number(1,10000000)),"pose target disagrees with physical trace");return 0;
}
fn mp_inverse_check(label,initial,pose) {
    let forward=f64_mul(pb_read_float(label),f64_from_i64(8));let sideways=f64_mul(pb_read_float(label+4),f64_from_i64(8));let c=f64_cos(load64(initial+16));let s=f64_sin(load64(initial+16));
    let x=f64_add(load64(initial),f64_sub(f64_mul(c,forward),f64_mul(s,sideways)));let y=f64_add(load64(initial+8),f64_add(f64_mul(s,forward),f64_mul(c,sideways)));
    let sine=pb_read_float(label+8);let cosine=pb_read_float(label+12);let heading=pb_wrap_pi(f64_add(load64(initial+16),f64_atan2(sine,cosine)));let tolerance=vc_number(1,100000);
    vc_require(f64_lt(f64_hypot(f64_sub(x,load64(pose)),f64_sub(y,load64(pose+8))),tolerance) && f64_lt(f64_magnitude(pb_wrap_pi(f64_sub(heading,load64(pose+16)))),tolerance) && f64_lt(f64_magnitude(f64_sub(f64_add(f64_mul(sine,sine),f64_mul(cosine,cosine)),PB_ONE)),tolerance),"pose target inverse transform differs from physical trace");return 0;
}
fn mp_write_target(target,initial,pose) {
    let dx=f64_sub(load64(pose),load64(initial));let dy=f64_sub(load64(pose+8),load64(initial+8));let angle=load64(initial+16);let c=f64_cos(angle);let s=f64_sin(angle);
    let forward=f64_div(f64_add(f64_mul(c,dx),f64_mul(s,dy)),f64_from_i64(8));let sideways=f64_div(f64_sub(f64_mul(c,dy),f64_mul(s,dx)),f64_from_i64(8));
    vc_require(f64_le(f64_magnitude(forward),PB_ONE) && f64_le(f64_magnitude(sideways),PB_ONE),"relative pose exceeds eight metre target range");
    let heading=pb_wrap_pi(f64_sub(load64(pose+16),angle));pb_put32(target,pb_f64_to_f32(forward));pb_put32(target+4,pb_f64_to_f32(sideways));pb_put32(target+8,pb_f64_to_f32(f64_sin(heading)));pb_put32(target+12,pb_f64_to_f32(f64_cos(heading)));pb_put32(target+16,0x3f800000);mp_inverse_check(target,initial,pose);return 0;
}
fn mp_trace(run) {
    va_command_intervals(run);let increments=va_physics(run);vc_require(increments>0,"pose target has no verified physical motion");
    let trace=alloc(32768*32);pb_zero(trace,32768*32);let pose=alloc(24);va_lines(vc_path(run,"trace.jsonl"));let state=va_next();
    while state {let step=vc_json_int(state,"step",0);let total=vc_json_int(state,"totalSteps",0);vc_require(step>=0 && step<32768 && total>=0 && !load64(trace+step*32+24),"duplicate or invalid physical trace frame");ve_pose_read(state,pose);vc_copy(trace+step*32,pose,24);store64(trace+step*32+24,total+1);state=va_next();}
    syscall(11,va_data,va_length,0,0,0,0);syscall(11,pose,24,0,0,0,0);return trace;
}
fn mp_progress(completed,total) {
    let text=alloc(128);let b=alloc(32);pl_builder(b,text,128);pl_text(b,"{\"verifiedEpisodes\":");pl_int(b,completed);pl_text(b,",\"totalEpisodes\":");pl_int(b,total);pl_text(b,"}\n");
    vc_require(!load64(b+24) && !pl_write(2,text,load64(b+8)),"cannot write memory-pose progress");syscall(11,text,128,0,0,0,0);syscall(11,b,32,0,0,0,0);return 0;
}
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==4,"prepare-memory-pose DATA MERGED_RUN NEW_OUTPUT");let path=vc_absolute(load64(argv+8));let root=vc_absolute(load64(argv+16));let output=vc_absolute(load64(argv+24));let data=vd_map(path);let bytes=vc_size;let row_bytes=vd_row_bytes(data);
    vc_require(bytes>=32 && row_bytes,"invalid pose dataset");let n=load64(data+8);let fit=load64(data+16);let length=load64(data+24);vc_require(n>=2 && n<=vd_episode_limit(data) && fit>=1 && fit<n && length>=1 && length<=512 && bytes==32+n*length*(21168+row_bytes),"invalid pose dataset dimensions");
    let data_sha=vc_digest(data,bytes);let size=32+n*length*20;let targets=alloc(size);pb_zero(targets,size);vc_copy(targets,"PVPOSE01",8);store64(targets+8,n);store64(targets+16,fit);store64(targets+24,length);
    let sources=alloc(524288);let builder=alloc(32);pl_builder(builder,sources,524288);pl_text(builder,"{\"sources\":[");let compare=ffi_symbol(ffi_open("libc.so.6"),"memcmp");vc_require(compare,"memcmp unavailable");let episode=0;
    while episode<n {let run=vc_path(root,vc_concat("expert-",vc_int(episode)));let initial_path=vc_path(run,"initial.json");let decisions_path=vc_path(run,"decisions.jsonl");let trace_path=vc_path(run,"trace.jsonl");
        let initial_sha=vc_file_sha(initial_path);let decisions_sha=vc_file_sha(decisions_path);let trace_sha=vc_file_sha(trace_path);let trace=mp_trace(run);let state=vc_json_file(initial_path);let initial=alloc(24);let pose=alloc(24);ve_pose_read(state,initial);vc_copy(pose,initial,24);let step=vc_json_int(state,"step",0);let total=vc_json_int(state,"totalSteps",0);mp_pose_match(trace,step,total,pose);
        let base=data+32+episode*length*(21168+row_bytes);let t=0;va_lines(decisions_path);let row=va_next();
        while row {vc_require(t<length,"pose source exceeds dataset horizon");let values=base+length*21168+t*row_bytes;vc_require(vd_valid_word(values,row_bytes)==0x3f800000 && !pb_u32(values+24),"pose source includes a padded frame or task-event hint");
            let stem=vc_concat("actor-",vc_int(total));let rgb=vc_map(vc_path(run,vc_concat(stem,".rgb")));vc_require(vc_size==21168 && !ffi_call(compare,rgb,base+t*21168,21168,0,0,0),"pose source RGB is not aligned to the dataset");syscall(11,rgb,21168,0,0,0,0);
            let own=vc_map(vc_path(run,vc_concat(stem,".feedback")));vc_require(vc_size==28 && !ffi_call(compare,own,values,28,0,0,0),"pose source feedback is not aligned to the dataset");syscall(11,own,28,0,0,0,0);
            mp_write_target(targets+32+(episode*length+t)*20,initial,pose);let action=pj_get(row,"action");let executed=values+28;if row_bytes==56 {executed=values+48;}
            vc_require(pj_kind(action)==3 && pj_count(action)==2 && pb_u32(executed)==pb_f64_to_f32(pj_real_node(pj_index(action,0))) && pb_u32(executed+4)==pb_f64_to_f32(pj_real_node(pj_index(action,1))),"pose source action differs from dataset");
            state=pj_get(row,"state");step=vc_json_int(state,"step",0);let next_total=vc_json_int(state,"totalSteps",0);vc_require(next_total==total+10 && vc_json_int(row,"step",0)==step,"pose source action and state steps differ");total=next_total;ve_pose_read(state,pose);mp_pose_match(trace,step,total,pose);
            t=t+1;row=va_next();
        }vc_require(t>=1,"pose source episode is empty");while t<length {let values=base+length*21168+t*row_bytes;vc_require(!vd_valid_word(values,row_bytes),"pose dataset contains a valid frame after its recording");t=t+1;}
        syscall(11,va_data,va_length,0,0,0,0);vc_require(pl_equal(initial_sha,vc_file_sha(initial_path)) && pl_equal(decisions_sha,vc_file_sha(decisions_path)) && pl_equal(trace_sha,vc_file_sha(trace_path)),"pose source changed during validation");
        if episode {pl_char(builder,44);}pl_text(builder,"{\"episode\":");pl_int(builder,episode);pl_text(builder,",\"initialSHA256\":");pj_text(builder,initial_sha);pl_text(builder,",\"decisionsSHA256\":");pj_text(builder,decisions_sha);pl_text(builder,",\"traceSHA256\":");pj_text(builder,trace_sha);pl_char(builder,125);
        syscall(11,trace,32768*32,0,0,0,0);syscall(11,initial,24,0,0,0,0);syscall(11,pose,24,0,0,0,0);episode=episode+1;mp_progress(episode,n);
    }pl_text(builder,"]}\n");vc_require(!load64(builder+24),"pose source manifest exceeds limit");vc_require(pl_equal(data_sha,vc_digest(data,bytes)),"pose dataset changed during validation");
    vc_mkdir(output);let target_sha=vc_digest(targets,size);vc_write(vc_path(output,"targets.bin"),targets,size);vc_write(vc_path(output,"sources.json"),sources,load64(builder+8));
    let text=alloc(2048);let b=alloc(32);pl_builder(b,text,2048);pl_text(b,"{\"passed\":true,\"runtime\":\"Flexscript\",\"pythonRequired\":false,\"verifiedAgainstPhysicalTrace\":true,\"sourceFilesStableDuringVerification\":true,\"actorInputsUnchanged\":true,\"preActionRGBAndFeedbackMatched\":true,\"inverseTransformChecked\":true,\"normalizationMetres\":8,\"episodes\":");pl_int(b,n);pl_text(b,",\"fittingHistories\":");pl_int(b,fit);pl_text(b,",\"validationHistories\":");pl_int(b,n-fit);pl_text(b,",\"sequenceLength\":");pl_int(b,length);pl_text(b,",\"sourceDataSHA256\":");pj_text(b,data_sha);pl_text(b,",\"targetsSHA256\":");pj_text(b,target_sha);pl_text(b,",\"sourcesSHA256\":");pj_text(b,vc_digest(sources,load64(builder+8)));pl_text(b,"}\n");vc_require(!load64(b+24),"pose receipt exceeds capacity");vc_write(vc_path(output,"receipt.json"),text,load64(b+8));pl_write(1,text,load64(b+8));return 0;
}
