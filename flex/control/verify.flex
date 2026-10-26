// Independent recorded-run checks: decode actual sensor PNGs, reproduce the
// actor boundary, replay recurrent commands and check every physical base tick.
import "environment.flex";
global va_data=0;
global va_length=0;
global va_at=0;
global va_line=0;
global va_png_begin=0;
global va_png_finish=0;
global va_png_free=0;
global va_commands=0;
global va_consumption_count=0;
fn va_lines(path) {va_data=vc_map(path);va_length=vc_size;va_at=0;if !va_line {va_line=alloc(65537);}return 0;}
fn va_next() {
    if va_at==va_length {return 0;}let start=va_at;while va_at<va_length && load8(va_data+va_at)!=10 {va_at=va_at+1;}let n=va_at-start;if va_at<va_length {va_at=va_at+1;}
    vc_require(n>0 && n<=65536,"recorded JSON line exceeds limit");vc_copy(va_line,va_data+start,n);store8(va_line+n,0);let root=pj_parse(va_line,n);vc_require(root,pj_message);return root;
}
fn va_vector(array,out,n) {vc_require(pj_kind(array)==3 && pj_count(array)==n,"recorded vector has wrong dimensions");let i=0;while i<n {store64(out+i*8,pj_real_node(pj_index(array,i)));i=i+1;}vc_require(!pj_error,"invalid recorded vector");return out;}
fn va_body(values,pose) {
    let c=f64_cos(load64(pose+16));let s=f64_sin(load64(pose+16));let i=0;
    while i<4 {let x=load64(values+i*24);let y=load64(values+i*24+8);if !i {x=f64_sub(x,load64(pose));y=f64_sub(y,load64(pose+8));}
        store64(values+i*24,f64_add(f64_mul(c,x),f64_mul(s,y)));store64(values+i*24+8,f64_sub(f64_mul(c,y),f64_mul(s,x)));i=i+1;}return 0;
}
fn va_metadata(path,state,frame) {
    let actual=alloc(96);let estimated=alloc(96);let pose=alloc(24);let local=alloc(24);ve_pose_read(state,pose);
    va_vector(pj_get(pj_get(state,"localization"),"pose"),local,3);va_vector(pj_get(pj_get(pj_get(state,"case"),"perception"),"calibration"),estimated,12);va_body(estimated,local);
    let old=pj_arena;let used=pj_used;pj_arena=alloc(131072);let meta=vc_json_file(path);vc_require(vc_json_int(meta,"frameId",0)==frame && pl_equal(pj_string_field(meta,"view"),"tcp"),"sensor calibration/frame mismatch");
    va_vector(pj_get(meta,"eyeM"),actual,3);va_vector(pj_get(meta,"forward"),actual+24,3);va_vector(pj_get(meta,"right"),actual+48,3);va_vector(pj_get(meta,"down"),actual+72,3);va_body(actual,pose);
    let i=0;while i<4 {let norm=0;let j=0;while j<3 {let d=f64_sub(load64(actual+i*24+j*8),load64(estimated+i*24+j*8));norm=f64_add(norm,f64_mul(d,d));j=j+1;}
        let limit=vc_number(3,100000);if !i {limit=vc_number(3,1000);}vc_require(f64_lt(f64_sqrt(norm),limit),"rendered and estimated body camera frames differ");i=i+1;}
    syscall(11,pj_arena,131072,0,0,0,0);pj_arena=old;pj_used=used;pj_error=0;return 0;
}
fn va_png(path,out) {
    if !va_png_begin {let library=ffi_open("libpng16.so.16");vc_require(library,"native PNG decoder is unavailable");va_png_begin=ffi_symbol(library,"png_image_begin_read_from_file");va_png_finish=ffi_symbol(library,"png_image_finish_read");va_png_free=ffi_symbol(library,"png_image_free");vc_require(va_png_begin && va_png_finish && va_png_free,"native PNG simplified API is unavailable");}
    let image=alloc(104);pb_put32(image+8,1);vc_require(ffi_call(va_png_begin,image,path,0,0,0,0),"cannot decode sensor PNG");vc_require(pb_u32(image+12)==640 && pb_u32(image+16)==480,"sensor PNG has wrong dimensions");
    pb_put32(image+20,2);vc_require(ffi_call(va_png_finish,image,0,out,0,0,0),"cannot read native sensor pixels");ffi_call(va_png_free,image,0,0,0,0,0);syscall(11,image,104,0,0,0,0);return 0;
}
fn va_observation(directory,state,feedback_expected,actor_expected,rgb_expected) {
    let frame=vc_json_int(state,"totalSteps",0);let stem=vc_concat("actor-",vc_int(frame));let image=vc_map(vc_path(directory,vc_concat(stem,".rgb")));vc_require(vc_size==21168,"saved actor image has wrong dimensions");
    if actor_expected {vc_require(pl_equal(vc_digest(image,21168),actor_expected),"saved actor pixels differ from journal");}vc_copy(ve_image,image,21168);syscall(11,image,21168,0,0,0,0);
    let own=vc_map(vc_path(directory,vc_concat(stem,".feedback")));vc_require(vc_size==28,"saved own-state vector has wrong dimensions");let i=0;
    while i<28 {vc_require(load8(own+i)==load8(feedback_expected+i),"saved actor feedback differs from actual commands/contact");i=i+1;}vc_copy(ve_feedback,own,28);syscall(11,own,28,0,0,0,0);
    let png=vc_path(vc_path(directory,"sensor"),vc_concat(vc_concat("frame-",vc_int(frame)),".png"));va_png(png,ve_rgb);if rgb_expected {vc_require(pl_equal(vc_digest(ve_rgb,921600),rgb_expected),"native sensor pixels differ from transported RGB");}
    let resized=alloc(21168);vc_resize(ve_rgb,resized);i=0;while i<21168 {vc_require(load8(resized+i)==load8(ve_image+i),"saved actor pixels do not reproduce sensor area resize");i=i+1;}
    va_metadata(vc_concat(png,".camera.json"),state,frame);syscall(11,resized,21168,0,0,0,0);return 0;
}
fn va_command_intervals(directory) {
    va_commands=alloc(32768*8);va_lines(vc_path(directory,"decisions.jsonl"));let row=va_next();
    while row {let step=vc_json_int(row,"step",0);vc_require(step>=10 && step<32768,"recorded action step is outside audit bounds");let action=pj_get(row,"action");
        let steering=f64_to_i64_nearest(f64_mul(pj_real_node(pj_index(action,0)),f64_from_i64(1000)));let speed=f64_to_i64_nearest(f64_mul(pj_real_node(pj_index(action,1)),f64_from_i64(1000)));
        let throttle=speed*60/1000;if pb_abs(speed)<80 {throttle=0;}let command=alloc(40);store64(command,throttle);store64(command+8,90+(steering/10)*45/100);store64(command+16,f64_eq(pj_real_node(pj_index(pj_get(row,"proprio"),5)),PB_ONE));store64(command+32,step);
        let tick=step-9;while tick<=step {vc_require(!load64(va_commands+tick*8),"overlapping recorded actions");store64(va_commands+tick*8,command);tick=tick+1;}row=va_next();
    }syscall(11,va_data,va_length,0,0,0,0);return 0;
}
fn va_consumption(directory,state,target) {
    let event=pj_get(state,"findReturn");let step=vc_json_int(event,"detectionStep",0);let pixel=pj_get(event,"detectionPixelBox");let bounds=alloc(32);va_vector(pixel,bounds,4);
    let old=pj_arena;let used=pj_used;pj_arena=alloc(131072);let path=vc_path(vc_path(directory,"sensor"),vc_concat(vc_concat("frame-",vc_int(step)),".png.camera.json"));let meta=vc_json_file(path);
    vc_require(vc_json_int(meta,"frameId",0)==step,"brick consumption frame is stale");let eye=alloc(24);let forward=alloc(24);let right=alloc(24);let down=alloc(24);
    va_vector(pj_get(meta,"eyeM"),eye,3);va_vector(pj_get(meta,"forward"),forward,3);va_vector(pj_get(meta,"right"),right,3);va_vector(pj_get(meta,"down"),down,3);
    let depth=0;let horizontal=0;let vertical=0;let i=0;while i<3 {let d=f64_sub(load64(target+i*8),load64(eye+i*8));depth=f64_add(depth,f64_mul(d,load64(forward+i*8)));horizontal=f64_add(horizontal,f64_mul(d,load64(right+i*8)));vertical=f64_add(vertical,f64_mul(d,load64(down+i*8)));i=i+1;}
    vc_require(f64_gt(depth,0),"consumed brick is behind the sensor");let intrinsics=pj_get(meta,"intrinsics");let x=f64_add(pj_real(intrinsics,"cx"),f64_mul(pj_real(intrinsics,"fx"),f64_div(horizontal,depth)));let y=f64_add(pj_real(intrinsics,"cy"),f64_mul(pj_real(intrinsics,"fy"),f64_div(vertical,depth)));let margin=f64_from_i64(12);
    vc_require(f64_ge(x,f64_sub(load64(bounds),margin)) && f64_le(x,f64_add(load64(bounds+16),margin)) && f64_ge(y,f64_sub(load64(bounds+8),margin)) && f64_le(y,f64_add(load64(bounds+24),margin)),"RGB consumption bbox does not contain the actual brick projection");
    syscall(11,pj_arena,131072,0,0,0,0);pj_arena=old;pj_used=used;pj_error=0;va_consumption_count=va_consumption_count+1;return 0;
}
fn va_return(state) {
    if !pj_boolean(pj_get(state,"case"),"passed") {return 0;}let pose=alloc(24);ve_pose_read(state,pose);let position=pj_get(pj_get(pj_get(state,"case"),"container"),"position");
    let dx=f64_sub(pj_real_node(pj_index(position,0)),load64(pose));let dy=f64_sub(pj_real_node(pj_index(position,1)),load64(pose+8));let range=f64_hypot(dx,dy);let error=f64_magnitude(pb_wrap_pi(f64_sub(f64_atan2(dy,dx),load64(pose+16))));
    vc_require(va_consumption_count==1 && f64_ge(range,vc_number(3,10)) && f64_le(range,vc_number(65,100)) && f64_le(error,pb_radians(f64_from_i64(35))) && vc_json_int(state,"findReturn","stableReturnObservations")>=3,"recorded return fails physical acceptance criteria");
    vc_require(vc_json_int(pj_get(state,"case"),"dockVision","frameId")==vc_json_int(state,"totalSteps",0),"recorded return camera frame is stale");return 0;
}
fn va_physics(directory) {
    va_lines(vc_path(directory,"trace.jsonl"));let previous=alloc(24);let pose=alloc(24);let step=-1;let checked=0;let state=va_next();
    while state {
        vc_require(!vc_json_int(state,"physicsFault",0) && !vc_json_int(pj_get(state,"vehicle"),"queryFault",0),"recorded physical fault");let gripper=pj_get(state,"gripper");vc_require(!pj_boolean(gripper,"held") && !vc_json_int(gripper,"grasps",0) && !vc_json_int(gripper,"releases",0),"recorded manipulation in driving task");
        let discovery=pj_get(state,"discovery");vc_require(!pj_boolean(discovery,"suppliedMap") && !pj_boolean(discovery,"worldPoseInput") && !vc_json_int(discovery,"scans",0) && !vc_json_int(discovery,"freeCells",0) && !vc_json_int(discovery,"occupiedCells",0),"recorded automatic mapping/scans");
        ve_pose_read(state,pose);let current=vc_json_int(state,"step",0);vc_require(current<32768,"physical trace exceeds audit bounds");let command=load64(va_commands+current*8);
        if command {let drive=pj_get(pj_get(state,"controller"),"drive");vc_require(vc_json_int(drive,"leftSpeed",0)==load64(command) && vc_json_int(drive,"rightSpeed",0)==load64(command) && vc_json_int(drive,"steeringAngleDeg",0)==load64(command+8),"physical interval commands differ from recorded actor action");
            if pj_boolean(state,"blocked") {store64(command+24,1);}if current==load64(command+32) {vc_require(load64(command+16)==load64(command+24),"actor contact feedback differs from physical collision trace");}}
        if step>=0 {
            vc_require(current==step+1,"physical trace skipped a tick");let drive=pj_get(pj_get(state,"controller"),"drive");let travel=vc_number(vc_json_int(drive,"leftSpeed",0)+vc_json_int(drive,"rightSpeed",0),20000);
            let radians=pb_radians(f64_from_i64(vc_json_int(drive,"steeringAngleDeg",0)-90));let heading=pb_wrap_pi(f64_sub(load64(previous+16),f64_mul(f64_div(travel,vc_number(18,100)),f64_div(f64_sin(radians),f64_cos(radians)))));
            let x=f64_add(load64(previous),f64_mul(travel,f64_cos(heading)));let y=f64_add(load64(previous+8),f64_mul(travel,f64_sin(heading)));
            if pj_boolean(state,"blocked") {x=load64(previous);y=load64(previous+8);heading=load64(previous+16);}
            vc_require(f64_lt(f64_hypot(f64_sub(x,load64(pose)),f64_sub(y,load64(pose+8))),vc_number(1,10000000)) && f64_lt(f64_magnitude(pb_wrap_pi(f64_sub(heading,load64(pose+16)))),vc_number(1,10000000)),"base movement differs from physical drive commands");checked=checked+1;
        }
        step=current;vc_copy(previous,pose,24);state=va_next();
    }syscall(11,va_data,va_length,0,0,0,0);return checked;
}
fn va_verify(directory,policy,output,blackout) {
    vc_mkdir(output);va_command_intervals(directory);let physical=va_physics(directory);let checksum=ve_policy_open(policy,output);ve_state=vc_json_file(vc_path(directory,"initial.json"));let initial_frame=vc_json_int(ve_state,"totalSteps",0);let target=alloc(24);va_vector(pj_get(pj_index(pj_get(pj_get(ve_state,"case"),"objects"),0),"position"),target,3);va_consumption_count=0;
    let initial=vc_map(vc_path(directory,vc_concat(vc_concat("actor-",vc_int(initial_frame)),".feedback")));vc_require(vc_size==28,"invalid initial feedback");vc_copy(ve_feedback,initial,28);syscall(11,initial,28,0,0,0,0);ve_check(1);va_observation(directory,ve_state,ve_feedback,0,0);
    let hidden=alloc(512);let expected=alloc(8);let feedback=alloc(28);let maximum=0;let commands=0;va_lines(vc_path(directory,"decisions.jsonl"));let row=va_next();
    while row {
        let action=pj_get(row,"action");pb_put32(expected,pb_f64_to_f32(pj_real_node(pj_index(action,0))));pb_put32(expected+4,pb_f64_to_f32(pj_real_node(pj_index(action,1))));
        let actual=ve_action(hidden,blackout);let error=pb_fmax(f64_magnitude(f64_sub(pb_read_float(actual),pb_read_float(expected))),f64_magnitude(f64_sub(pb_read_float(actual+4),pb_read_float(expected+4))));maximum=pb_fmax(maximum,error);vc_require(f64_lt(error,vc_number(1,100000)),"native recurrent command replay differs");
        ve_state=pj_get(row,"state");ve_contact=0;let own=pj_get(row,"proprio");if f64_eq(pj_real_node(pj_index(own,5)),PB_ONE) {ve_contact=1;}
        vc_copy(ve_previous,expected,8);vc_feedback(pj_get(pj_get(ve_state,"controller"),"drive"),ve_previous,ve_contact,feedback);
        let i=0;while i<7 {vc_require(pb_f64_to_f32(pj_real_node(pj_index(own,i)))==pb_u32(feedback+i*4),"journal actor feedback is not own-state feedback");i=i+1;}
        ve_steering=f64_to_i64_nearest(f64_mul(pb_read_float(expected),f64_from_i64(1000)));ve_speed=f64_to_i64_nearest(f64_mul(pb_read_float(expected+4),f64_from_i64(1000)));
        vc_copy(ve_feedback,feedback,28);ve_check(0);va_observation(directory,ve_state,feedback,pj_string_field(row,"actorSHA256"),pj_string_field(row,"rgbSHA256"));
        if vc_json_int(ve_state,"findReturn","consumedIndex")>=0 {if !va_consumption_count {va_consumption(directory,ve_state,target);}}else {va_vector(pj_get(pj_index(pj_get(pj_get(ve_state,"case"),"objects"),0),"position"),target,3);}
        va_return(ve_state);commands=commands+1;row=va_next();
    }
    vc_require(commands>=1,"recorded episode is empty");vc_finish(ve_policy,15000);let out=alloc(4096);let b=alloc(32);pl_builder(b,out,4096);
    pl_text(b,"{\"passed\":true,\"runtime\":\"Flexscript\",\"pythonRequired\":false,\"physicalMotionIncrements\":");pl_int(b,physical);pl_text(b,",\"modelCommandsReplayed\":");pl_int(b,commands);pl_text(b,",\"commandReplayMaxAbsError\":");pl_float(b,maximum);
    pl_text(b,",\"PNGAndActorFramesMatched\":");pl_int(b,commands+1);pl_text(b,",\"consumptionEventsProjected\":");pl_int(b,va_consumption_count);pl_text(b,",\"motorAndContactIntervalsChecked\":true,\"returnPoseChecked\":true,\"cameraCalibrationChecked\":true,\"taskEventHintAbsent\":true,\"blackout\":");pj_bool_text(b,blackout);pl_text(b,",\"weightsSHA256\":");pj_text(b,checksum);pl_text(b,"}\n");vc_write(vc_path(output,"result.json"),out,load64(b+8));pl_write(1,out,load64(b+8));return 0;
}
