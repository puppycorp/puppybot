// Chase game: drive to a brick that reappears somewhere new after every reach.
// Placement uses the privileged floorplan. The teacher steers only from the
// camera's brick detection and its odometry memory of the last sighting.
import "workflow.flex";
import "actions.flex";
global vw_chase=0;
global vw_chase_forward=0;
global vx_rng=1;
global vx_reaches=0;
global vx_jumps=0;
global vx_jump_step=-1;
global vx_brick=0;
global vx_target=0;
global vx_seen_step=-1000;
global vx_missing=0;
global vx_side=1;
global vx_escape=0;
global vx_contacts=0;
global vx_log=0;
global vx_disagree=0;
fn vx_random() {vx_rng=(vx_rng*1103515245+12345)&2147483647;return vc_number(vx_rng,2147483648);}
fn vx_uniform(lo,hi) {return f64_add(lo,f64_mul(f64_sub(hi,lo),vx_random()));}
fn vx_sign() {if f64_lt(vx_random(),vc_number(1,2)) {return f64_from_i64(-1);}return PB_ONE;}
// Floor and box clearance only; unlike vo_open this plans no route to the case brick.
fn vx_world(directory) {
    vo_close();let old=pj_arena;let used=pj_used;pj_arena=alloc(131072);let root=vc_json_file(vc_path(vc_path(directory,"scene"),"case.json"));
    let box=pj_get(root,"container");let position=pj_get(box,"position");let size=pj_get(box,"innerSize");let wall=pj_real_node(pj_get(box,"wallThickness"));if !vo_box {vo_box=alloc(32);}
    store64(vo_box,pj_real_node(pj_index(position,0)));store64(vo_box+8,pj_real_node(pj_index(position,1)));store64(vo_box+16,f64_add(f64_mul(pj_real_node(pj_index(size,0)),vc_number(1,2)),wall));store64(vo_box+24,f64_add(f64_mul(pj_real_node(pj_index(size,1)),vc_number(1,2)),wall));vc_require(!pj_error,"invalid chase box reference");
    syscall(11,pj_arena,131072,0,0,0,0);pj_arena=old;pj_used=used;vo_world=vc_map(vc_path(vc_path(directory,"scene"),"environment.bin"));vo_world_size=vc_size;
    vc_require(vo_world_size>=256 && load64(vo_world)==load64("PBENV001") && load64(vo_world+8)>=0 && load64(vo_world+8)<=128 && vo_world_size>=256+load64(vo_world+8)*128,"invalid chase environment");vo_width=0;vo_height=0;return 0;
}
fn vx_note(reason,x,y) {
    let text=alloc(512);let b=alloc(32);pl_builder(b,text,512);pl_text(b,"{\"step\":");pl_int(b,ve_steps);pl_text(b,",\"event\":");pj_text(b,reason);pl_text(b,",\"brick\":[");pl_float(b,x);pl_char(b,44);pl_float(b,y);
    pl_text(b,"],\"robot\":[");pl_float(b,load64(ve_pose));pl_char(b,44);pl_float(b,load64(ve_pose+8));pl_char(b,44);pl_float(b,load64(ve_pose+16));pl_text(b,"]}\n");
    vc_require(!load64(b+24) && !pl_write(vx_log,text,load64(b+8)),"cannot journal chase placement");syscall(11,text,512,0,0,0,0);syscall(11,b,32,0,0,0,0);return 0;
}
fn vx_send(x,y,yaw) {
    ve_sequence=ve_sequence+1;pb_zero(ve_request,64);store64(ve_request,5);store64(ve_request+8,ve_sequence);store64(ve_request+24,x);store64(ve_request+32,y);store64(ve_request+40,yaw);
    vc_io(0,load64(ve_process+8),ve_request,64);ve_receive();
    vc_require(vc_json_int(ve_state,"findReturn","consumedIndex")<0,"chase placement did not restore the brick");
    vc_require(vc_json_int(pj_get(ve_state,"case"),"perception","frameId")==vc_json_int(ve_state,"totalSteps",0),"camera frame is stale after placement");return 0;
}
// Mostly in view, some beside the robot, a few behind it; always reachable in a straight line when possible.
fn vx_place(reason) {
    let x=load64(ve_pose);let y=load64(ve_pose+8);let h=load64(ve_pose+16);let px=0;let py=0;let ok=0;let tries=0;vo_clearance=vc_number(30,100);
    while !ok && tries<600 {
        let u=vx_random();let bearing=vx_uniform(vc_number(-45,100),vc_number(45,100));let distance=vx_uniform(vc_number(6,10),vc_number(22,10));
        if f64_ge(u,vc_number(6,10)) {bearing=f64_mul(vx_sign(),vx_uniform(vc_number(6,10),vc_number(15,10)));distance=vx_uniform(vc_number(6,10),vc_number(16,10));}
        if f64_ge(u,vc_number(9,10)) {bearing=f64_mul(vx_sign(),vx_uniform(vc_number(15,10),pb_radians(f64_from_i64(180))));distance=vx_uniform(vc_number(6,10),vc_number(15,10));}
        if tries>=400 {bearing=vx_uniform(pb_neg(pb_radians(f64_from_i64(180))),pb_radians(f64_from_i64(180)));distance=vx_uniform(vc_number(6,10),f64_from_i64(3));}
        px=f64_add(x,f64_mul(distance,f64_cos(f64_add(h,bearing))));py=f64_add(y,f64_mul(distance,f64_sin(f64_add(h,bearing))));
        vo_clearance=vc_number(30,100);ok=vo_free(px,py);if ok && tries<200 {vo_clearance=vc_number(20,100);ok=vo_line(f64_add(x,f64_mul(vc_number(3,10),f64_cos(f64_add(h,bearing)))),f64_add(y,f64_mul(vc_number(3,10),f64_sin(f64_add(h,bearing)))),px,py);}tries=tries+1;
    }
    vc_require(ok,"no free chase placement");store64(vx_brick,px);store64(vx_brick+8,py);vx_send(px,py,vx_uniform(0,pb_radians(f64_from_i64(180))));vx_note(reason,px,py);
    // A fifth of fresh targets later jump once while the robot is still on its way.
    vx_jump_step=-1;if !pl_equal(reason,"jump") && f64_lt(vx_random(),vc_number(2,10)) {vx_jump_step=ve_steps+4+f64_to_i64_nearest(f64_mul(vx_random(),f64_from_i64(8)));}
    if !pl_equal(reason,"jump") {vx_seen_step=-1000;vx_missing=0;}return 0;
}
fn vx_set(action,class) {pb_put32(action,ca_steering_bits(class));pb_put32(action+4,ca_speed_bits(class));return class;}
// Exact seven-class labels: steer at the remembered camera sighting, reverse
// out of contacts, otherwise circle toward the side the brick was last seen.
// Before any sighting the search turns left, so every label follows from the
// camera history; mirror augmentation supplies the right-hand version.
fn vx_teacher(action) {
    let local=pj_get(pj_get(ve_state,"localization"),"pose");vc_require(pj_kind(local)==3 && pj_count(local)==3,"invalid chase localization");
    let lx=pj_real_node(pj_index(local,0));let ly=pj_real_node(pj_index(local,1));let lh=pj_real_node(pj_index(local,2));
    let detections=pj_get(pj_get(pj_get(ve_state,"case"),"perception"),"detections");let seen=0;
    if pj_kind(detections)==3 && pj_count(detections) {let point=pj_get(pj_index(detections,0),"targetM");let tx=pj_real_node(pj_index(point,0));let ty=pj_real_node(pj_index(point,1));
        if !pj_error && f64_is_finite(tx) && f64_is_finite(ty) && f64_lt(f64_hypot(f64_sub(tx,lx),f64_sub(ty,ly)),vc_number(35,10)) {store64(vx_target,tx);store64(vx_target+8,ty);vx_seen_step=ve_steps;vx_missing=0;seen=1;}}
    vc_require(!pj_error,"invalid chase detection");
    if vx_escape>0 {vx_escape=vx_escape-1;if vx_side>0 {return vx_set(action,5);}return vx_set(action,3);}
    if ve_contact {vx_escape=2;return vx_set(action,4);}
    if ve_steps-vx_seen_step<=25 {
        let dx=f64_sub(load64(vx_target),lx);let dy=f64_sub(load64(vx_target+8),ly);let distance=f64_hypot(dx,dy);let error=pb_wrap_pi(f64_sub(f64_atan2(dy,dx),lh));
        if f64_gt(error,0) {vx_side=1;}else {vx_side=-1;}
        // A remembered brick that should be in view but is not was moved.
        if !seen && f64_lt(f64_magnitude(error),vc_number(3,10)) && f64_gt(distance,vc_number(5,10)) && f64_lt(distance,f64_from_i64(2)) {vx_missing=vx_missing+1;if vx_missing>=3 {vx_seen_step=-1000;}}
        if vx_seen_step>=0 {
            if f64_gt(f64_magnitude(error),vc_number(13,10)) && f64_lt(distance,vc_number(7,10)) {if vx_side>0 {return vx_set(action,5);}return vx_set(action,3);}
            if f64_gt(error,vc_number(2,10)) {return vx_set(action,0);}if f64_lt(error,vc_number(-2,10)) {return vx_set(action,2);}return vx_set(action,1);
        }
    }
    let h=load64(ve_pose+16);vo_clearance=vc_number(22,100);
    if !vo_free(f64_add(load64(ve_pose),f64_mul(vc_number(3,10),f64_cos(h))),f64_add(load64(ve_pose+8),f64_mul(vc_number(3,10),f64_sin(h)))) {vx_escape=1;if vx_side>0 {return vx_set(action,5);}return vx_set(action,3);}
    if vx_side>0 {return vx_set(action,0);}return vx_set(action,2);
}
fn vx_result(path,seed,controller,checksum) {
    let out=alloc(4096);let b=alloc(32);pl_builder(b,out,4096);pl_text(b,"{\"seed\":");pl_int(b,seed);pl_text(b,",\"game\":\"chase\",\"controller\":");pj_text(b,controller);
    pl_text(b,",\"reaches\":");pl_int(b,vx_reaches);pl_text(b,",\"jumps\":");pl_int(b,vx_jumps);pl_text(b,",\"steps\":");pl_int(b,ve_steps);pl_text(b,",\"actionSeconds\":");pl_float(b,vc_number(ve_steps,5));
    pl_text(b,",\"reachesPerMinute\":");pl_float(b,f64_div(f64_from_i64(vx_reaches*300),f64_from_i64(pb_max(ve_steps,1))));pl_text(b,",\"contactSteps\":");pl_int(b,vx_contacts);pl_text(b,",\"teacherDisagreements\":");pl_int(b,vx_disagree);pl_text(b,",\"pathM\":");pl_float(b,ve_path);
    pl_text(b,",\"blackout\":");pj_bool_text(b,vw_blackout);pl_text(b,",\"policyWeightsSHA256\":");if checksum {pj_text(b,checksum);}else {pl_text(b,"null");}pl_text(b,",\"maximumBrickDistanceM\":0.35,\"suppliedMap\":false,\"taskEventHint\":false}\n");
    vc_require(!load64(b+24),"chase result exceeded limit");vc_write(path,out,load64(b+8));pl_write(1,out,load64(b+8));return out;
}
// Modes: 0 camera teacher, 1 neural policy, 2 always forward, 3 neural policy drives while the teacher labels.
// Dataset rows are written before each action and always carry the teacher's label.
fn vx_episode(directory,scene,seed,mode,base,hidden) {
    ve_task=3;ve_open(vw_binary("simulator"),directory,scene,vw_template(),seed,0);vx_world(directory);
    vx_rng=(seed*7919+17)&2147483647;if !vx_rng {vx_rng=1;}if !vx_brick {vx_brick=alloc(16);vx_target=alloc(16);}
    vx_reaches=0;vx_jumps=0;vx_disagree=0;vx_seen_step=-1000;vx_missing=0;vx_escape=0;vx_contacts=0;vx_side=1;
    vx_log=syscall(2,vc_path(directory,"chase.jsonl"),0x800c1,384,0,0,0);vc_require(vx_log>=0,"cannot create chase journal");vx_place("start");let action=alloc(8);let label=alloc(8);
    while ve_steps<vw_horizon {
        if mode==0 || mode==3 {vx_teacher(label);vc_copy(action,label,8);}if mode==1 || mode==3 {vc_copy(action,ve_action(hidden,vw_blackout),8);}if mode==2 {vx_set(action,1);}
        if mode==3 && load64(action)!=load64(label) {vx_disagree=vx_disagree+1;}
        if base {vc_copy(base+ve_steps*21168,ve_image,21168);let row=base+vw_horizon*21168+ve_steps*44;vc_copy(row,ve_feedback,28);vc_copy(row+28,label,8);pb_put32(row+36,0);pb_put32(row+40,0x3f800000);}
        if ve_contact {vx_contacts=vx_contacts+1;}ve_step(action);
        if vc_json_int(ve_state,"findReturn","consumedIndex")>=0 {vx_reaches=vx_reaches+1;vx_place("reach");}
        else if ve_steps==vx_jump_step && f64_gt(f64_hypot(f64_sub(load64(vx_brick),load64(ve_pose)),f64_sub(load64(vx_brick+8),load64(ve_pose+8))),vc_number(9,10)) {vx_jumps=vx_jumps+1;vx_place("jump");}
    }
    syscall(3,vx_log,0,0,0,0,0);return 0;
}
fn vx_scene(episode) {if vw_catalog {return vc_path(vw_catalog,vc_int(episode));}return vw_scene;}
fn vx_collect() {
    vc_require(vw_validation>=1 && vw_episodes>vw_validation && vw_episodes<=128,"chase collect requires 2..128 episodes and a smaller positive validation count");vc_require(vw_horizon<=512,"collection horizon must be in 1..512");vc_mkdir(vw_output);
    let size=32+vw_episodes*vw_horizon*(21168+44);let path=vc_path(vw_output,"data.partial.bin");let fd=syscall(2,path,0x800c2,384,0,0,0);vc_require(fd>=0 && !syscall(77,fd,size,0,0,0,0),"cannot allocate chase dataset");
    let dataset=syscall(9,0,size,3,1,fd,0);vc_require(dataset>0,"cannot map chase dataset");vc_copy(dataset,"PVDATA01",8);store64(dataset+8,vw_episodes);store64(dataset+16,vw_episodes-vw_validation);store64(dataset+24,vw_horizon);
    let episode=0;let reaches=0;let mode=0;let checksum=0;let controller="camera-sighting chase teacher";let hidden=alloc(ve_memory_width*4);
    if vw_policy {let frozen=vc_path(vw_output,"policy");vw_snapshot_policy(vw_policy,frozen);checksum=ve_policy_open(frozen,vw_output);mode=3;controller="native neural policy with chase teacher labels";}
    while episode<vw_episodes {
        let directory=vc_path(vw_output,vc_concat("expert-",vc_int(episode)));pb_zero(hidden,ve_memory_width*4);vx_episode(directory,vx_scene(episode),vw_seed+episode,mode,dataset+32+episode*vw_horizon*(21168+44),hidden);
        reaches=reaches+vx_reaches;vx_result(vc_path(directory,"result.json"),vw_seed+episode,controller,checksum);ve_close();vo_close();episode=episode+1;
    }
    if mode==3 {vc_finish(ve_policy,15000);}
    vc_require(!syscall(26,dataset,size,4,0,0,0) && !syscall(74,fd,0,0,0,0,0),"cannot synchronize chase dataset");syscall(11,dataset,size,0,0,0,0);syscall(3,fd,0,0,0,0,0);
    vc_require(!syscall(82,path,vc_path(vw_output,"data.bin"),0,0,0,0),"cannot publish chase demonstrations");
    let out=alloc(4096);let b=alloc(32);pl_builder(b,out,4096);pl_text(b,"{\"complete\":true,\"game\":\"chase\",\"runtime\":\"Flexscript\",\"pythonRequired\":false,\"teacher\":\"camera-sighting chase teacher\",\"studentDriven\":");pj_bool_text(b,mode==3);pl_text(b,",\"teacherUsesCameraDetections\":true,\"teacherUsesReferenceGeometryForWallsOnly\":true,\"teacherUsesTargetCoordinates\":false,\"actorUsesReferencePose\":false,\"actorUsesTargetCoordinates\":false,\"seed\":");pl_int(b,vw_seed);
    pl_text(b,",\"episodes\":");pl_int(b,vw_episodes);pl_text(b,",\"reaches\":");pl_int(b,reaches);pl_text(b,",\"trainingEpisodes\":");pl_int(b,vw_episodes-vw_validation);pl_text(b,",\"validationEpisodes\":");pl_int(b,vw_validation);pl_text(b,",\"sequenceLength\":");pl_int(b,vw_horizon);pl_text(b,",\"dataSHA256\":");pj_text(b,vc_file_sha(vc_path(vw_output,"data.bin")));pl_text(b,"}\n");vc_write(vc_path(vw_output,"report.json"),out,load64(b+8));return 0;
}
fn vx_run() {
    vc_mkdir(vw_output);let checksum=0;let mode=2;let controller="always forward";let hidden=alloc(ve_memory_width*4);
    if !vw_chase_forward {vc_require(vw_policy,"chase run requires --policy DIRECTORY or --chase-forward");let frozen=vc_path(vw_output,"policy");vw_snapshot_policy(vw_policy,frozen);checksum=ve_policy_open(frozen,vw_output);mode=1;controller="native neural policy";}
    let rows=alloc(131072);let b=alloc(32);pl_builder(b,rows,131072);pl_char(b,91);let episode=0;let reaches=0;
    while episode<vw_episodes {
        let seed=vw_seed+episode;let directory=vc_path(vw_output,vc_int(seed));pb_zero(hidden,ve_memory_width*4);vx_episode(directory,vx_scene(episode),seed,mode,0,hidden);reaches=reaches+vx_reaches;
        let result=vx_result(vc_path(directory,"result.json"),seed,controller,checksum);ve_close();vo_close();if episode {pl_char(b,44);}pl_text(b,result);episode=episode+1;
    }
    pl_char(b,93);if mode==1 {vc_finish(ve_policy,15000);}vc_require(!load64(b+24),"chase summary exceeded limit");let out=alloc(139264);let s=alloc(32);pl_builder(s,out,139264);
    pl_text(s,"{\"complete\":true,\"game\":\"chase\",\"episodes\":");pl_int(s,vw_episodes);pl_text(s,",\"reaches\":");pl_int(s,reaches);pl_text(s,",\"controller\":");pj_text(s,controller);pl_text(s,",\"blackout\":");pj_bool_text(s,vw_blackout);
    pl_text(s,",\"policyWeightsSHA256\":");if checksum {pj_text(s,checksum);}else {pl_text(s,"null");}pl_text(s,",\"rows\":");pl_append(s,rows,load64(b+8));pl_text(s,"}\n");
    vc_require(!load64(s+24),"cannot construct chase summary");vc_write(vc_path(vw_output,"summary.json"),out,load64(s+8));return 0;
}
