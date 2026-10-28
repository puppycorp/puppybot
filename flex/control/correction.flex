// Student roll-ins followed by oracle interventions. The roll-in remains in
// recurrent history. Optional dense oracle labels supervise roll-in states
// without replacing the student's executed commands or observed feedback.
import "workflow.flex";
import "exploration-teacher.flex";
global vw_correction_side=0;
global vw_correction_stopped=0;
global vw_correction_returning=0;
global vw_correction_waypoint=0;
global vw_correction_home=0;
global vw_correction_start_side=0;
global vw_return_rollin=0;
global vw_allow_incomplete=0;
global vw_coverage_teacher=0;
global vw_coverage_index=0;
global vw_coverage_first=0;
global vw_coverage_source=0;
global vw_coverage_goal=0;
global vw_coverage_trace=0;
fn vw_correction_reset() {vw_correction_side=vw_correction_start_side;vw_correction_stopped=0;vw_correction_returning=0;vw_correction_home=0;vw_coverage_index=0;if vw_coverage_teacher {vw_coverage_index=sx_start(ve_rooms,ve_room_count,ve_start_room,ve_initial_pose);}vw_coverage_first=vw_coverage_index;vw_coverage_source=0;if !vw_coverage_goal {vw_coverage_goal=alloc(24);}return 0;}
fn vw_coverage_action(action) {
    if sx_camera_goal(ve_state,ve_pose,vw_coverage_goal) && ve_oracle_action(load64(vw_coverage_goal),load64(vw_coverage_goal+8),load64(vw_coverage_goal+16),action) && (pb_u32(action) || pb_u32(action+4)) {vw_coverage_source=1;return 1;}
    let attempts=0;let limit=pb_min(ve_room_count*9,16);while attempts<limit {sx_coverage_goal(ve_rooms,ve_room_count,ve_start_room,ve_initial_pose,vw_coverage_first,vw_coverage_index,vw_coverage_goal);
        if ve_oracle_action(load64(vw_coverage_goal),load64(vw_coverage_goal+8),load64(vw_coverage_goal+16),action) && (pb_u32(action) || pb_u32(action+4)) {vw_coverage_source=2;return 1;}
        vw_coverage_index=vw_coverage_index+1;attempts=attempts+1;
    }return 0;
}
fn vw_coverage_record(action) {
    let text=alloc(512);let b=alloc(32);pl_builder(b,text,512);pl_text(b,"{\"step\":");pl_int(b,ve_steps);pl_text(b,",\"source\":");if ve_found {pj_text(b,"return");}else if vw_coverage_source==1 {pj_text(b,"camera");}else {pj_text(b,"coverage");}
    pl_text(b,",\"coverageIndex\":");pl_int(b,vw_coverage_index);pl_text(b,",\"goal\":[");let i=0;while i<3 {if i {pl_char(b,44);}pl_float(b,load64(ve_oracle_goal+i*8));i=i+1;}pl_text(b,"],\"label\":[");pl_float(b,pb_read_float(action));pl_char(b,44);pl_float(b,pb_read_float(action+4));pl_text(b,"]}\n");vc_require(!load64(b+24) && !pl_write(vw_coverage_trace,text,load64(b+8)),"cannot write coverage teacher trace");syscall(11,text,512,0,0,0,0);syscall(11,b,32,0,0,0,0);return 0;
}
fn vw_correction_action(action) {
    if ve_found!=vw_correction_returning {vw_correction_side=0;vw_correction_stopped=0;vw_correction_returning=ve_found;}
    if vw_coverage_teacher && !ve_found {return vw_coverage_action(action);}
    if ve_contact {vw_correction_side=(vw_correction_side+1)%4;vw_correction_stopped=0;}
    if ve_found && vw_correction_waypoint && !vw_correction_home {
        let h=load64(ve_initial_pose+16);let x=f64_sub(load64(ve_initial_pose),f64_mul(vc_number(4,10),f64_cos(h)));let y=f64_sub(load64(ve_initial_pose+8),f64_mul(vc_number(4,10),f64_sin(h)));
        if ve_oracle_action(x,y,h,action) && (pb_u32(action) || pb_u32(action+4)) {return 1;}vw_correction_home=1;vw_correction_side=0;vw_correction_stopped=0;
    }
    let position=pj_get(pj_index(pj_get(pj_get(ve_state,"case"),"objects"),0),"position");let x=pj_real_node(pj_index(position,0));let y=pj_real_node(pj_index(position,1));let heading=0;let range=vc_number(24,100);
    if ve_found {
        position=pj_get(pj_get(pj_get(ve_state,"case"),"container"),"position");x=pj_real_node(pj_index(position,0));y=pj_real_node(pj_index(position,1));heading=f64_atan2(f64_sub(y,load64(ve_initial_pose+8)),f64_sub(x,load64(ve_initial_pose)));range=vc_number(5,10);
    }
    // The planner may stop up to 10 cm short of its goal. Keep that tolerance
    // inside the task's acceptance bands. An arrived search pose without a
    // real detection must try another approach, rather than wait forever.
    let base=vw_correction_side;let attempt=0;while attempt<4 {let side=(base+attempt)%4;let angle=f64_add(heading,f64_mul(f64_from_i64(side),vc_number(1570796327,1000000000)));let ok=ve_oracle_action(f64_sub(x,f64_mul(range,f64_cos(angle))),f64_sub(y,f64_mul(range,f64_sin(angle))),angle,action);
        if ok {if pb_u32(action) || pb_u32(action+4) {vw_correction_side=side;vw_correction_stopped=0;return 1;}
            // Allow fresh marker stability and three stopped return samples.
            if ve_found {vw_correction_stopped=vw_correction_stopped+1;if vw_correction_stopped<=6 {vw_correction_side=side;return 1;}}
        }attempt=attempt+1;
    }
    return 0;
}
fn vw_correction_manifest(directory,policy,checksum,student,start,burnin,scene,limit,termination) {
    let text=alloc(16384);let b=alloc(32);pl_builder(b,text,16384);pl_text(b,"{\"schema\":\"puppybot.intervention.v1\",\"studentActions\":");pl_int(b,student);pl_text(b,",\"burninActions\":");pl_int(b,burnin);
    pl_text(b,",\"studentStartAction\":");pl_int(b,start);pl_text(b,",\"studentMemoryWidth\":");pl_int(b,ve_memory_width);pl_text(b,",\"studentBeginsAfterConsumption\":");pj_bool_text(b,vw_return_rollin);
    pl_text(b,",\"studentCompletedBeforeHandoff\":");pj_bool_text(b,ve_passed && student>0 && start+student==ve_steps);pl_text(b,",\"studentPolicy\":");pj_text(b,policy);pl_text(b,",\"studentWeightsSHA256\":");pj_text(b,checksum);pl_text(b,",\"sourceScene\":");if scene {pj_text(b,scene);}else {pl_text(b,"null");}
    pl_text(b,",\"minimumRollinActions\":");pl_int(b,vw_rollin_min);pl_text(b,",\"maximumRollinActions\":");pl_int(b,vw_rollin);pl_text(b,",\"scheduledRollinActions\":");pl_int(b,limit);
    pl_text(b,",\"studentSuccessClaimed\":false,\"rollinInputsRetained\":true,\"teacherReturnViaHome\":");pj_bool_text(b,vw_correction_waypoint);pl_text(b,",\"teacherApproachSide\":");pl_int(b,vw_correction_start_side);pl_text(b,",\"denseOracleLabels\":");pj_bool_text(b,vw_label_rollin);pl_text(b,",\"oracleTargetsAreExecutedCommands\":");pj_bool_text(b,!vw_label_rollin);if vw_coverage_teacher {pl_text(b,",\"searchTeacher\":\"coverage-camera-v2\",\"teacherUsesRoomBounds\":true,\"searchGoalsUseUnseenBrickPosition\":false,\"teacherPlannerUsesPrivilegedGeometry\":true");}if vw_allow_incomplete {pl_text(b,",\"allowIncomplete\":true,\"recordedHorizon\":");pl_int(b,vw_horizon);pl_text(b,",\"terminationReason\":");pj_text(b,termination);}pl_text(b,"}\n");vc_require(!load64(b+24),"intervention receipt exceeded limit");vc_write(vc_path(directory,"supervision.json"),text,load64(b+8));syscall(11,text,16384,0,0,0,0);syscall(11,b,32,0,0,0,0);return 0;
}
fn vw_correct() {
    vc_require(vw_policy,"correct requires --policy DIRECTORY");vc_require(vw_validation>=1 && vw_episodes>vw_validation && vw_episodes<=64 && vw_horizon<=512 && vw_rollin_min<=vw_rollin && (vw_rollin<vw_horizon || (vw_allow_incomplete && vw_rollin==vw_horizon)),"invalid correction dimensions");
    vc_require(!vw_return_rollin || (vw_label_rollin && vw_rollin_min>=1),"return roll-in requires dense labels and a positive minimum student window");
    vc_require(!vw_allow_incomplete || (vw_label_rollin && vw_rollin_min>=1),"incomplete corrections require dense labels and a student roll-in");
    vc_require(!vw_coverage_teacher || vw_label_rollin,"coverage teacher requires dense labels");
    vc_mkdir(vw_output);let frozen=vc_path(vw_output,"student");vw_snapshot_policy(vw_policy,frozen);let checksum=ve_policy_open(frozen,vw_output);ve_teacher_oracle=1;
    let row_bytes=48;let format="PVDATA02";if vw_label_rollin {row_bytes=56;format="PVDATA03";}let stride=vw_horizon*(21168+row_bytes);
    let size=32+vw_episodes*stride;let path=vc_path(vw_output,"data.partial.bin");let fd=syscall(2,path,0x800c2,384,0,0,0);vc_require(fd>=0 && !syscall(77,fd,size,0,0,0,0),"cannot allocate correction dataset");let data=syscall(9,0,size,3,1,fd,0);vc_require(data>0,"cannot map correction dataset");vc_copy(data,format,8);store64(data+8,vw_episodes);store64(data+16,vw_episodes-vw_validation);store64(data+24,vw_horizon);
    let episode=0;let successful=0;let total_student=0;let total_labels=0;let hidden=alloc(ve_memory_width*4);let teacher=alloc(8);
    while episode<vw_episodes {let scene=vw_scene;if vw_catalog {scene=vc_path(vw_catalog,vc_int(episode));}let directory=vc_path(vw_output,vc_concat("expert-",vc_int(episode)));let hard=vw_hidden || pl_equal(vw_curriculum,"hidden") || (!scene && pl_equal(vw_curriculum,"mixed") && episode%2);
        ve_open(vw_binary("simulator"),directory,scene,vw_template(),vw_seed+episode,hard);vw_correction_reset();if vw_coverage_teacher {vw_coverage_trace=syscall(2,vc_path(directory,"teacher-search.jsonl"),0x800c1,384,0,0,0);vc_require(vw_coverage_trace>=0,"cannot create coverage teacher trace");}pb_zero(hidden,ve_memory_width*4);vc_rng=(vw_seed+episode)&2147483647;vc_random();let limit=vw_rollin_min+vc_rng%(vw_rollin-vw_rollin_min+1);let student=0;let start=0;let oracle_unavailable=0;if vw_return_rollin {start=-1;}let base=data+32+episode*stride;
        while ve_steps<vw_horizon && !ve_passed && !oracle_unavailable {if start<0 && ve_found {start=ve_steps;}let active=start>=0 && ve_steps>=start && ve_steps<start+limit;let action=teacher;let supervised=1;if vw_label_rollin || !active {if !vw_correction_action(teacher) {if vw_allow_incomplete && student>0 {oracle_unavailable=1;}else {vc_require(0,"correction oracle found no safe oriented route; partial dataset retained");}}}
            // Teacher approach commands still form the student's recurrent
            // history. Advance memory on every warm-up frame before handing
            // over control, using the actual executed-command feedback.
            if !oracle_unavailable {if vw_coverage_teacher {vw_coverage_record(teacher);}let predicted=0;if active || (vw_return_rollin && start<0) {predicted=ve_action(hidden,0);}
            if active {action=predicted;student=student+1;if !vw_label_rollin {supervised=0;}}
            vc_copy(base+ve_steps*21168,ve_image,21168);let row=base+vw_horizon*21168+ve_steps*row_bytes;vc_copy(row,ve_feedback,28);let label=action;if vw_label_rollin {label=teacher;vc_copy(row+48,action,8);}vc_copy(row+28,label,8);pb_put32(row+36,pb_f64_to_f32(f64_from_i64(ve_found)));if supervised {pb_put32(row+40,0x3f800000);}pb_put32(row+44,0x3f800000);ve_step(action);}
        }
        if vw_coverage_teacher {syscall(3,vw_coverage_trace,0,0,0,0,0);vw_coverage_trace=0;}let burnin=student;if vw_label_rollin {burnin=0;}if ve_passed && start+student==ve_steps {burnin=0;let t=0;while t<ve_steps {pb_put32(base+vw_horizon*21168+t*row_bytes+40,0x3f800000);t=t+1;}}
        if vw_allow_incomplete {vc_require(student>=1 && ve_steps>=1,"incomplete correction has no student actions");}let termination="success";if !ve_passed {termination="horizon";if oracle_unavailable {termination="oracle-unavailable";}}vw_correction_manifest(directory,frozen,checksum,student,start,burnin,scene,limit,termination);if ve_passed {successful=successful+1;}total_student=total_student+student;total_labels=total_labels+ve_steps-burnin;vw_result(vc_path(directory,"result.json"),vw_seed+episode,ve_passed,0);ve_close();episode=episode+1;
    }
    vc_finish(ve_policy,15000);vc_require(!syscall(26,data,size,4,0,0,0) && !syscall(74,fd,0,0,0,0,0),"cannot synchronize correction data");syscall(11,data,size,0,0,0,0);syscall(3,fd,0,0,0,0,0);vc_require(vw_allow_incomplete || successful==vw_episodes,"correction failed: all episodes and partial dataset retained");vc_require(!syscall(82,path,vc_path(vw_output,"data.bin"),0,0,0,0),"cannot publish correction data");
    let text=alloc(2048);let b=alloc(32);pl_builder(b,text,2048);pl_text(b,"{\"complete\":true,\"format\":");pj_text(b,format);pl_text(b,",\"runtime\":\"Flexscript\",\"pythonRequired\":false,\"episodes\":");pl_int(b,vw_episodes);pl_text(b,",\"studentMemoryWidth\":");pl_int(b,ve_memory_width);pl_text(b,",\"teacherCompleted\":");pl_int(b,successful);if vw_allow_incomplete {pl_text(b,",\"incompleteEpisodes\":");pl_int(b,vw_episodes-successful);pl_text(b,",\"incompletePrefixesRetained\":true");}pl_text(b,",\"studentRollinActions\":");pl_int(b,total_student);pl_text(b,",\"supervisedActions\":");pl_int(b,total_labels);pl_text(b,",\"studentSuccessClaimed\":false,\"dataSHA256\":");pj_text(b,vc_file_sha(vc_path(vw_output,"data.bin")));pl_text(b,"}\n");vc_write(vc_path(vw_output,"report.json"),text,load64(b+8));pl_write(1,text,load64(b+8));return 0;
}
