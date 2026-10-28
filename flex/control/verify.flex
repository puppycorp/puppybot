// Independent recorded-run checks: decode actual sensor PNGs, reproduce the
// actor boundary, replay recurrent commands and check every physical base tick.
import "environment.flex";
import "dataset.flex";
global va_data=0;
global va_length=0;
global va_at=0;
global va_line=0;
global va_png_begin=0;
global va_png_finish=0;
global va_png_free=0;
global va_commands=0;
global va_consumption_count=0;
global va_audit_start=0;
global va_audit_count=0;
global va_allow_incomplete=0;
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
    let frame=vc_json_int(state,"totalSteps",0);let stem=vc_concat("actor-",vc_int(frame));let image=vc_map(vc_path(directory,vc_concat(stem,".rgb")));vc_require(vc_size==ve_image_bytes,"saved actor image has wrong dimensions");
    if actor_expected {vc_require(pl_equal(vc_digest(image,ve_image_bytes),actor_expected),"saved actor pixels differ from journal");}vc_copy(ve_image,image,ve_image_bytes);syscall(11,image,ve_image_bytes,0,0,0,0);
    let own=vc_map(vc_path(directory,vc_concat(stem,".feedback")));vc_require(vc_size==28,"saved own-state vector has wrong dimensions");let i=0;
    while i<28 {vc_require(load8(own+i)==load8(feedback_expected+i),"saved actor feedback differs from actual commands/contact");i=i+1;}vc_copy(ve_feedback,own,28);syscall(11,own,28,0,0,0,0);
    let png=vc_path(vc_path(directory,"sensor"),vc_concat(vc_concat("frame-",vc_int(frame)),".png"));va_png(png,ve_rgb);if rgb_expected {vc_require(pl_equal(vc_digest(ve_rgb,921600),rgb_expected),"native sensor pixels differ from transported RGB");}
    let resized=alloc(ve_image_bytes);vc_resize_to(ve_rgb,resized,ve_image_side);i=0;while i<ve_image_bytes {vc_require(load8(resized+i)==load8(ve_image+i),"saved actor pixels do not reproduce sensor area resize");i=i+1;}
    va_metadata(vc_concat(png,".camera.json"),state,frame);syscall(11,resized,ve_image_bytes,0,0,0,0);return 0;
}
fn va_command_intervals(directory) {
    va_commands=alloc(32768*8);va_lines(vc_path(directory,"decisions.jsonl"));let row=va_next();
    while row {let step=vc_json_int(row,"step",0);vc_require(step>=10 && step<32768,"recorded action step is outside audit bounds");let action=pj_get(row,"action");
        let steering=f64_to_i64_nearest(f64_mul(pj_real_node(pj_index(action,0)),f64_from_i64(1000)));let speed=f64_to_i64_nearest(f64_mul(pj_real_node(pj_index(action,1)),f64_from_i64(1000)));
        let throttle=speed*60/1000;if pb_abs(speed)<80 {throttle=0;}let command=alloc(40);store64(command,throttle);store64(command+8,90+(steering/10)*45/100);store64(command+16,f64_eq(pj_real_node(pj_index(pj_get(row,"proprio"),5)),PB_ONE));store64(command+32,step);
        let tick=step-9;while tick<=step {vc_require(!load64(va_commands+tick*8),"overlapping recorded actions");store64(va_commands+tick*8,command);tick=tick+1;}row=va_next();
    }syscall(11,va_data,va_length,0,0,0,0);return 0;
}
fn va_brick_pixel(rgb) {
    let r=load8(rgb);let g=load8(rgb+1);let b=load8(rgb+2);if pb_max(r,pb_max(g,b))<45 {return 0;}
    return (r>g*2 && r>b*2) || (b*10>r*18 && b*10>g*17) || (r>b*3 && g>b*3 && g*10>r*7) || (g*10>r*18 && g*10>b*16) || (b>r && r*10>g*18 && b*10>g*22) || (r*10>g*18 && r>b*4 && g*10>r*4);
}
fn va_consumption(directory,state,target) {
    let event=pj_get(state,"findReturn");let step=vc_json_int(event,"detectionStep",0);let pixel=pj_get(event,"detectionPixelBox");let bounds=alloc(32);va_vector(pixel,bounds,4);
    vc_require(step==vc_json_int(state,"totalSteps",0),"consumption does not match the delivered current camera frame");
    let pose=alloc(24);ve_pose_read(state,pose);let dx=f64_sub(load64(target),load64(pose));let dy=f64_sub(load64(target+8),load64(pose+8));let range=f64_hypot(dx,dy);syscall(11,pose,24,0,0,0,0);
    vc_require(f64_le(range,vc_number(35,100)),"consumed brick is farther than 0.35 m from the robot base");
    let x0=f64_to_i64_trunc(load64(bounds));let y0=f64_to_i64_trunc(load64(bounds+8));let x1=f64_to_i64_trunc(load64(bounds+16));let y1=f64_to_i64_trunc(load64(bounds+24));
    vc_require(x0>=0 && y0>=0 && x1>=x0 && y1>=y0 && x1<640 && y1<480,"consumption pixel bounds exceed the camera image");
    let coloured=0;let py=y0;while py<=y1 {let px=x0;while px<=x1 {if va_brick_pixel(ve_rgb+(py*640+px)*3) {coloured=coloured+1;}px=px+1;}py=py+1;}
    vc_require(coloured>=18,"consumption image does not contain coloured brick pixels");
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
    ve_teacher_oracle=0;
    vc_mkdir(output);va_command_intervals(directory);let physical=va_physics(directory);let checksum=ve_policy_open(policy,output);ve_state=vc_json_file(vc_path(directory,"initial.json"));let initial_frame=vc_json_int(ve_state,"totalSteps",0);let target=alloc(24);va_vector(pj_get(pj_index(pj_get(pj_get(ve_state,"case"),"objects"),0),"position"),target,3);va_consumption_count=0;
    let initial=vc_map(vc_path(directory,vc_concat(vc_concat("actor-",vc_int(initial_frame)),".feedback")));vc_require(vc_size==28,"invalid initial feedback");vc_copy(ve_feedback,initial,28);syscall(11,initial,28,0,0,0,0);ve_check(1);va_observation(directory,ve_state,ve_feedback,0,0);
    let hidden=alloc(ve_memory_width*4);let expected=alloc(8);let feedback=alloc(28);let maximum=0;let commands=0;va_lines(vc_path(directory,"decisions.jsonl"));let row=va_next();
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
fn va_verify_data(directory,path,output) {
    ve_teacher_oracle=1;
    vc_mkdir(output);let data=vd_map(path);let bytes=vc_size;vc_require(bytes>=32,"invalid demonstration dataset");let row_bytes=vd_row_bytes(data);vc_require(row_bytes,"invalid demonstration dataset");let episodes=load64(data+8);let fit=load64(data+16);let length=load64(data+24);
    vc_require(episodes>=2 && episodes<=vd_episode_limit(data) && fit>=1 && fit<episodes && length>=1 && length<=512 && bytes==32+episodes*length*(21168+row_bytes),"invalid demonstration dimensions");let limit=episodes;if va_audit_count {limit=va_audit_start+va_audit_count;}vc_require(va_audit_start>=0 && va_audit_start<episodes && limit>va_audit_start && limit<=episodes,"audit range exceeds dataset episodes");let dense=row_bytes==56;let episode=va_audit_start;let total=0;let increments=0;let supervised=0;let replayed=0;let maximum=0;let incomplete_count=0;
    let expected=alloc(8);let feedback=alloc(28);let target=alloc(24);let hidden=alloc(256*4);let students128=0;let students256=0;
    while episode<limit {
        let run=vc_path(directory,vc_concat("expert-",vc_int(episode)));va_command_intervals(run);increments=increments+va_physics(run);let student=0;let student_start=0;let return_rollin=0;let burnin=0;let self=0;let incomplete=0;let termination=0;let recorded_horizon=length;let scheduled=-1;let manifest=vc_path(run,"supervision.json");let intervention=0;
        if !syscall(21,manifest,4,0,0,0,0) {vc_require(row_bytes>=48,"intervention requires PVDATA02 or PVDATA03");intervention=1;let meta=vc_json_file(manifest);student=vc_json_int(meta,"studentActions",0);burnin=vc_json_int(meta,"burninActions",0);self=pj_boolean(meta,"studentCompletedBeforeHandoff");
            let mode=pj_get(meta,"denseOracleLabels");vc_require(!mode || pj_kind(mode)==5,"invalid oracle label mode");if pj_get(meta,"studentStartAction") {student_start=vc_json_int(meta,"studentStartAction",0);}let returning=pj_get(meta,"studentBeginsAfterConsumption");vc_require(!returning || pj_kind(returning)==5,"invalid return roll-in mode");if returning {return_rollin=pj_value(returning);}
            if pj_get(meta,"allowIncomplete") {incomplete=pj_boolean(meta,"allowIncomplete");if incomplete {vc_require(va_allow_incomplete && dense,"incomplete intervention requires explicit opt-in and dense labels");termination=vc_string(pj_string_field(meta,"terminationReason"));if pj_get(meta,"recordedHorizon") {recorded_horizon=vc_json_int(meta,"recordedHorizon",0);}vc_require(recorded_horizon>=1 && recorded_horizon<=512,"invalid recorded intervention horizon");}}
            vc_require(student_start>=0 && student_start+student<=length && ((!return_rollin && !student_start) || (return_rollin && dense && student_start>=1 && student>=1)),"invalid student command window");
            vc_require(pj_value(mode)==dense && student>=0 && student<=length && burnin>=0 && burnin<=student && ((dense && !burnin) || (!dense && ((self && !burnin) || (!self && burnin==student)))),"invalid intervention handoff");
            if pj_get(meta,"scheduledRollinActions") {scheduled=vc_json_int(meta,"scheduledRollinActions",0);let minimum=vc_json_int(meta,"minimumRollinActions",0);let maximum=vc_json_int(meta,"maximumRollinActions",0);vc_require(minimum>=0 && minimum<=scheduled && scheduled<=maximum && maximum<=511 && ((self && student<=scheduled) || (!self && (student==scheduled || (incomplete && student<=scheduled)))),"intervention did not follow its scheduled roll-in");}if incomplete {vc_require(scheduled>=1 && scheduled<=recorded_horizon && student>=1,"incomplete intervention has no valid scheduled student actions");}
            if student {let width=128;if pj_get(meta,"studentMemoryWidth") {width=vc_json_int(meta,"studentMemoryWidth",0);}vc_require(width==128 || width==256,"unsupported intervention student memory width");if width==128 {students128=students128+1;}else {students256=students256+1;}ve_memory_width=width;let policy=vc_string(pj_string_field(meta,"studentPolicy"));let checksum=vc_string(pj_string_field(meta,"studentWeightsSHA256"));let replay=vc_path(output,vc_concat("student-",vc_int(episode)));vc_mkdir(replay);vc_require(pl_equal(ve_policy_open(policy,replay),checksum),"intervention student checkpoint mismatch");pb_zero(hidden,ve_memory_width*4);}
        }
        vc_require(!dense || intervention,"dense labels require an intervention receipt");ve_state=vc_json_file(vc_path(run,"initial.json"));va_consumption_count=0;
        va_vector(pj_get(pj_index(pj_get(pj_get(ve_state,"case"),"objects"),0),"position"),target,3);pb_zero(ve_previous,8);vc_feedback(pj_get(pj_get(ve_state,"controller"),"drive"),ve_previous,0,feedback);ve_check(1);va_observation(run,ve_state,feedback,0,0);
        let base=data+32+episode*length*(21168+row_bytes);let t=0;let phase=0;let queries=0;va_lines(vc_path(run,"decisions.jsonl"));let row=va_next();
        while row {
            vc_require(t<length,"recorded demonstration exceeds dataset horizon");let values=base+length*21168+t*row_bytes;let i=0;
            while i<21168 {vc_require(load8(base+t*21168+i)==load8(ve_image+i),"dataset image differs from its pre-action camera frame");i=i+1;}
            i=0;while i<28 {vc_require(load8(values+i)==load8(ve_feedback+i),"dataset input includes information beyond own feedback");i=i+1;}vc_require(!pb_u32(values+24),"dataset leaks a task-event input");
            let action=pj_get(row,"action");pb_put32(expected,pb_f64_to_f32(pj_real_node(pj_index(action,0))));pb_put32(expected+4,pb_f64_to_f32(pj_real_node(pj_index(action,1))));
            let executed=values+28;if dense {executed=values+48;}vc_require(pb_u32(executed)==pb_u32(expected) && pb_u32(executed+4)==pb_u32(expected+4),"dataset executed actions differ from the recorded commands");vc_require(pb_u32(values+36)==0x3f800000*phase && vd_valid_word(values,row_bytes)==0x3f800000 && pb_u32(values+40)==0x3f800000*(t>=burnin),"dataset phase/validity/supervision differs from its pre-action state");
            if t>=burnin {supervised=supervised+1;}
            if return_rollin {vc_require(phase==(t>=student_start),"return student window does not begin at the first consumed-brick frame");}
            if t<student_start+student {let predicted=ve_action(hidden,0);if t>=student_start {let error=pb_fmax(f64_magnitude(f64_sub(pb_read_float(predicted),pb_read_float(expected))),f64_magnitude(f64_sub(pb_read_float(predicted+4),pb_read_float(expected+4))));maximum=pb_fmax(maximum,error);vc_require(f64_lt(error,vc_number(1,100000)),"frozen student roll-in replay differs");replayed=replayed+1;}}
            ve_state=pj_get(row,"state");ve_contact=0;let own=pj_get(row,"proprio");if f64_eq(pj_real_node(pj_index(own,5)),PB_ONE) {ve_contact=1;}vc_copy(ve_previous,expected,8);vc_feedback(pj_get(pj_get(ve_state,"controller"),"drive"),ve_previous,ve_contact,feedback);
            if intervention {let oracle=pj_get(ve_state,"trainingOracle");vc_require(oracle && pj_boolean(oracle,"enabled"),"intervention did not use an isolated training bridge");let next=vc_json_int(oracle,"queries",0);
                if t<student && !dense {vc_require(!next,"student roll-in queried the oracle");}else {vc_require(next>queries,"supervised correction has no new oracle query");let label=pj_get(oracle,"label");let target_action=expected;if dense {target_action=values+28;}vc_require(pj_kind(label)==3 && pj_count(label)==2 && pb_f64_to_f32(pj_real_node(pj_index(label,0)))==pb_u32(target_action) && pb_f64_to_f32(pj_real_node(pj_index(label,1)))==pb_u32(target_action+4),"supervised correction differs from the oracle label");}queries=next;
            }
            i=0;while i<7 {vc_require(pb_f64_to_f32(pj_real_node(pj_index(own,i)))==pb_u32(feedback+i*4),"demonstration journal is not own-state feedback");i=i+1;}
            ve_steering=f64_to_i64_nearest(f64_mul(pb_read_float(expected),f64_from_i64(1000)));ve_speed=f64_to_i64_nearest(f64_mul(pb_read_float(expected+4),f64_from_i64(1000)));vc_copy(ve_feedback,feedback,28);ve_check(0);va_observation(run,ve_state,feedback,pj_string_field(row,"actorSHA256"),pj_string_field(row,"rgbSHA256"));
            phase=vc_json_int(ve_state,"findReturn","consumedIndex")>=0;if phase && !va_consumption_count {va_consumption(run,ve_state,target);}va_return(ve_state);t=t+1;row=va_next();
        }
        let passed=pj_boolean(pj_get(ve_state,"case"),"passed");vc_require(t>=1,"dataset contains an empty demonstration");if passed {if intervention {vc_require((self && student_start+student==t && (dense || !queries)) || (!self && student_start+student<t),"invalid successful-student/intervention completion");if incomplete {vc_require(pl_equal(termination,"success") && t<=recorded_horizon && (self || student==scheduled),"successful intervention has invalid termination metadata");}}}else {vc_require(va_allow_incomplete && intervention && incomplete && dense && !self && student>=1 && student_start+student<=t,"dataset contains an unsuccessful demonstration");vc_require((pl_equal(termination,"horizon") && t==recorded_horizon) || (pl_equal(termination,"oracle-unavailable") && t<recorded_horizon),"invalid incomplete termination metadata");vc_require(student==scheduled || student_start+student==t,"incomplete student roll-in was truncated inconsistently");incomplete_count=incomplete_count+1;}if student {vc_finish(ve_policy,15000);}let i=t*21168;while i<length*21168 {vc_require(!load8(base+i),"dataset image padding is not zero");i=i+1;}
        i=t*row_bytes;while i<length*row_bytes {vc_require(!load8(base+length*21168+i),"dataset target/feedback padding is not zero");i=i+1;}total=total+t;syscall(11,va_data,va_length,0,0,0,0);episode=episode+1;
    }
    syscall(11,data,bytes,0,0,0,0);let out=alloc(2048);let b=alloc(32);pl_builder(b,out,2048);pl_text(b,"{\"passed\":true,\"runtime\":\"Flexscript\",\"pythonRequired\":false,\"episodes\":");pl_int(b,limit-va_audit_start);pl_text(b,",\"datasetEpisodes\":");pl_int(b,episodes);pl_text(b,",\"firstEpisode\":");pl_int(b,va_audit_start);pl_text(b,",\"commands\":");pl_int(b,total);pl_text(b,",\"physicalMotionIncrements\":");pl_int(b,increments);
    pl_text(b,",\"supervisedSteps\":");pl_int(b,supervised);pl_text(b,",\"studentPolicies128\":");pl_int(b,students128);pl_text(b,",\"studentPolicies256\":");pl_int(b,students256);pl_text(b,",\"studentRollinCommandsReplayed\":");pl_int(b,replayed);pl_text(b,",\"studentRollinMaxAbsError\":");pl_float(b,maximum);pl_text(b,",\"datasetInputsMatchActualRGBAndOwnFeedback\":true,\"executedCommandsMatchRecordings\":true,\"denseOracleLabels\":");pj_bool_text(b,dense);pl_text(b,",\"labelsMatchExecutedCommands\":");pj_bool_text(b,!dense);if va_allow_incomplete {pl_text(b,",\"incompleteEpisodes\":");pl_int(b,incomplete_count);pl_text(b,",\"successfulEpisodes\":");pl_int(b,limit-va_audit_start-incomplete_count);pl_text(b,",\"incompleteReasonIndependentlyVerified\":false,\"incompleteEpisodesClaimedSuccessful\":false");}pl_text(b,",\"preActionAlignmentChecked\":true,\"zeroPaddingChecked\":true,\"taskEventHintAbsent\":true,\"dataSHA256\":");pj_text(b,vd_file_sha(path));pl_text(b,"}\n");vc_write(vc_path(output,"result.json"),out,load64(b+8));pl_write(1,out,load64(b+8));return 0;
}
