// Synchronous simulator and policy clients; only bounded wire bytes cross IPC.
import "observation.flex";
import "scene.flex";
global ve_process=0;
global ve_policy=0;
global ve_sequence=0;
global ve_state=0;
global ve_json=0;
global ve_json_size=0;
global ve_rgb=0;
global ve_image=0;
global ve_feedback=0;
global ve_previous=0;
global ve_request=0;
global ve_policy_input=0;
global ve_policy_output=0;
global ve_contact=0;
global ve_last_step=0;
global ve_initial_step=0;
global ve_steps=0;
global ve_found=0;
global ve_passed=0;
global ve_path=0;
global ve_excursion=0;
global ve_search_excursion=0;
global ve_left_room=0;
global ve_hidden=0;
global ve_pose=0;
global ve_initial_pose=0;
global ve_arm=0;
global ve_journal=0;
global ve_directory=0;
global ve_steering=0;
global ve_speed=0;
global ve_frame_checks=0;
global ve_rooms=0;
global ve_room_count=0;
global ve_start_room=0;
global ve_room_visits=0;
fn ve_open_buffers() {
    ve_rgb=alloc(640*480*3);ve_json=alloc(65537);ve_image=alloc(21168);ve_feedback=alloc(28);ve_previous=alloc(8);ve_request=alloc(64);
    ve_policy_input=alloc((21168+7+128)*4);ve_policy_output=alloc(130*4);ve_pose=alloc(24);ve_initial_pose=alloc(24);ve_arm=alloc(32);ve_rooms=alloc(64*32);vc_pixels_init();return 0;
}
fn ve_policy_open(directory,output) {
    let root=vc_json_file(vc_path(directory,"receipt.json"));let weights=vc_string(pj_string_field(root,"weightsSHA256"));let binary=vc_string(pj_string_field(root,"binarySHA256"));
    vc_require(!pj_error && pl_equal(vc_file_sha(vc_path(directory,"weights.bin")),weights) && pl_equal(vc_file_sha(vc_path(directory,"policy")),binary),"policy receipt/hash mismatch");
    let kernels=pj_get(root,"kernels");let child=pj_value(kernels);
    while child {let name=load64(child+32);vc_require(!pl_starts(name,"/") && !pl_starts(name,"..") && pl_equal(vc_file_sha(vc_path(vc_path(directory,"kernels"),name)),pj_value(child)),"policy kernel hash mismatch");child=load64(child+24);}
    vc_require(pj_kind(kernels)==4 && pj_count(kernels)>=5,"policy kernel receipt is missing");
    let args=vc_args();vc_add(args,vc_path(directory,"policy"));vc_add(args,vc_path(directory,"weights.bin"));vc_add(args,weights);vc_add(args,vc_path(directory,"kernels"));vc_add(args,"3");
    ve_policy=vc_spawn(args,vc_path(output,"policy.log"),0,1);let marker=alloc(8);vc_io(1,load64(ve_policy+8),marker,8);vc_require(load64(marker)==load64("VCPOL001"),"invalid policy handshake");return weights;
}
fn ve_command(command,steering,speed) {
    ve_sequence=ve_sequence+1;pb_zero(ve_request,64);store64(ve_request,command);store64(ve_request+8,ve_sequence);
    store64(ve_request+16,steering);store64(ve_request+24,speed);store64(ve_request+32,10);store64(ve_request+48,2);
    vc_io(0,load64(ve_process+8),ve_request,64);if command==3 {return 0;}
    let header=alloc(32);vc_io(1,load64(ve_process+8),header,32);ve_json_size=load64(header);
    vc_require(ve_json_size>0 && ve_json_size<=65536 && load64(header+8)==640*480*3 && load64(header+16)==ve_sequence,"invalid simulator response");
    ve_contact=load64(header+24);vc_require(ve_contact==0 || ve_contact==1,"invalid contact feedback");
    vc_io(1,load64(ve_process+8),ve_json,ve_json_size);store8(ve_json+ve_json_size,0);vc_io(1,load64(ve_process+8),ve_rgb,640*480*3);
    ve_state=pj_parse(ve_json,ve_json_size);vc_require(ve_state,pj_message);vc_resize(ve_rgb,ve_image);
    vc_feedback(pj_get(pj_get(ve_state,"controller"),"drive"),ve_previous,ve_contact,ve_feedback);syscall(11,header,32,0,0,0,0);return 1;
}
fn ve_pose_read(root,out) {let pose=pj_get(root,"pose");vc_require(pj_kind(pose)==3 && pj_count(pose)==3,"invalid physical pose");let i=0;while i<3 {let value=pj_real_node(pj_index(pose,i));vc_require(!pj_error && f64_is_finite(value),"nonfinite physical pose");store64(out+i*8,value);i=i+1;}return out;}
fn ve_distance(a,b) {return f64_hypot(f64_sub(load64(a),load64(b)),f64_sub(load64(a+8),load64(b+8)));}
fn ve_room(pose) {let i=0;while i<ve_room_count {let room=ve_rooms+i*32;if f64_ge(load64(pose),load64(room)) && f64_le(load64(pose),load64(room+16)) && f64_ge(load64(pose+8),load64(room+8)) && f64_le(load64(pose+8),load64(room+24)) {return i;}i=i+1;}return -1;}
fn ve_reference(scene,environment,hidden) {
    ve_room_visits=0;ve_start_room=0;let path=0;if scene {path=vc_path(scene,"layout.json");}
    if path && !syscall(21,path,4,0,0,0,0) {
        let root=vc_json_file(path);let rooms=pj_get(root,"rooms");ve_room_count=pj_count(rooms);vc_require(pj_kind(rooms)==3 && ve_room_count>=1 && ve_room_count<=64,"invalid reference room list");
        let i=0;while i<ve_room_count {let room=pj_index(rooms,i);vc_require(pj_count(room)==4,"invalid reference room bounds");let k=0;while k<4 {store64(ve_rooms+i*32+k*8,pj_real_node(pj_index(room,k)));k=k+1;}i=i+1;}
        ve_start_room=vc_json_int(root,"startRoom",0);vc_require(!pj_error && ve_start_room>=0 && ve_start_room<ve_room_count,"invalid reference start room");
    }else {
        let data=vc_map(environment);vc_require(vc_size>=256 && load64(data)==load64("PBENV001"),"invalid reference environment");vc_copy(ve_rooms,data+64,32);syscall(11,data,vc_size,0,0,0,0);ve_room_count=1;
        if hidden {vc_copy(ve_rooms+32,ve_rooms,32);store64(ve_rooms+16,vc_number(12,10));store64(ve_rooms+32,vc_number(12,10));ve_room_count=2;}
    }return 0;
}
fn ve_check(first) {
    vc_require(!vc_json_int(ve_state,"physicsFault",0) && !vc_json_int(pj_get(ve_state,"vehicle"),"queryFault",0),"native physics fault");
    let gripper=pj_get(ve_state,"gripper");vc_require(!pj_boolean(gripper,"held") && !vc_json_int(gripper,"grasps",0) && !vc_json_int(gripper,"releases",0),"visual control must not grasp/release");
    let discovery=pj_get(ve_state,"discovery");vc_require(!pj_boolean(discovery,"suppliedMap") && !pj_boolean(discovery,"worldPoseInput") && !vc_json_int(discovery,"scans",0) && !vc_json_int(discovery,"freeCells",0) && !vc_json_int(discovery,"occupiedCells",0),"visual control received automatic mapping/scans");
    let frame=vc_json_int(ve_state,"totalSteps",0);let state_step=vc_json_int(ve_state,"step",0);let camera=pj_get(ve_state,"camera");
    vc_require(pl_equal(pj_string_field(camera,"pose"),"driving") && pj_boolean(camera,"armSettled"),"camera must remain in its forward driving pose");
    vc_require(vc_json_int(pj_get(ve_state,"case"),"perception","frameId")==frame,"camera frame is stale");
    let angles=pj_get(ve_state,"jointAnglesRad");let i=0;while i<4 {let value=pj_real_node(pj_index(angles,i));if first {store64(ve_arm+i*8,value);}else {vc_require(f64_lt(f64_magnitude(f64_sub(value,load64(ve_arm+i*8))),vc_number(1,100000000)),"arm moved during visual control");}i=i+1;}
    if !first {
        vc_require(state_step==ve_last_step+10,"physical action did not advance ten ticks");let drive=pj_get(pj_get(ve_state,"controller"),"drive");let throttle=ve_speed*60/1000;if pb_abs(ve_speed)<80 {throttle=0;}
        let angle=vc_json_int(drive,"steeringAngleDeg",0);let expected=90+(ve_steering/10)*45/100;
        // The RGB task's successful stop centers steering after the sampled
        // action ticks. The physical trace still carries the executed angle.
        let completed_stop=pj_boolean(pj_get(ve_state,"case"),"passed") && !throttle && angle==90;
        vc_require(vc_json_int(drive,"leftSpeed",0)==throttle && vc_json_int(drive,"rightSpeed",0)==throttle && (angle==expected || completed_stop),"physical motor commands differ from policy outputs");
    }
    vc_require(!pj_error && !pb_u32(ve_feedback+24),"actor task-event hint must remain zero");ve_last_step=state_step;ve_frame_checks=ve_frame_checks+1;return 0;
}
fn ve_observation_save() {
    let frame=vc_json_int(ve_state,"totalSteps",0);let stem=vc_concat("actor-",vc_int(frame));vc_write(vc_path(ve_directory,vc_concat(stem,".rgb")),ve_image,21168);
    vc_write(vc_path(ve_directory,vc_concat(stem,".feedback")),ve_feedback,28);return 0;
}
fn ve_record(action) {
    let builder=alloc(32);let text=alloc(65536);pl_builder(builder,text,65536);pl_text(builder,"{\"sequence\":");pl_int(builder,ve_sequence);
    pl_text(builder,",\"step\":");pl_int(builder,ve_last_step);pl_text(builder,",\"action\":[");pl_float(builder,pb_read_float(action));pl_char(builder,44);pl_float(builder,pb_read_float(action+4));
    pl_text(builder,"],\"proprio\":[");let i=0;while i<7 {if i {pl_char(builder,44);}pl_float(builder,pb_read_float(ve_feedback+i*4));i=i+1;}
    pl_text(builder,"],\"rgbSHA256\":");pj_text(builder,vc_digest(ve_rgb,921600));pl_text(builder,",\"actorSHA256\":");pj_text(builder,vc_digest(ve_image,21168));
    pl_text(builder,",\"state\":");let n=ve_json_size;if load8(ve_json+n-1)==10 {n=n-1;}pl_append(builder,ve_json,n);pl_text(builder,"}\n");vc_require(!load64(builder+24) && !pl_write(ve_journal,text,load64(builder+8)),"cannot journal visual controls");
    ve_observation_save();syscall(11,builder,32,0,0,0,0);syscall(11,text,65536,0,0,0,0);return 0;
}
fn ve_open(binary,output,scene,template,seed,hidden) {
    ve_directory=output;vc_mkdir(output);let world=vc_path(output,"scene");vc_mkdir(world);ve_hidden=hidden;
    if scene {vc_copy_file(vc_path(scene,"case.json"),vc_path(world,"case.json"));vc_copy_file(vc_path(scene,"environment.bin"),vc_path(world,"environment.bin"));}
    else {vc_environment(vc_path(world,"environment.bin"),hidden);vc_case(vc_path(world,"case.json"),template,seed,hidden);}
    ve_reference(scene,vc_path(world,"environment.bin"),hidden);let args=vc_args();vc_add(args,binary);vc_add(args,"--hidden");vc_add(args,"--case-file");vc_add(args,vc_path(world,"case.json"));vc_add(args,"--environment");vc_add(args,vc_path(world,"environment.bin"));
    vc_add(args,"--steps");vc_add(args,"1000000");vc_add(args,"--bind");vc_add(args,"127.0.0.1:0");vc_add(args,"--agent-fd");vc_add(args,"3");vc_add(args,"--observer-distance-mm");vc_add(args,"2500");vc_add(args,"--tcp-view");
    vc_add(args,"--video");vc_add(args,vc_path(output,"mission.mp4"));vc_add(args,"--video-fps");vc_add(args,"5");vc_add(args,"--record");vc_add(args,vc_path(output,"trace.jsonl"));
    vc_add(args,"--capture");vc_add(args,vc_path(output,"outcome.png"));vc_add(args,"--search-output");vc_add(args,vc_path(output,"sensor"));
    ve_process=vc_spawn(args,vc_path(output,"native.log"),0,1);ve_sequence=0;ve_steps=0;ve_found=0;ve_passed=0;ve_path=0;ve_excursion=0;ve_search_excursion=0;ve_left_room=0;ve_frame_checks=0;
    pb_zero(ve_previous,8);ve_command(1,0,0);ve_check(1);ve_pose_read(ve_state,ve_pose);vc_copy(ve_initial_pose,ve_pose,24);ve_initial_step=ve_last_step;
    vc_require(vc_json_int(ve_state,"findReturn","consumedIndex")<0 && !pj_boolean(pj_get(ve_state,"case"),"passed"),"reset already satisfies task");
    let room=ve_room(ve_pose);if room>=0 {ve_room_visits=ve_room_visits|(1<<room);}ve_journal=syscall(2,vc_path(output,"decisions.jsonl"),0x800c1,384,0,0,0);vc_require(ve_journal>=0,"cannot create decision journal");ve_observation_save();vc_write(vc_path(output,"initial.json"),ve_json,ve_json_size);return 0;
}
fn ve_step(action) {
    let steering=pb_read_float(action);let speed=pb_read_float(action+4);vc_require(f64_is_finite(steering) && f64_is_finite(speed) && f64_le(f64_magnitude(steering),PB_ONE) && f64_le(f64_magnitude(speed),PB_ONE),"nonfinite/unbounded policy action");
    ve_steering=f64_to_i64_nearest(f64_mul(steering,f64_from_i64(1000)));ve_speed=f64_to_i64_nearest(f64_mul(speed,f64_from_i64(1000)));vc_copy(ve_previous,action,8);
    ve_command(2,ve_steering,ve_speed);ve_check(0);let before=alloc(24);vc_copy(before,ve_pose,24);ve_pose_read(ve_state,ve_pose);ve_path=f64_add(ve_path,ve_distance(before,ve_pose));syscall(11,before,24,0,0,0,0);
    let excursion=ve_distance(ve_initial_pose,ve_pose);ve_excursion=pb_fmax(ve_excursion,excursion);let room=ve_room(ve_pose);if room>=0 {ve_room_visits=ve_room_visits|(1<<room);}if !ve_found {ve_search_excursion=pb_fmax(ve_search_excursion,excursion);if room>=0 && room!=ve_start_room {ve_left_room=1;}}
    ve_found=vc_json_int(ve_state,"findReturn","consumedIndex")>=0;ve_passed=pj_boolean(pj_get(ve_state,"case"),"passed");
    if ve_passed {
        let container=pj_get(pj_get(ve_state,"case"),"container");let position=pj_get(container,"position");let dx=f64_sub(pj_real_node(pj_index(position,0)),load64(ve_pose));let dy=f64_sub(pj_real_node(pj_index(position,1)),load64(ve_pose+8));
        let range=f64_hypot(dx,dy);let error=f64_magnitude(pb_wrap_pi(f64_sub(f64_atan2(dy,dx),load64(ve_pose+16))));
        vc_require(ve_found && f64_ge(range,vc_number(3,10)) && f64_le(range,vc_number(65,100)) && f64_le(error,pb_radians(f64_from_i64(35))) && vc_json_int(ve_state,"findReturn","stableReturnObservations")>=3,"invalid physical return pose");
        vc_require(vc_json_int(pj_get(ve_state,"case"),"dockVision","frameId")==vc_json_int(ve_state,"totalSteps",0),"return box view is stale");
    }
    ve_steps=ve_steps+1;ve_record(action);return ve_passed;
}
fn ve_action(hidden,blackout) {
    vc_policy_input(ve_image,ve_feedback,hidden,ve_policy_input,blackout);vc_io(0,load64(ve_policy+8),ve_policy_input,(21168+7+128)*4);vc_io(1,load64(ve_policy+8),ve_policy_output,130*4);
    vc_copy(hidden,ve_policy_output+8,128*4);return ve_policy_output;
}
fn ve_close() {ve_command(3,0,0);vc_finish(ve_process,45000);syscall(3,ve_journal,0,0,0,0,0);return 0;}
