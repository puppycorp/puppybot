// End-to-end native data collection, checkpoint packaging and evaluation.
import "oracle.flex";
import "dataset.flex";
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
global vw_batch=2;
global vw_rate=700;
global vw_random=0;
global vw_blackout=0;
global vw_stop_weight_one=0;
global vw_hidden=0;
global vw_curriculum=0;
global vw_catalog=0;
global vw_rollin=30;
global vw_rollin_min=0;
global vw_label_rollin=0;
global vw_categorical=0;
global vw_phase_gate=0;
global vw_event_aux=0;
global vw_phase_from_valid=0;
global vw_checkpoint_every=0;
global vw_mirror_augment=0;
global vw_pose_targets=0;
global vw_target_positions=0;
global vw_target_heatmap=0;
global vw_heat_actor=0;
global vw_heat_stop_gradient=0;
global vw_heat_absence=0;
global vw_large_model=0;
global vw_focus_history=-1;
global vw_focus_copies=0;
global vw_max_optimizer_steps=0;
global vw_reversal_milli=0;
global vw_phase_consistency_milli=0;
global vw_balanced_phase=0;
global vw_return_weight_milli=0;
global vw_contact_weight_milli=0;
global vw_feedback_drop_milli=0;
fn vw_binary(name) {return vc_path(vc_path(vw_root,"build/flex/control"),name);}
fn vw_template() {return vc_path(vw_root,"flex/sim/cases/find-return-house.json");}
fn vw_result(path,seed,success,checksum) {
    let out=alloc(4096);let b=alloc(32);pl_builder(b,out,4096);pl_text(b,"{\"seed\":");pl_int(b,seed);pl_text(b,",\"success\":");pj_bool_text(b,success);
    pl_text(b,",\"found\":");pj_bool_text(b,ve_found);pl_text(b,",\"maximumBrickDistanceM\":0.35");pl_text(b,",\"steps\":");pl_int(b,ve_steps);pl_text(b,",\"pathM\":");pl_float(b,ve_path);
    pl_text(b,",\"maxExcursionM\":");pl_float(b,ve_excursion);pl_text(b,",\"searchMaxExcursionM\":");pl_float(b,ve_search_excursion);
    pl_text(b,",\"leftStartRoom\":");pj_bool_text(b,ve_left_room);pl_text(b,",\"roomsVisited\":[");let room=0;let first_room=1;while room<ve_room_count {if ve_room_visits&(1<<room) {if !first_room {pl_char(b,44);}pl_int(b,room);first_room=0;}room=room+1;}pl_text(b,"],\"actionSeconds\":");pl_float(b,vc_number(ve_steps,5));
    pl_text(b,",\"initialCameraPositioningSeconds\":");pl_float(b,vc_number(ve_initial_step,50));pl_text(b,",\"simulationSeconds\":");pl_float(b,vc_number(ve_last_step,50));
    pl_text(b,",\"freshFramesChecked\":");pl_int(b,ve_frame_checks);pl_text(b,",\"blackout\":");pj_bool_text(b,vw_blackout);
    pl_text(b,",\"controller\":");if checksum {pj_text(b,"native neural policy");}else {pj_text(b,"training-only full-scene oracle");}pl_text(b,",\"policyWeightsSHA256\":");if checksum {pj_text(b,checksum);}else {pl_text(b,"null");}
    pl_text(b,",\"trainingAndInference\":\"Flexscript/Pup CUDA\",\"orchestration\":\"Flexscript\",\"pythonRequired\":false,\"taskEventHint\":false,\"suppliedMap\":false,\"automaticScans\":0,\"grasps\":0,\"releases\":0}\n");
    vc_require(!load64(b+24),"episode result exceeded limit");vc_write(path,out,load64(b+8));pl_write(1,out,load64(b+8));return out;
}
fn vw_memory_width(path) {
    let data=vc_map(path);let bytes=vc_size;vc_require(bytes>=32 && load64(data)==load64("PUPV0001") && load64(data+8)<=4096 && 32+load64(data+8)*256<=bytes,"invalid policy checkpoint directory");let width=0;let i=0;
    while i<load64(data+8) {let row=data+32+i*256;if pl_equal(row,"memory.weight_hh_T") {let n=load64(row+216);vc_require(!width && (n==128 || n==256) && load64(row+192)==2 && load64(row+200)==n*n*3 && load64(row+224)==n*3,"invalid policy memory shape");width=n;}i=i+1;}
    syscall(11,data,bytes,0,0,0,0);vc_require(width,"policy checkpoint has no memory");return width;
}
fn vw_actor_mode(path) {
    let memory=vw_memory_width(path);
    let data=vc_map(path);let bytes=vc_size;vc_require(bytes>=32 && load64(data)==load64("PUPV0001") && load64(data+8)<=4096 && 32+load64(data+8)*256<=bytes,"invalid policy checkpoint directory");let mode=0;let gates=0;let i=0;
    while i<load64(data+8) {let row=data+32+i*256;let found=0;let gate=0;if pl_equal(row,"actor.weight_T") {found=2;}if pl_equal(row,"actor7.weight_T") {found=7;}if pl_equal(row,"actor_search.weight_T") {found=14;gate=1;}if pl_equal(row,"actor_return.weight_T") {found=14;gate=2;}
        if found {let width=7;if found==2 {width=2;}vc_require((!mode || (mode==14 && found==14)) && !(gates&gate) && load64(row+192)==2 && load64(row+200)==memory*width && load64(row+216)==memory && load64(row+224)==width,"invalid or ambiguous policy actor head");mode=found;gates=gates|gate;}i=i+1;
    }syscall(11,data,bytes,0,0,0,0);vc_require(mode && (mode!=14 || gates==3),"policy checkpoint has no supported actor head");return mode;
}
fn vw_action_width(path) {let mode=vw_actor_mode(path);if mode==2 {return 2;}return 7;}
fn vw_has_event_aux(path) {
    let data=vc_map(path);let bytes=vc_size;let found=0;let i=0;while i<load64(data+8) {if pl_equal(data+32+i*256,"critic.event.weight_T") {found=1;}i=i+1;}syscall(11,data,bytes,0,0,0,0);return found;
}
fn vw_has_pose_aux(path) {
    let data=vc_map(path);let bytes=vc_size;let found=0;let i=0;while i<load64(data+8) {if pl_equal(data+32+i*256,"critic.pose.weight_T") {found=1;}i=i+1;}syscall(11,data,bytes,0,0,0,0);return found;
}
fn vw_has_target_aux(path) {
    let data=vc_map(path);let bytes=vc_size;let found=0;let i=0;while i<load64(data+8) {if pl_equal(data+32+i*256,"critic.target.weight_T") {found=1;}i=i+1;}syscall(11,data,bytes,0,0,0,0);return found;
}
fn vw_has_heat_aux(path) {
    let data=vc_map(path);let bytes=vc_size;let found=0;let i=0;while i<load64(data+8) {if pl_equal(data+32+i*256,"critic.heat.weight") {found=1;}i=i+1;}syscall(11,data,bytes,0,0,0,0);return found;
}
fn vw_has_heat_actor(path) {
    let width=vw_memory_width(path);let data=vc_map(path);let bytes=vc_size;let found=0;let i=0;while i<load64(data+8) {let row=data+32+i*256;if pl_equal(row,"visual.merge.weight_T") {vc_require(load64(row+192)==2 && load64(row+200)==400*width && load64(row+216)==400 && load64(row+224)==width,"invalid visual merge shape");found=found|1;}if pl_equal(row,"visual.merge.bias") {vc_require(load64(row+192)==1 && load64(row+200)==width && load64(row+216)==width,"invalid visual merge bias");found=found|2;}i=i+1;}syscall(11,data,bytes,0,0,0,0);vc_require(!found || found==3,"incomplete visual merge");return found==3;
}
fn vw_check_image_shape(path,side) {
    let channels=16;if vw_memory_width(path)==256 {channels=32;}let data=vc_map(path);let bytes=vc_size;let found=0;let i=0;while i<load64(data+8) {let row=data+32+i*256;if pl_equal(row,"encoder.0.weight") {let kernel=8;if side==128 {kernel=12;}vc_require(!found && load64(row+192)==4 && load64(row+200)==channels*3*kernel*kernel && load64(row+216)==channels && load64(row+224)==3 && load64(row+232)==kernel && load64(row+240)==kernel,"checkpoint encoder does not match policy image size");found=1;}i=i+1;}syscall(11,data,bytes,0,0,0,0);vc_require(found,"checkpoint lacks image encoder");return 0;
}
fn vw_publish(output,weights,method,data,initial) {
    let target=vc_path(output,"weights.bin");if !pl_equal(target,weights) {vc_copy_file(weights,target);}
    vw_check_image_shape(target,ve_image_side);
    let mode=vw_actor_mode(target);let categorical=mode!=2;let memory=vw_memory_width(target);let heat_actor=vw_has_heat_actor(target);vc_require(!heat_actor || ((mode==7 || (mode==14 && memory==256)) && vw_has_heat_aux(target)),"heat actor requires a categorical policy and heatmap head");vc_require(ve_image_side==84 || (ve_image_side==128 && heat_actor),"unsupported policy image size or architecture");let binary="policy";let graph="flex/control/model.pup";let factory="build/flex/pixel-control-model.flex";if categorical {binary="policy-categorical";graph="flex/control/model-categorical.pup";factory="build/flex/pixel-control-categorical-model.flex";}if mode==14 {binary="policy-categorical-phase";graph="flex/control/model-categorical-phase.pup";factory="build/flex/pixel-control-categorical-phase-model.flex";}if heat_actor {binary="policy-categorical-heat";graph="flex/control/model-categorical-heat.pup";factory="build/flex/pixel-control-categorical-heat-model.flex";if ve_image_side==128 {binary="policy-categorical-heat-128";graph="flex/control/model-categorical-heat-128.pup";factory="build/flex/pixel-control-categorical-heat-128-model.flex";}}
    if memory==256 {vc_require(ve_image_side==84 && heat_actor && (mode==7 || mode==14),"unsupported large policy architecture");binary="policy-categorical-heat-large";graph="flex/control/model-categorical-heat-large.pup";factory="build/flex/pixel-control-categorical-heat-large-model.flex";if mode==14 {binary="policy-categorical-heat-phase-large";graph="flex/control/model-categorical-heat-phase-large.pup";factory="build/flex/pixel-control-categorical-heat-phase-large-model.flex";}}
    vc_copy_file(vw_binary(binary),vc_path(output,"policy"));vc_require(!syscall(90,vc_path(output,"policy"),448,0,0,0,0),"cannot mark policy executable");
    vc_copy_file(vc_path(vw_root,graph),vc_path(output,"model.pup"));vc_copy_file(vc_path(vw_root,factory),vc_path(output,"factory.flex"));
    let kernels=vc_path(output,"kernels");vc_mkdir(kernels);let names=vc_args();vc_add(names,"activation.ptx");vc_add(names,"binary.ptx");vc_add(names,"convolution.ptx");vc_add(names,"join.ptx");vc_add(names,"matmul.ptx");vc_add(names,"gradients.ptx");vc_add(names,"recurrence.ptx");vc_add(names,"recurrence-backward.ptx");vc_add(names,"recurrence-registers.ptx");vc_add(names,"recurrence-registers-backward.ptx");vc_add(names,"convolution-train.ptx");vc_add(names,"binary-train.ptx");
    let out=alloc(16384);let b=alloc(32);pl_builder(b,out,16384);pl_text(b,"{\"schema\":\"puppybot.visual-control-pup.v2\",\"trainingRuntime\":\"Flexscript/Pup CUDA\",\"inferenceRuntime\":\"Flexscript/Pup CUDA\",\"orchestrationRuntime\":\"Flexscript\",\"pythonRequired\":false,\"taskFeedback\":false,\"method\":");pj_text(b,method);
    pl_text(b,",\"weightsSHA256\":");pj_text(b,vc_file_sha(target));pl_text(b,",\"checkpointSHA256\":");pj_text(b,vc_file_sha(target));pl_text(b,",\"binarySHA256\":");pj_text(b,vc_file_sha(vc_path(output,"policy")));
    pl_text(b,",\"graphSHA256\":");pj_text(b,vc_file_sha(vc_path(output,"model.pup")));pl_text(b,",\"dataSHA256\":");if data {if ve_image_side==128 {pj_text(b,vc_highres_file_sha(data));}else {pj_text(b,vd_file_sha(data));}}else {pl_text(b,"null");}
    pl_text(b,",\"initialWeightsSHA256\":");if initial {pj_text(b,vc_file_sha(initial));}else {pl_text(b,"null");}pl_text(b,",\"fromScratch\":");pj_bool_text(b,vw_random);
    pl_text(b,",\"actionCodec\":");if categorical {let codec="joint-seven-v1";if mode==14 {codec="joint-seven-phase-v1";}pj_text(b,codec);pl_text(b,",\"controlLoss\":\"weighted joint action cross entropy\",\"steeringLossWeight\":null,\"actionTable\":[[-0.6,1],[0,1],[0.6,1],[-0.6,-1],[0,-1],[0.6,-1],[0,0]]");}else {pj_text(b,"continuous-tanh-v1");pl_text(b,",\"controlLoss\":\"weighted control MSE\",\"steeringLossWeight\":8");}
    pl_text(b,",\"phaseGatedNavigation\":");pj_bool_text(b,mode==14);
    if vw_balanced_phase {pl_text(b,",\"balancedPhaseLoss\":true,\"balancedPhaseLossTrainingOnly\":true");}
    if vw_return_weight_milli {pl_text(b,",\"returnControlWeightMilli\":");pl_int(b,vw_return_weight_milli);pl_text(b,",\"returnControlWeightTrainingOnly\":true");}
    if vw_contact_weight_milli {pl_text(b,",\"contactControlWeightMilli\":");pl_int(b,vw_contact_weight_milli);pl_text(b,",\"contactControlWeightTrainingOnly\":true");}
    if vw_feedback_drop_milli {pl_text(b,",\"driveFeedbackDropMilli\":");pl_int(b,vw_feedback_drop_milli);pl_text(b,",\"driveFeedbackDropTrainingOnly\":true");}
    pl_text(b,",\"cameraEventAuxiliary\":");pj_bool_text(b,vw_has_event_aux(target));pl_text(b,",\"cameraEventPositiveWeight\":50,\"cameraEventLossWeight\":1");
    pl_text(b,",\"memoryPoseAuxiliary\":");pj_bool_text(b,vw_has_pose_aux(target));pl_text(b,",\"memoryPoseLossWeight\":1,\"memoryPoseTargetsSHA256\":");if vw_pose_targets {pj_text(b,vc_file_sha(vc_path(vw_pose_targets,"targets.bin")));}else {pl_text(b,"null");}
    pl_text(b,",\"targetPositionAuxiliary\":");pj_bool_text(b,vw_has_target_aux(target));pl_text(b,",\"targetPositionLossWeight\":1,\"targetPositionTargetsSHA256\":");if vw_target_positions {pj_text(b,vc_file_sha(vc_path(vw_target_positions,"targets.bin")));}else {pl_text(b,"null");}
    pl_text(b,",\"targetHeatmapAuxiliary\":");pj_bool_text(b,vw_has_heat_aux(target));
    pl_text(b,",\"heatmapActorFeatures\":");pj_bool_text(b,heat_actor);
    pl_text(b,",\"heatmapActorGradientDetached\":");pj_bool_text(b,vw_heat_stop_gradient);
    pl_text(b,",\"heatmapAbsenceSupervision\":");pj_bool_text(b,vw_heat_absence);
    pl_text(b,",\"stopLossWeight\":");if vw_stop_weight_one {pl_int(b,1);}else {pl_int(b,5);}pl_text(b,",\"speedTransitionLossWeight\":8,\"epochs\":");pl_int(b,vw_epochs);pl_text(b,",\"batch\":");pl_int(b,vw_batch);pl_text(b,",\"learningRateMicros\":");pl_int(b,vw_rate);pl_text(b,",\"seed\":");pl_int(b,vw_seed);
    pl_text(b,",\"checkpointEveryEpochs\":");pl_int(b,vw_checkpoint_every);pl_text(b,",\"phaseSupervisionFromValidFrames\":");pj_bool_text(b,vw_phase_from_valid);
    pl_text(b,",\"sequenceMirrorAugmentation\":");pj_bool_text(b,vw_mirror_augment);pl_text(b,",\"focusHistory\":");if vw_focus_history>=0 {pl_int(b,vw_focus_history);}else {pl_text(b,"null");}pl_text(b,",\"focusCopiesPerEpoch\":");pl_int(b,vw_focus_copies);if vw_max_optimizer_steps {pl_text(b,",\"maxOptimizerSteps\":");pl_int(b,vw_max_optimizer_steps);}if vw_reversal_milli {pl_text(b,",\"reversalPenaltyMilli\":");pl_int(b,vw_reversal_milli);}if vw_phase_consistency_milli {pl_text(b,",\"phaseConsistencyMilli\":");pl_int(b,vw_phase_consistency_milli);}pl_text(b,",\"memoryWidth\":");pl_int(b,memory);
    pl_text(b,",\"preprocessing\":");if ve_image_side==128 {pj_text(b,"Native exact-area uint8 RGB 128x128 NCHW, FP32 normalized by 255");}else {pj_text(b,"Native exact-area uint8 RGB 84x84 NCHW, FP32 normalized by 255");}pl_text(b,",\"imageSide\":");pl_int(b,ve_image_side);pl_text(b,",\"kernels\":{");let i=0;
    while i<load64(names) {let name=load64(names+8+i*8);let path=vc_path(kernels,name);vc_copy_file(vc_path(vw_binary("kernels"),name),path);if i {pl_char(b,44);}pj_text(b,name);pl_char(b,58);pj_text(b,vc_file_sha(path));i=i+1;}
    pl_text(b,"}}\n");vc_require(!load64(b+24),"policy receipt exceeded limit");vc_write(vc_path(output,"receipt.json"),out,load64(b+8));return 0;
}
fn vw_empty_seed(path) {let data=alloc(32);vc_copy(data,"PUPV0001",8);store64(data+16,32);vc_write(path,data,32);return 0;}
fn vw_train(initialize) {
    vc_mkdir(vw_output);let seed=vc_path(vw_output,"seed.bin");let data=vc_path(vw_output,"data.bin");
    if vw_policy {vc_copy_file(vc_path(vw_policy,"weights.bin"),seed);vc_require(vw_memory_width(seed)==128+128*vw_large_model,"initial policy memory width does not match training option");let mode=vw_actor_mode(seed);if mode!=2 {vw_categorical=1;}if mode==14 {vw_phase_gate=1;}if vw_has_event_aux(seed) {vw_event_aux=1;}vc_require(!vw_has_heat_actor(seed) || vw_heat_actor,"continuing a heat actor requires --heat-actor and target supervision");}else {vw_random=1;vw_empty_seed(seed);}
    vc_require(!vw_heat_actor || (vw_categorical && (!vw_phase_gate || vw_large_model)),"heat-actor phase gating requires a large categorical policy");
    vc_require(!vw_phase_consistency_milli || vw_phase_gate,"phase consistency requires a phase-gated policy");
    vc_require(!vw_balanced_phase || vw_phase_gate,"balanced phase loss requires a phase-gated policy");
    if initialize {
        vw_random=1;vw_epochs=0;vw_batch=1;let size=32+2*(21168+44);let dummy=alloc(size);vc_copy(dummy,"PVDATA01",8);store64(dummy+8,2);store64(dummy+16,1);store64(dummy+24,1);
        pb_put32(dummy+32+21168+40,0x3f800000);pb_put32(dummy+32+(21168+44)+21168+40,0x3f800000);vc_write(data,dummy,size);syscall(11,dummy,size,0,0,0,0);
    }else {vc_require(vw_data,"train requires --data FILE");if ve_image_side==128 {vc_copy_file(vw_data,data);}else {vd_copy_file(vw_data,data);}}
    if vw_pose_targets {let copied=vc_path(vw_output,"memory-pose");vc_mkdir(copied);vc_copy_file(vc_path(vw_pose_targets,"targets.bin"),vc_path(copied,"targets.bin"));vc_copy_file(vc_path(vw_pose_targets,"receipt.json"),vc_path(copied,"receipt.json"));vw_pose_targets=copied;}
    if vw_target_positions {let copied=vc_path(vw_output,"target-position");vc_mkdir(copied);vc_copy_file(vc_path(vw_target_positions,"targets.bin"),vc_path(copied,"targets.bin"));vc_copy_file(vc_path(vw_target_positions,"receipt.json"),vc_path(copied,"receipt.json"));vw_target_positions=copied;}
    let args=vc_args();vc_add(args,vw_binary("trainer"));vc_add(args,seed);vc_add(args,vc_file_sha(seed));vc_add(args,vw_binary("kernels"));vc_add(args,data);vc_add(args,vw_output);
    vc_add(args,vc_int(vw_epochs));vc_add(args,vc_int(vw_batch));vc_add(args,vc_int(vw_rate));vc_add(args,vc_int(vw_seed));if vw_random {vc_add(args,"--random");}if vw_phase_gate {vc_add(args,"--phase-gated");}else if vw_categorical {vc_add(args,"--categorical");}
    if vw_event_aux {vc_add(args,"--event-aux");}
    if vw_pose_targets {vc_add(args,"--memory-pose");vc_add(args,vw_pose_targets);}
    if vw_target_positions {if vw_target_heatmap {vc_add(args,"--target-heatmap");}else {vc_add(args,"--target-position");}vc_add(args,vw_target_positions);}
    if vw_heat_actor {vc_add(args,"--heat-actor");}
    if vw_heat_stop_gradient {vc_add(args,"--heat-stop-gradient");}
    if vw_heat_absence {vc_add(args,"--heat-absence");}
    if vw_phase_from_valid {vc_add(args,"--phase-from-valid");}
    if vw_mirror_augment {vc_add(args,"--mirror-augment");}
    if vw_stop_weight_one {vc_add(args,"--stop-weight-one");}
    if vw_large_model {vc_add(args,"--large-model");}
    if vw_focus_copies {vc_add(args,"--focus-history");vc_add(args,vc_int(vw_focus_history));vc_add(args,"--focus-copies");vc_add(args,vc_int(vw_focus_copies));}
    if vw_max_optimizer_steps {vc_add(args,"--max-optimizer-steps");vc_add(args,vc_int(vw_max_optimizer_steps));}
    if vw_reversal_milli {vc_add(args,"--reversal-penalty-milli");vc_add(args,vc_int(vw_reversal_milli));}
    if vw_phase_consistency_milli {vc_add(args,"--phase-consistency-milli");vc_add(args,vc_int(vw_phase_consistency_milli));}
    if vw_balanced_phase {vc_add(args,"--balanced-phase");}
    if vw_return_weight_milli {vc_add(args,"--return-weight-milli");vc_add(args,vc_int(vw_return_weight_milli));}
    if vw_contact_weight_milli {vc_add(args,"--contact-weight-milli");vc_add(args,vc_int(vw_contact_weight_milli));}
    if vw_feedback_drop_milli {vc_add(args,"--drop-drive-feedback-milli");vc_add(args,vc_int(vw_feedback_drop_milli));}
    if vw_checkpoint_every {vc_add(args,"--checkpoint-every");vc_add(args,vc_int(vw_checkpoint_every));}
    let process=vc_spawn(args,vc_path(vw_output,"training.log"),0,0);vc_finish(process,7200000);
    if !vw_epochs {vc_copy_file(vc_path(vw_output,"last.bin"),vc_path(vw_output,"weights.bin"));}
    let method="Full-episode demonstration learning";if vw_categorical {method="Full-episode joint-action classification";}if vw_phase_gate {method="Full-episode joint-action classification with a learned search/return gate";}if initialize {method="Native random initialization; no learning steps";}
    vw_publish(vw_output,vc_path(vw_output,"weights.bin"),method,data,seed);pl_print(1,"Native policy ready: ");pl_print(1,vw_output);pl_print(1,"\n");return 0;
}
fn vw_collect() {
    vc_require(vw_validation>=1 && vw_episodes>vw_validation && vw_episodes<=64,"collect requires 2..64 episodes and a smaller positive validation count");vc_require(vw_horizon<=512,"collection horizon must be in 1..512");vc_mkdir(vw_output);
    let size=32+vw_episodes*vw_horizon*(21168+44);let path=vc_path(vw_output,"data.partial.bin");let fd=syscall(2,path,0x800c2,384,0,0,0);vc_require(fd>=0 && !syscall(77,fd,size,0,0,0,0),"cannot allocate demonstration dataset");
    let dataset=syscall(9,0,size,3,1,fd,0);vc_require(dataset>0,"cannot map demonstration dataset");vc_copy(dataset,"PVDATA01",8);store64(dataset+8,vw_episodes);store64(dataset+16,vw_episodes-vw_validation);store64(dataset+24,vw_horizon);
    let episode=0;let action=alloc(8);let history=alloc(vw_horizon*8);let successful=0;let hidden_episodes=0;
    while episode<vw_episodes {
        let hidden=vw_hidden || pl_equal(vw_curriculum,"hidden") || (!vw_scene && pl_equal(vw_curriculum,"mixed") && episode%2);if hidden {hidden_episodes=hidden_episodes+1;}
        let directory=vc_path(vw_output,vc_concat("expert-",vc_int(episode)));ve_open(vw_binary("simulator"),directory,vw_scene,vw_template(),vw_seed+episode,hidden);vo_open(directory);
        let count=0;let reverse=0;let speed=vc_uniform(vc_number(5,10),vc_number(9,10));let base=dataset+32+episode*vw_horizon*(21168+44);
        while ve_steps<vw_horizon && !ve_passed {
            vo_action(action,history,count,reverse,speed);if !ve_found {count=count+1;}else if reverse<count {reverse=reverse+1;}
            vc_copy(base+ve_steps*21168,ve_image,21168);let row=base+vw_horizon*21168+ve_steps*44;vc_copy(row,ve_feedback,28);vc_copy(row+28,action,8);pb_put32(row+36,pb_f64_to_f32(f64_from_i64(ve_found)));pb_put32(row+40,0x3f800000);
            ve_step(action);
        }
        if ve_passed {successful=successful+1;}vw_result(vc_path(directory,"result.json"),vw_seed+episode,ve_passed,0);vo_close();ve_close();episode=episode+1;
    }
    vc_require(!syscall(26,dataset,size,4,0,0,0) && !syscall(74,fd,0,0,0,0,0),"cannot synchronize demonstration dataset");syscall(11,dataset,size,0,0,0,0);syscall(3,fd,0,0,0,0,0);
    vc_require(successful==vw_episodes,"expert failed: all episodes and partial dataset retained; training dataset was not published");vc_require(!syscall(82,path,vc_path(vw_output,"data.bin"),0,0,0,0),"cannot publish completed demonstrations");
    let out=alloc(4096);let b=alloc(32);pl_builder(b,out,4096);pl_text(b,"{\"complete\":true,\"runtime\":\"Flexscript\",\"pythonRequired\":false,\"teacher\":\"full-scene oracle\",\"teacherUsesReferencePose\":true,\"teacherUsesReferenceGeometry\":true,\"teacherUsesTargetCoordinates\":true,\"actorUsesReferencePose\":false,\"actorUsesReferenceGeometry\":false,\"actorUsesTargetCoordinates\":false,\"taskEventHint\":false,\"seed\":");pl_int(b,vw_seed);
    pl_text(b,",\"episodes\":");pl_int(b,vw_episodes);pl_text(b,",\"successes\":");pl_int(b,successful);pl_text(b,",\"trainingEpisodes\":");pl_int(b,vw_episodes-vw_validation);pl_text(b,",\"validationEpisodes\":");pl_int(b,vw_validation);pl_text(b,",\"hiddenEpisodes\":");pl_int(b,hidden_episodes);pl_text(b,",\"sequenceLength\":");pl_int(b,vw_horizon);pl_text(b,",\"dataSHA256\":");pj_text(b,vc_file_sha(vc_path(vw_output,"data.bin")));pl_text(b,"}\n");vc_write(vc_path(vw_output,"report.json"),out,load64(b+8));return 0;
}
fn vw_snapshot_policy(source,target) {
    vc_mkdir(target);vc_copy_file(vc_path(source,"weights.bin"),vc_path(target,"weights.bin"));vc_copy_file(vc_path(source,"policy"),vc_path(target,"policy"));syscall(90,vc_path(target,"policy"),448,0,0,0,0);
    vc_copy_file(vc_path(source,"receipt.json"),vc_path(target,"receipt.json"));let root=vc_json_file(vc_path(source,"receipt.json"));let kernels=pj_value(pj_get(root,"kernels"));let directory=vc_path(target,"kernels");vc_mkdir(directory);
    while kernels {let name=load64(kernels+32);vc_require(!pl_starts(name,"/") && !pl_starts(name,".."),"invalid kernel receipt path");vc_copy_file(vc_path(vc_path(source,"kernels"),name),vc_path(directory,name));kernels=load64(kernels+24);}return 0;
}
fn vw_run() {
    ve_teacher_oracle=0;
    vc_require(vw_policy,"run requires --policy DIRECTORY");vc_mkdir(vw_output);let frozen=vc_path(vw_output,"policy");vw_snapshot_policy(vw_policy,frozen);let checksum=ve_policy_open(frozen,vw_output);
    let rows=alloc(65536);let b=alloc(32);pl_builder(b,rows,65536);pl_char(b,91);let episode=0;let successes=0;let found=0;let hidden=alloc(ve_memory_width*4);
    while episode<vw_episodes {
        let seed=vw_seed+episode;let directory=vc_path(vw_output,vc_int(seed));ve_open(vw_binary("simulator"),directory,vw_scene,vw_template(),seed,vw_hidden);pb_zero(hidden,ve_memory_width*4);
        while ve_steps<vw_horizon && !ve_passed {ve_step(ve_action(hidden,vw_blackout));}
        let success=ve_passed && (!vw_hidden || (ve_left_room && f64_ge(ve_search_excursion,vc_number(15,10))));if success {successes=successes+1;}if ve_found {found=found+1;}
        let result=vw_result(vc_path(directory,"result.json"),seed,success,checksum);ve_close();if episode {pl_char(b,44);}pl_text(b,result);episode=episode+1;
    }
    pl_char(b,93);vc_finish(ve_policy,15000);vc_require(!load64(b+24),"evaluation summary exceeded limit");let out=alloc(73728);let s=alloc(32);pl_builder(s,out,73728);
    pl_text(s,"{\"complete\":true,\"runtime\":\"Flexscript\",\"pythonRequired\":false,\"episodes\":");pl_int(s,vw_episodes);pl_text(s,",\"successes\":");pl_int(s,successes);pl_text(s,",\"found\":");pl_int(s,found);
    pl_text(s,",\"blackout\":");pj_bool_text(s,vw_blackout);pl_text(s,",\"hiddenTarget\":");pj_bool_text(s,vw_hidden);pl_text(s,",\"policyWeightsSHA256\":");pj_text(s,checksum);pl_text(s,",\"rows\":");pl_append(s,rows,load64(b+8));pl_text(s,"}\n");
    vc_require(!load64(s+24),"cannot construct evaluation summary");vc_write(vc_path(vw_output,"summary.json"),out,load64(s+8));return 0;
}
