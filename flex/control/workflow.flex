// End-to-end native data collection, checkpoint packaging and evaluation.
import "environment.flex";
global vw_root=0;
global vw_output=0;
global vw_policy=0;
global vw_scene=0;
global vw_data=0;
global vw_seed=110000;
global vw_episodes=8;
global vw_validation=8;
global vw_horizon=150;
global vw_epochs=80;
global vw_batch=4;
global vw_rate=700;
global vw_random=0;
global vw_blackout=0;
global vw_hidden=0;
fn vw_binary(name) {return vc_path(vc_path(vw_root,"build/flex/control"),name);}
fn vw_template() {return vc_path(vw_root,"flex/sim/cases/find-return-house.json");}
fn vw_result(path,seed,success,checksum) {
    let out=alloc(4096);let b=alloc(32);pl_builder(b,out,4096);pl_text(b,"{\"seed\":");pl_int(b,seed);pl_text(b,",\"success\":");pj_bool_text(b,success);
    pl_text(b,",\"found\":");pj_bool_text(b,ve_found);pl_text(b,",\"steps\":");pl_int(b,ve_steps);pl_text(b,",\"pathM\":");pl_float(b,ve_path);
    pl_text(b,",\"maxExcursionM\":");pl_float(b,ve_excursion);pl_text(b,",\"searchMaxExcursionM\":");pl_float(b,ve_search_excursion);
    pl_text(b,",\"leftStartRoom\":");pj_bool_text(b,ve_left_room);pl_text(b,",\"roomsVisited\":[");let room=0;let first_room=1;while room<ve_room_count {if ve_room_visits&(1<<room) {if !first_room {pl_char(b,44);}pl_int(b,room);first_room=0;}room=room+1;}pl_text(b,"],\"actionSeconds\":");pl_float(b,vc_number(ve_steps,5));
    pl_text(b,",\"initialCameraPositioningSeconds\":");pl_float(b,vc_number(ve_initial_step,50));pl_text(b,",\"simulationSeconds\":");pl_float(b,vc_number(ve_last_step,50));
    pl_text(b,",\"freshFramesChecked\":");pl_int(b,ve_frame_checks);pl_text(b,",\"blackout\":");pj_bool_text(b,vw_blackout);
    pl_text(b,",\"controller\":");if checksum {pj_text(b,"native neural policy");}else {pj_text(b,"training-only privileged teacher");}pl_text(b,",\"policyWeightsSHA256\":");if checksum {pj_text(b,checksum);}else {pl_text(b,"null");}
    pl_text(b,",\"trainingAndInference\":\"Flexscript/Pup CUDA\",\"orchestration\":\"Flexscript\",\"pythonRequired\":false,\"taskEventHint\":false,\"suppliedMap\":false,\"automaticScans\":0,\"grasps\":0,\"releases\":0}\n");
    vc_require(!load64(b+24),"episode result exceeded limit");vc_write(path,out,load64(b+8));pl_write(1,out,load64(b+8));return out;
}
fn vw_publish(output,weights,method,data,initial) {
    let target=vc_path(output,"weights.bin");if !pl_equal(target,weights) {vc_copy_file(weights,target);}
    vc_copy_file(vw_binary("policy"),vc_path(output,"policy"));vc_require(!syscall(90,vc_path(output,"policy"),448,0,0,0,0),"cannot mark policy executable");
    vc_copy_file(vc_path(vw_root,"flex/control/model.pup"),vc_path(output,"model.pup"));vc_copy_file(vc_path(vw_root,"build/flex/pixel-control-model.flex"),vc_path(output,"factory.flex"));
    let kernels=vc_path(output,"kernels");vc_mkdir(kernels);let names=vc_args();vc_add(names,"activation.ptx");vc_add(names,"binary.ptx");vc_add(names,"convolution.ptx");vc_add(names,"join.ptx");vc_add(names,"matmul.ptx");vc_add(names,"gradients.ptx");
    let out=alloc(16384);let b=alloc(32);pl_builder(b,out,16384);pl_text(b,"{\"schema\":\"puppybot.visual-control-pup.v2\",\"trainingRuntime\":\"Flexscript/Pup CUDA\",\"inferenceRuntime\":\"Flexscript/Pup CUDA\",\"orchestrationRuntime\":\"Flexscript\",\"pythonRequired\":false,\"taskFeedback\":false,\"method\":");pj_text(b,method);
    pl_text(b,",\"weightsSHA256\":");pj_text(b,vc_file_sha(target));pl_text(b,",\"checkpointSHA256\":");pj_text(b,vc_file_sha(target));pl_text(b,",\"binarySHA256\":");pj_text(b,vc_file_sha(vc_path(output,"policy")));
    pl_text(b,",\"graphSHA256\":");pj_text(b,vc_file_sha(vc_path(output,"model.pup")));pl_text(b,",\"dataSHA256\":");if data {pj_text(b,vc_file_sha(data));}else {pl_text(b,"null");}
    pl_text(b,",\"initialWeightsSHA256\":");if initial {pj_text(b,vc_file_sha(initial));}else {pl_text(b,"null");}pl_text(b,",\"fromScratch\":");pj_bool_text(b,vw_random);
    pl_text(b,",\"epochs\":");pl_int(b,vw_epochs);pl_text(b,",\"batch\":");pl_int(b,vw_batch);pl_text(b,",\"learningRateMicros\":");pl_int(b,vw_rate);pl_text(b,",\"seed\":");pl_int(b,vw_seed);
    pl_text(b,",\"preprocessing\":\"Native exact-area uint8 RGB 84x84 NCHW, FP32 normalized by 255\",\"kernels\":{");let i=0;
    while i<load64(names) {let name=load64(names+8+i*8);let path=vc_path(kernels,name);vc_copy_file(vc_path(vw_binary("kernels"),name),path);if i {pl_char(b,44);}pj_text(b,name);pl_char(b,58);pj_text(b,vc_file_sha(path));i=i+1;}
    pl_text(b,"}}\n");vc_require(!load64(b+24),"policy receipt exceeded limit");vc_write(vc_path(output,"receipt.json"),out,load64(b+8));return 0;
}
fn vw_empty_seed(path) {let data=alloc(32);vc_copy(data,"PUPV0001",8);store64(data+16,32);vc_write(path,data,32);return 0;}
fn vw_train(initialize) {
    vc_mkdir(vw_output);let seed=vc_path(vw_output,"seed.bin");let data=vc_path(vw_output,"data.bin");
    if vw_policy {vc_copy_file(vc_path(vw_policy,"weights.bin"),seed);}else {vw_random=1;vw_empty_seed(seed);}
    if initialize {
        vw_random=1;vw_epochs=0;vw_batch=1;let size=32+2*(21168+44);let dummy=alloc(size);vc_copy(dummy,"PVDATA01",8);store64(dummy+8,2);store64(dummy+16,1);store64(dummy+24,1);
        pb_put32(dummy+32+21168+40,0x3f800000);pb_put32(dummy+32+(21168+44)+21168+40,0x3f800000);vc_write(data,dummy,size);syscall(11,dummy,size,0,0,0,0);
    }else {vc_require(vw_data,"train requires --data FILE");vc_copy_file(vw_data,data);}
    let args=vc_args();vc_add(args,vw_binary("trainer"));vc_add(args,seed);vc_add(args,vc_file_sha(seed));vc_add(args,vw_binary("kernels"));vc_add(args,data);vc_add(args,vw_output);
    vc_add(args,vc_int(vw_epochs));vc_add(args,vc_int(vw_batch));vc_add(args,vc_int(vw_rate));vc_add(args,vc_int(vw_seed));if vw_random {vc_add(args,"--random");}
    let process=vc_spawn(args,vc_path(vw_output,"training.log"),0,0);vc_finish(process,900000);
    if !vw_epochs {vc_copy_file(vc_path(vw_output,"last.bin"),vc_path(vw_output,"weights.bin"));}
    let method="Full-episode demonstration learning";if initialize {method="Native random initialization; no learning steps";}
    vw_publish(vw_output,vc_path(vw_output,"weights.bin"),method,data,seed);pl_print(1,"Native policy ready: ");pl_print(1,vw_output);pl_print(1,"\n");return 0;
}
fn vw_teacher(action,history,count,reverse,speed) {
    if !ve_found {
        let goal=pj_get(pj_index(pj_get(pj_get(ve_state,"case"),"objects"),0),"position");let tx=pj_real_node(pj_index(goal,0));let ty=pj_real_node(pj_index(goal,1));
        if f64_lt(load64(ve_pose),vc_number(9,10)) {
            let box=pj_get(pj_get(pj_get(ve_state,"case"),"container"),"position");let side=-1;if f64_lt(pj_real_node(pj_index(box,1)),0) {side=1;}
            tx=PB_ONE;ty=vc_number(side*18,100);
        }
        let dx=f64_sub(tx,load64(ve_pose));let dy=f64_sub(ty,load64(ve_pose+8));let distance=pb_fmax(vc_number(15,100),f64_hypot(dx,dy));
        let error=pb_wrap_pi(f64_sub(f64_atan2(dy,dx),load64(ve_pose+16)));let steering=pb_neg(f64_div(f64_atan(f64_div(f64_mul(vc_number(36,100),f64_sin(error)),distance)),vc_number(785398163,1000000000)));
        pb_put32(action,pb_f64_to_f32(pb_fclamp(steering,pb_neg(PB_ONE),PB_ONE)));pb_put32(action+4,pb_f64_to_f32(speed));vc_copy(history+count*8,action,8);return 0;
    }
    pb_zero(action,8);if reverse<count {vc_copy(action,history+(count-1-reverse)*8,8);pb_put32(action+4,pb_u32(action+4)^0x80000000);}return 0;
}
fn vw_collect() {
    vc_require(vw_validation>=1 && vw_episodes>vw_validation && vw_episodes<=64,"collect requires 2..64 episodes and a smaller positive validation count");vc_mkdir(vw_output);
    let size=32+vw_episodes*64*(21168+44);let path=vc_path(vw_output,"data.partial.bin");let fd=syscall(2,path,0x800c2,384,0,0,0);vc_require(fd>=0 && !syscall(77,fd,size,0,0,0,0),"cannot allocate demonstration dataset");
    let dataset=syscall(9,0,size,3,1,fd,0);vc_require(dataset>0,"cannot map demonstration dataset");vc_copy(dataset,"PVDATA01",8);store64(dataset+8,vw_episodes);store64(dataset+16,vw_episodes-vw_validation);store64(dataset+24,64);
    let episode=0;let action=alloc(8);let history=alloc(64*8);let successful=0;
    while episode<vw_episodes {
        let directory=vc_path(vw_output,vc_concat("expert-",vc_int(episode)));ve_open(vw_binary("simulator"),directory,0,vw_template(),vw_seed+episode,0);
        let count=0;let reverse=0;let speed=vc_uniform(vc_number(5,10),vc_number(9,10));let base=dataset+32+episode*64*(21168+44);
        while ve_steps<64 && !ve_passed {
            vw_teacher(action,history,count,reverse,speed);if !ve_found {count=count+1;}else if reverse<count {reverse=reverse+1;}
            vc_copy(base+ve_steps*21168,ve_image,21168);let row=base+64*21168+ve_steps*44;vc_copy(row,ve_feedback,28);vc_copy(row+28,action,8);pb_put32(row+36,pb_f64_to_f32(f64_from_i64(ve_found)));pb_put32(row+40,0x3f800000);
            ve_step(action);
        }
        if ve_passed {successful=successful+1;}vw_result(vc_path(directory,"result.json"),vw_seed+episode,ve_passed,0);ve_close();episode=episode+1;
    }
    vc_require(!syscall(26,dataset,size,4,0,0,0) && !syscall(74,fd,0,0,0,0,0),"cannot synchronize demonstration dataset");syscall(11,dataset,size,0,0,0,0);syscall(3,fd,0,0,0,0,0);
    vc_require(successful==vw_episodes,"expert failed: all episodes and partial dataset retained; training dataset was not published");vc_require(!syscall(82,path,vc_path(vw_output,"data.bin"),0,0,0,0),"cannot publish completed demonstrations");
    let out=alloc(4096);let b=alloc(32);pl_builder(b,out,4096);pl_text(b,"{\"complete\":true,\"runtime\":\"Flexscript\",\"pythonRequired\":false,\"teacherUsesReferencePose\":true,\"actorUsesReferencePose\":false,\"taskEventHint\":false,\"seed\":");pl_int(b,vw_seed);
    pl_text(b,",\"episodes\":");pl_int(b,vw_episodes);pl_text(b,",\"successes\":");pl_int(b,successful);pl_text(b,",\"trainingEpisodes\":");pl_int(b,vw_episodes-vw_validation);pl_text(b,",\"validationEpisodes\":");pl_int(b,vw_validation);pl_text(b,",\"sequenceLength\":64,\"dataSHA256\":");pj_text(b,vc_file_sha(vc_path(vw_output,"data.bin")));pl_text(b,"}\n");vc_write(vc_path(vw_output,"report.json"),out,load64(b+8));return 0;
}
fn vw_snapshot_policy(source,target) {
    vc_mkdir(target);vc_copy_file(vc_path(source,"weights.bin"),vc_path(target,"weights.bin"));vc_copy_file(vc_path(source,"policy"),vc_path(target,"policy"));syscall(90,vc_path(target,"policy"),448,0,0,0,0);
    vc_copy_file(vc_path(source,"receipt.json"),vc_path(target,"receipt.json"));let root=vc_json_file(vc_path(source,"receipt.json"));let kernels=pj_value(pj_get(root,"kernels"));let directory=vc_path(target,"kernels");vc_mkdir(directory);
    while kernels {let name=load64(kernels+32);vc_require(!pl_starts(name,"/") && !pl_starts(name,".."),"invalid kernel receipt path");vc_copy_file(vc_path(vc_path(source,"kernels"),name),vc_path(directory,name));kernels=load64(kernels+24);}return 0;
}
fn vw_run() {
    vc_require(vw_policy,"run requires --policy DIRECTORY");vc_mkdir(vw_output);let frozen=vc_path(vw_output,"policy");vw_snapshot_policy(vw_policy,frozen);let checksum=ve_policy_open(frozen,vw_output);
    let rows=alloc(65536);let b=alloc(32);pl_builder(b,rows,65536);pl_char(b,91);let episode=0;let successes=0;let found=0;let hidden=alloc(128*4);
    while episode<vw_episodes {
        let seed=vw_seed+episode;let directory=vc_path(vw_output,vc_int(seed));ve_open(vw_binary("simulator"),directory,vw_scene,vw_template(),seed,vw_hidden);pb_zero(hidden,128*4);
        while ve_steps<vw_horizon && !ve_passed {ve_step(ve_action(hidden,vw_blackout));}
        let success=ve_passed && (!vw_hidden || (ve_left_room && f64_ge(ve_search_excursion,vc_number(15,10))));if success {successes=successes+1;}if ve_found {found=found+1;}
        let result=vw_result(vc_path(directory,"result.json"),seed,success,checksum);ve_close();if episode {pl_char(b,44);}pl_text(b,result);episode=episode+1;
    }
    pl_char(b,93);vc_finish(ve_policy,15000);vc_require(!load64(b+24),"evaluation summary exceeded limit");let out=alloc(73728);let s=alloc(32);pl_builder(s,out,73728);
    pl_text(s,"{\"complete\":true,\"runtime\":\"Flexscript\",\"pythonRequired\":false,\"episodes\":");pl_int(s,vw_episodes);pl_text(s,",\"successes\":");pl_int(s,successes);pl_text(s,",\"found\":");pl_int(s,found);
    pl_text(s,",\"blackout\":");pj_bool_text(s,vw_blackout);pl_text(s,",\"hiddenTarget\":");pj_bool_text(s,vw_hidden);pl_text(s,",\"policyWeightsSHA256\":");pj_text(s,checksum);pl_text(s,",\"rows\":");pl_append(s,rows,load64(b+8));pl_text(s,"}\n");
    vc_require(!load64(s+24),"cannot construct evaluation summary");vc_write(vc_path(vw_output,"summary.json"),out,load64(s+8));return 0;
}
