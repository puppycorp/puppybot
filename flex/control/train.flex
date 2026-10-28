// Full-episode demonstration training: data batching, CNN/GRU backward,
// gradient clipping, Adam, validation and checkpoint selection are Flexscript.
import "training.flex";
import "dataset.flex";
import "loss.flex";
import "augmentation.flex";
import "pose-supervision.flex";
import "target-supervision.flex";
global pt_data=0;
global pt_data_size=0;
global pt_length=0;
global pt_batch=0;
global pt_record_size=0;
global pt_row_bytes=44;
global pt_batch_images=0;
// A training batch is filled on the host while the previous step's backward pass runs.
global pt_fill_feedback=0;
global pt_fill_count=0;
global pt_prefetch_order=0;
global pt_prefetch_start=-1;
global pt_prefetch_count=0;
global pt_prefetched=-1;
global pt_batch_proprio=0;
global pt_batch_targets=0;
global pt_batch_phase_masks=0;
global pt_phase_from_valid=0;
global pt_image_job=0;
global pt_batch_device=0;
global pt_prediction=0;
global pt_phase_prediction=0;
global pt_action_seed=0;
global pt_phase_seed=0;
global pt_event_prediction=0;
global pt_event_seed=0;
global pt_pose_directory=0;
global pt_batch_pose=0;
global pt_pose_prediction=0;
global pt_pose_seed=0;
global pt_target_directory=0;
global pt_batch_target_positions=0;
global pt_target_prediction=0;
global pt_target_seed=0;
global pt_target_width=2;
global pt_heat_absence=0;
global pt_memcpy=0;
global pt_last_norm=0;
global pt_checkpoint_every=0;
global pt_mirror_augment=0;
global pt_mirror_active=0;
global pt_mirror_mask_host=0;
global pt_mirrored_sequences=0;
global pt_stop_weight_one=0;
global pt_large_option=0;
global pt_focus_history=-1;
global pt_focus_copies=0;
global pt_max_optimizer_steps=0;
global pt_reversal_scratch=0;
global pt_phase_consistency_milli=0;
global pt_balanced_phase=0;
global pt_return_weight_milli=0;
global pt_contact_weight_milli=0;
global pt_feedback_drop_milli=0;
global pt_feedback_drop_active=0;
global pt_feedback_drop_mask_host=0;
global pt_feedback_drop_proprio=0;
global pt_feedback_dropped_sequences=0;

fn pt_data_open(path) {
    let fd=syscall(2,path,0x80000,0,0,0,0);vp_require(fd>=0,"cannot open demonstration data");let size=syscall(8,fd,0,2,0,0,0);
    vp_require(size>=32 && size<=8589934592,"demonstration data size is outside 32 B..8 GiB");pt_data_size=size;let data=syscall(9,0,size,1,2,fd,0);syscall(3,fd,0,0,0,0,0);vp_require(data>0,"cannot map demonstration data");vp_require(pt_image_side==128 || size<=VC_MAX_FILE_BYTES || load64(data)==load64("PVDATA04"),"legacy demonstration data exceeds 2 GiB");return data;
}
fn pt_batch_open() {
    // Pinned staging lets the image upload use direct DMA.
    let count=pt_batch*pt_length;pt_batch_images=device_host_buffer(count*pt_image_bytes);vp_require(pt_batch_images,device_error());pt_batch_proprio=alloc(count*7*4);pt_batch_targets=alloc(count*4*4);pt_batch_phase_masks=alloc(count*4);
    pt_prediction=alloc(count*pt_action_width*4);pt_phase_prediction=alloc(count*4);pt_action_seed=alloc(count*pt_action_width*4);pt_phase_seed=alloc(count*4);
    if pt_event_aux {pt_event_prediction=alloc(count*4);pt_event_seed=alloc(count*4);}
    if pt_pose_aux {pt_batch_pose=alloc(count*20);pt_pose_prediction=alloc(count*16);pt_pose_seed=alloc(count*16);}
    if pt_target_aux || pt_heat_aux {if pt_heat_aux {pt_target_width=400;}pt_batch_target_positions=alloc(count*12);pt_target_prediction=alloc(count*pt_target_width*4);pt_target_seed=alloc(count*pt_target_width*4);}
    if pt_reversal_milli {pt_reversal_scratch=alloc(112);}
    pt_batch_device=vp_buffer(count*pt_image_bytes);let mode=103;if pt_mirror_augment {mode=104;if pt_image_side==128 {mode=105;}}pt_image_job=pt_launch(pt_batch_device,load64(pt_images),count*pt_image_bytes,mode,pt_batch,0,0);
    if pt_mirror_augment {pt_mirror_mask_host=alloc(8);store64(load64(pt_image_job)+5*8,pt_mirror_mask_host);}
    if pt_feedback_drop_milli {pt_feedback_drop_mask_host=alloc(8);pt_feedback_drop_proprio=alloc(count*28);}
    pt_memcpy=ffi_symbol(ffi_open("libc.so.6"),"memcpy");vp_require(pt_memcpy,"memcpy is unavailable");return 0;
}
// The mapped demonstrations never change, so every row is checked once before training.
fn pt_check_rows(episodes) {
    let episode=0;while episode<episodes {let base=pt_data+32+episode*pt_record_size;let t=0;
        while t<pt_length {let values=base+pt_length*pt_image_bytes+t*pt_row_bytes;
            let field=0;while field<pt_row_bytes/4 {vp_require(f64_is_finite(pb_read_float(values+field*4)),"nonfinite demonstration value");field=field+1;}
            vp_require(!f64_magnitude(pb_read_float(values+24)),"task-event feedback must be masked during training");
            if pt_contact_weight_milli {vp_require(pb_u32(values+20)==0 || pb_u32(values+20)==0x3f800000,"contact feedback must be binary");}
            vp_require(f64_le(f64_magnitude(pb_read_float(values+28)),PB_ONE) && f64_le(f64_magnitude(pb_read_float(values+32)),PB_ONE),"demonstration action exceeds [-1,1]");
            vp_require((pb_u32(values+36)==0 || pb_u32(values+36)==0x3f800000) && (pb_u32(values+40)==0 || pb_u32(values+40)==0x3f800000),"invalid demonstration phase/mask");
            let frame=vd_valid_word(values,pt_row_bytes);vp_require((frame==0 || frame==0x3f800000) && (!pb_u32(values+40) || frame),"invalid valid-frame/supervision mask");
            if pt_row_bytes==56 {vp_require(f64_le(f64_magnitude(pb_read_float(values+48)),PB_ONE) && f64_le(f64_magnitude(pb_read_float(values+52)),PB_ONE),"executed demonstration action exceeds [-1,1]");}
            t=t+1;}
        episode=episode+1;}return 0;
}
fn pt_batch_fill(order,start,count) {
    let mirror_mask=0;if pt_mirror_augment && pt_mirror_active {mirror_mask=pm_mask(pt_batch,count);}if pt_mirror_augment {store64(pt_mirror_mask_host,mirror_mask);}
    let feedback_mask=0;if pt_feedback_drop_milli && pt_feedback_drop_active {feedback_mask=pf_mask(pt_batch,count,pt_feedback_drop_milli);}if pt_feedback_drop_milli {store64(pt_feedback_drop_mask_host,feedback_mask);}
    let b=0;while b<pt_batch {
        let active=b<count;let episode=0;if active {episode=load64(order+(start+b)*8);}
        if (mirror_mask>>b)&1 {pt_mirrored_sequences=pt_mirrored_sequences+1;}
        let base=pt_data+32+episode*pt_record_size;let t=0;
        while t<pt_length {let index=t*pt_batch+b;let values=base+pt_length*pt_image_bytes+t*pt_row_bytes;
            let frame=vd_valid_word(values,pt_row_bytes);
            ffi_call(pt_memcpy,pt_batch_images+index*pt_image_bytes,base+t*pt_image_bytes,pt_image_bytes,0,0,0);
            ffi_call(pt_memcpy,pt_batch_proprio+index*7*4,values,7*4,0,0,0);
            ffi_call(pt_memcpy,pt_batch_targets+index*4*4,values+7*4,4*4,0,0,0);
            if (mirror_mask>>b)&1 {pm_feedback(pt_batch_proprio+index*28,pt_batch_targets+index*16,frame);}
            if pt_pose_aux {let target=pt_batch_pose+index*20;ffi_call(pt_memcpy,target,pt_pose_data+32+(episode*pt_length+t)*20,20,0,0,0);if (mirror_mask>>b)&1 {pm_pose(target,frame);}if !active {pb_put32(target+16,0);}}
            if pt_target_aux || pt_heat_aux {let target=pt_batch_target_positions+index*12;ffi_call(pt_memcpy,target,pt_target_data+32+(episode*pt_length+t)*12,12,0,0,0);if (mirror_mask>>b)&1 {pm_target(target,pb_u32(target+8));}if pt_heat_absence && active && frame && t && pb_u32(values+36) {let previous=values-pt_row_bytes;if vd_valid_word(previous,pt_row_bytes) && pb_u32(previous+36) {pb_put32(target+8,0xbf800000);}}if !active {pb_put32(target+8,0);}}
            pb_put32(pt_batch_phase_masks+index*4,pt_phase_mask(pb_u32(values+40),frame,active,pt_phase_from_valid));
            if !active {pb_put32(pt_batch_targets+(index*4+3)*4,0);}t=t+1;
        }b=b+1;
    }pt_fill_feedback=feedback_mask;pt_fill_count=count;return 0;
}
fn pt_batch_send() {
    let feedback_mask=pt_fill_feedback;let count=pt_fill_count;pt_upload(pt_batch_device,pt_batch_images,pt_batch*pt_length*pt_image_bytes);pt_dispatch(pt_image_job);vp_check(device_stream_wait(vp_stream));
    let proprio_input=pt_batch_proprio;if feedback_mask {let bytes=pt_batch*pt_length*28;ffi_call(pt_memcpy,pt_feedback_drop_proprio,pt_batch_proprio,bytes,0,0,0);let t=0;while t<pt_length {let sample=0;while sample<count {if (feedback_mask>>sample)&1 {pf_neutral_drive(pt_feedback_drop_proprio+(t*pt_batch+sample)*28);}sample=sample+1;}t=t+1;}
        let sample=0;while sample<count {if (feedback_mask>>sample)&1 {pt_feedback_dropped_sequences=pt_feedback_dropped_sequences+1;}sample=sample+1;}proprio_input=pt_feedback_drop_proprio;}
    pt_upload(load64(pt_proprio),proprio_input,pt_batch*pt_length*7*4);return 0;
}
fn pt_batch_load(order,start,count) {pt_batch_fill(order,start,count);return pt_batch_send();}
fn pt_prefetch() {if pt_prefetch_start>=0 {pt_batch_fill(pt_prefetch_order,pt_prefetch_start,pt_prefetch_count);pt_prefetched=pt_prefetch_start;pt_prefetch_start=-1;}return 0;}
fn pt_loss(training,rate) {
    vp_execute();if training {pt_zero_grad();}
    // Keep separate host buffers for every time step. Queue transfers on the
    // execution stream, then wait once before CPU reads or buffer reuse.
    // Fused graphs keep every step's outputs contiguous, so one transfer covers the sequence.
    let action_bytes=pt_batch*pt_action_width*4;let steps=pt_length;let span=1;if pt_fused {steps=1;span=pt_length;}let t=0;while t<steps {
        vp_check(device_download_async(pt_prediction+t*action_bytes,load64(vp_at(pt_actions,t)),action_bytes*span,vp_stream));
        vp_check(device_download_async(pt_phase_prediction+t*pt_batch*4,load64(vp_at(pt_phases,t)),pt_batch*4*span,vp_stream));if pt_event_aux {vp_check(device_download_async(pt_event_prediction+t*pt_batch*4,load64(vp_at(pt_events,t)),pt_batch*4,vp_stream));}if pt_pose_aux {vp_check(device_download_async(pt_pose_prediction+t*pt_batch*16,load64(vp_at(pt_poses,t)),pt_batch*16,vp_stream));}if pt_target_aux || pt_heat_aux {let size=pt_batch*pt_target_width*4;vp_check(device_download_async(pt_target_prediction+t*size,load64(vp_at(pt_target_predictions,t)),size,vp_stream));}t=t+1;
    }vp_check(device_stream_wait(vp_stream));
    let weights=0;let valid=0;let phase_valid=0;let phase_positive=0;let phase_negative=0;let event_weights=0;let pose_valid=0;let target_valid=0;let target_absent=0;let index=0;
    while index<pt_batch*pt_length {
        let target=pt_batch_targets+index*16;let mask=pb_read_float(target+12);let weight=pt_control_weight(mask,pb_read_float(target+4),pb_read_float(pt_batch_proprio+index*28+4));weight=pt_return_control_weight(weight,pb_read_float(target+8),training,pt_return_weight_milli);weight=pt_contact_control_weight(weight,pb_read_float(pt_batch_proprio+index*28+20),training,pt_contact_weight_milli);
        weights=f64_add(weights,weight);valid=f64_add(valid,mask);let phase_mask=pb_read_float(pt_batch_phase_masks+index*4);phase_valid=f64_add(phase_valid,phase_mask);if f64_gt(pb_read_float(target+8),0) {phase_positive=f64_add(phase_positive,phase_mask);}else {phase_negative=f64_add(phase_negative,phase_mask);}if pt_event_aux {event_weights=f64_add(event_weights,pt_event_weight(pt_batch_targets,index,pt_batch));}if pt_pose_aux {pose_valid=f64_add(pose_valid,pb_read_float(pt_batch_pose+index*20+16));}if pt_target_aux || pt_heat_aux {let target_mask=pb_read_float(pt_batch_target_positions+index*12+8);if f64_gt(target_mask,0) {target_valid=f64_add(target_valid,target_mask);}else if f64_lt(target_mask,0) {target_absent=f64_add(target_absent,PB_ONE);}}index=index+1;
    }
    vp_require(f64_gt(weights,0) && f64_gt(valid,0) && f64_gt(phase_valid,0),"empty training batch");if pt_heat_aux {pb_zero(pt_target_seed,pt_batch*pt_length*pt_target_width*4);}let loss=0;t=0;
    while t<pt_length {
        let prediction=pt_prediction+t*action_bytes;let phase_prediction=pt_phase_prediction+t*pt_batch*4;let action_seed=pt_action_seed+t*action_bytes;let phase_seed=pt_phase_seed+t*pt_batch*4;let b=0;
        while b<pt_batch {
            let target=pt_batch_targets+(t*pt_batch+b)*16;let mask=pb_read_float(target+12);let weight=pt_control_weight(mask,pb_read_float(target+4),pb_read_float(pt_batch_proprio+(t*pt_batch+b)*28+4));weight=pt_return_control_weight(weight,pb_read_float(target+8),training,pt_return_weight_milli);weight=pt_contact_control_weight(weight,pb_read_float(pt_batch_proprio+(t*pt_batch+b)*28+20),training,pt_contact_weight_milli);
            if pt_action_width==7 {loss=f64_add(loss,pt_categorical_loss(prediction+b*28,target,mask,f64_div(weight,weights),action_seed+b*28));}else {let axis=0;while axis<2 {
                let delta=f64_sub(pb_read_float(prediction+(b*2+axis)*4),pb_read_float(target+axis*4));let scale=PB_ONE;if !axis {scale=0x4020000000000000;}
                let weighted=f64_div(f64_mul(weight,scale),weights);loss=f64_add(loss,f64_mul(f64_mul(delta,delta),weighted));
                pb_put32(action_seed+(b*2+axis)*4,pb_f64_to_f32(f64_mul(0x4000000000000000,f64_mul(delta,weighted))));axis=axis+1;
            }}
            let logit=pb_read_float(phase_prediction+b*4);let label=pb_read_float(target+8);let scale=pt_phase_scale(pb_read_float(pt_batch_phase_masks+(t*pt_batch+b)*4),label,phase_valid,phase_positive,phase_negative,pt_balanced_phase && training);
            let exp=f64_exp(pb_neg(f64_magnitude(logit)));let positive=pb_fmax(logit,0);
            loss=f64_add(loss,f64_mul(scale,f64_add(f64_sub(positive,f64_mul(logit,label)),pt_log1p(exp))));
            let sigmoid=f64_div(PB_ONE,f64_add(PB_ONE,exp));if f64_lt(logit,0) {sigmoid=f64_mul(exp,sigmoid);}
            pb_put32(phase_seed+b*4,pb_f64_to_f32(f64_mul(scale,f64_sub(sigmoid,label))));
            if pt_event_aux {let index=t*pt_batch+b;let weight=0;if event_weights {weight=f64_div(pt_event_weight(pt_batch_targets,index,pt_batch),event_weights);}loss=f64_add(loss,pt_binary_loss(pb_read_float(pt_event_prediction+index*4),pt_event_label(pt_batch_targets,index,pt_batch),weight,pt_event_seed+index*4));}
            if pt_pose_aux {let index=t*pt_batch+b;let target_pose=pt_batch_pose+index*20;let weight=0;if pose_valid {weight=f64_div(pb_read_float(target_pose+16),f64_mul(pose_valid,f64_from_i64(4)));}loss=f64_add(loss,pt_pose_loss(pt_pose_prediction+index*16,target_pose,weight,pt_pose_seed+index*16));}
            if pt_target_aux {let index=t*pt_batch+b;let target_position=pt_batch_target_positions+index*12;let weight=0;if target_valid {weight=f64_div(pb_read_float(target_position+8),f64_mul(target_valid,f64_from_i64(2)));}loss=f64_add(loss,pt_target_loss(pt_target_prediction+index*8,target_position,weight,pt_target_seed+index*8));}
            if pt_heat_aux {let index=t*pt_batch+b;let target_position=pt_batch_target_positions+index*12;let target_mask=pb_read_float(target_position+8);let weight=0;if f64_gt(target_mask,0) {weight=f64_div(PB_ONE,target_valid);if target_absent {weight=f64_mul(weight,vc_number(1,2));}loss=f64_add(loss,pt_heat_loss_sized(pt_target_prediction+index*1600,target_position,weight,pt_target_seed+index*1600,pt_image_side));}else if f64_lt(target_mask,0) {weight=f64_div(PB_ONE,target_absent);if target_valid {weight=f64_mul(weight,vc_number(1,2));}loss=f64_add(loss,pt_heat_absence_loss(pt_target_prediction+index*1600,index,weight,pt_target_seed+index*1600));}}b=b+1;
        }
        t=t+1;
    }
    if pt_reversal_milli && training {let pairs=0;index=pt_batch;while index<pt_batch*pt_length {if pt_reversal_pair(pt_batch_targets+(index-pt_batch)*16,pt_batch_targets+index*16) {pairs=pairs+1;}index=index+1;}
        if pairs {let weight=f64_div(vc_number(pt_reversal_milli,1000),f64_from_i64(pairs));index=pt_batch;while index<pt_batch*pt_length {let previous=index-pt_batch;
            if pt_reversal_pair(pt_batch_targets+previous*16,pt_batch_targets+index*16) {loss=f64_add(loss,pt_reversal_loss(pt_prediction+previous*28,pt_prediction+index*28,weight,pt_action_seed+previous*28,pt_action_seed+index*28,pt_reversal_scratch));}index=index+1;}}
    }
    if pt_phase_consistency_milli && training {let pairs=0;index=pt_batch;while index<pt_batch*pt_length {let previous=index-pt_batch;if pt_phase_consistency_pair(pt_batch_targets+previous*16,pt_batch_targets+index*16,pt_batch_phase_masks+previous*4,pt_batch_phase_masks+index*4) {pairs=pairs+1;}index=index+1;}
        if pairs {let weight=f64_div(vc_number(pt_phase_consistency_milli,1000),f64_from_i64(pairs));index=pt_batch;while index<pt_batch*pt_length {let previous=index-pt_batch;
            if pt_phase_consistency_pair(pt_batch_targets+previous*16,pt_batch_targets+index*16,pt_batch_phase_masks+previous*4,pt_batch_phase_masks+index*4) {loss=f64_add(loss,pt_phase_consistency_loss(pb_read_float(pt_phase_prediction+previous*4),pb_read_float(pt_phase_prediction+index*4),weight,pt_phase_seed+previous*4,pt_phase_seed+index*4));}index=index+1;}}
    }
    vp_require(f64_is_finite(loss),"nonfinite training loss");if training {
        t=0;while t<steps {vp_check(device_upload_async(pt_gradient(vp_at(pt_actions,t)),pt_action_seed+t*action_bytes,action_bytes*span,vp_stream));vp_check(device_upload_async(pt_gradient(vp_at(pt_phases,t)),pt_phase_seed+t*pt_batch*4,pt_batch*4*span,vp_stream));if pt_event_aux {vp_check(device_upload_async(pt_gradient(vp_at(pt_events,t)),pt_event_seed+t*pt_batch*4,pt_batch*4,vp_stream));}if pt_pose_aux {vp_check(device_upload_async(pt_gradient(vp_at(pt_poses,t)),pt_pose_seed+t*pt_batch*16,pt_batch*16,vp_stream));}if pt_target_aux || pt_heat_aux {let size=pt_batch*pt_target_width*4;vp_check(device_upload_async(pt_gradient(vp_at(pt_target_predictions,t)),pt_target_seed+t*size,size,vp_stream));}t=t+1;}
        vp_check(device_stream_wait(vp_stream));pt_step_launch();pt_prefetch();pt_last_norm=pt_step_finish(rate);
    }return loss;
}
fn pt_order_file(path,order,count) {
    let fd=syscall(2,path,577,420,0,0,0);vp_require(fd>=0 && !pl_write(fd,order,count*8),"cannot record training split/order");return syscall(3,fd,0,0,0,0,0);
}
fn pt_save_epoch(output,epoch) {
    // The standalone trainer initializes its own host services. Keep filename
    // construction on the same native builder path as the other checkpoints.
    let name=alloc(64);let b=alloc(32);pl_builder(b,name,64);pl_text(b,"epoch-");pl_int(b,epoch);pl_text(b,".bin");pt_save(vp_path(output,name),0);
    syscall(11,name,64,0,0,0,0);syscall(11,b,32,0,0,0,0);return 0;
}
fn pt_log_epoch(fd,epoch,training,validation,best,milliseconds) {
    let out=alloc(1024);let builder=alloc(32);pl_builder(builder,out,1024);
    pl_text(builder,"{\"epoch\":");pl_int(builder,epoch);pl_text(builder,",\"trainingLoss\":");pl_float(builder,training);
    pl_text(builder,",\"validationLoss\":");pl_float(builder,validation);pl_text(builder,",\"selected\":");pl_text(builder,"false");
    if best {store64(builder+8,load64(builder+8)-5);pl_text(builder,"true");}
    pl_text(builder,",\"optimizerSteps\":");pl_int(builder,pt_adam_steps);pl_text(builder,",\"gradientNorm\":");pl_float(builder,pt_last_norm);
    pl_text(builder,",\"elapsedMilliseconds\":");pl_int(builder,milliseconds);if pt_feedback_drop_milli {pl_text(builder,",\"driveFeedbackDroppedSequences\":");pl_int(builder,pt_feedback_dropped_sequences);}if pt_mirror_augment {pl_text(builder,",\"mirroredTrainingSequences\":");pl_int(builder,pt_mirrored_sequences);}if pt_focus_copies {pl_text(builder,",\"focusHistory\":");pl_int(builder,pt_focus_history);pl_text(builder,",\"focusCopiesPerEpoch\":");pl_int(builder,pt_focus_copies);}if pt_max_optimizer_steps {pl_text(builder,",\"maxOptimizerSteps\":");pl_int(builder,pt_max_optimizer_steps);}pl_text(builder,"}\n");
    vp_require(!load64(builder+24) && !pl_write(fd,out,load64(builder+8)),"cannot record training curve");pl_write(1,out,load64(builder+8));
    syscall(11,out,1024,0,0,0,0);syscall(11,builder,32,0,0,0,0);return 0;
}
fn main(argc,argv) {
    if !pl_init() || argc<10 || argc>44 {pl_print(2,"train WEIGHTS SHA KERNELS DATA OUTPUT EPOCHS BATCH LR_MICROS SEED [--random] [--categorical] [--phase-gated] [--event-aux] [--memory-pose DIRECTORY] [--target-position DIRECTORY|--target-heatmap DIRECTORY] [--heat-actor] [--heat-stop-gradient] [--heat-absence] [--phase-from-valid] [--mirror-augment] [--checkpoint-every EPOCHS] [--image-128] [--stop-weight-one] [--large-model] [--focus-history INDEX --focus-copies COUNT] [--max-optimizer-steps COUNT] [--reversal-penalty-milli WEIGHT] [--phase-consistency-milli WEIGHT] [--balanced-phase] [--return-weight-milli WEIGHT] [--contact-weight-milli WEIGHT] [--drop-drive-feedback-milli RATE]\n");return 2;}
    let output=load64(argv+40);let epochs=pl_integer(load64(argv+48),pl_size(load64(argv+48)));vp_require(!pl_bad_number && epochs>=0 && epochs<=10000,"invalid epoch count");
    pt_batch=pl_integer(load64(argv+56),pl_size(load64(argv+56)));vp_require(!pl_bad_number && pt_batch>=1 && pt_batch<=8,"invalid batch size");
    let micros=pl_integer(load64(argv+64),pl_size(load64(argv+64)));vp_require(!pl_bad_number && micros>=1 && micros<=10000,"invalid learning rate");
    let seed=pl_integer(load64(argv+72),pl_size(load64(argv+72)));vp_require(!pl_bad_number && seed>=0 && seed<=2147483647,"invalid random seed");pt_rng=seed;
    let option=10;let categorical_option=0;while option<argc {let flag=load64(argv+option*8);if pl_equal(flag,"--drop-drive-feedback-milli") {vp_require(!pt_feedback_drop_milli && option+1<argc,"missing or duplicate drive feedback drop rate");option=option+1;let value=load64(argv+option*8);pt_feedback_drop_milli=pl_integer(value,pl_size(value));vp_require(!pl_bad_number && pt_feedback_drop_milli>=1 && pt_feedback_drop_milli<=1000,"invalid drive feedback drop rate");}else if pl_equal(flag,"--contact-weight-milli") {vp_require(!pt_contact_weight_milli && option+1<argc,"missing or duplicate contact control weight");option=option+1;let value=load64(argv+option*8);pt_contact_weight_milli=pl_integer(value,pl_size(value));vp_require(!pl_bad_number && pt_contact_weight_milli>=1000 && pt_contact_weight_milli<=10000,"invalid contact control weight");}else if pl_equal(flag,"--return-weight-milli") {vp_require(!pt_return_weight_milli && option+1<argc,"missing or duplicate return control weight");option=option+1;let value=load64(argv+option*8);pt_return_weight_milli=pl_integer(value,pl_size(value));vp_require(!pl_bad_number && pt_return_weight_milli>=1000 && pt_return_weight_milli<=10000,"invalid return control weight");}else if pl_equal(flag,"--balanced-phase") {vp_require(!pt_balanced_phase,"duplicate balanced phase option");pt_balanced_phase=1;}else if pl_equal(flag,"--phase-consistency-milli") {vp_require(!pt_phase_consistency_milli && option+1<argc,"missing or duplicate phase consistency penalty");option=option+1;let value=load64(argv+option*8);pt_phase_consistency_milli=pl_integer(value,pl_size(value));vp_require(!pl_bad_number && pt_phase_consistency_milli>=1 && pt_phase_consistency_milli<=10000,"invalid phase consistency penalty");}else if pl_equal(flag,"--reversal-penalty-milli") {vp_require(!pt_reversal_milli && option+1<argc,"missing or duplicate reversal penalty");option=option+1;let value=load64(argv+option*8);pt_reversal_milli=pl_integer(value,pl_size(value));vp_require(!pl_bad_number && pt_reversal_milli>=1 && pt_reversal_milli<=10000,"invalid reversal penalty");}else if pl_equal(flag,"--max-optimizer-steps") {vp_require(!pt_max_optimizer_steps && option+1<argc,"missing or duplicate optimizer step limit");option=option+1;let value=load64(argv+option*8);pt_max_optimizer_steps=pl_integer(value,pl_size(value));vp_require(!pl_bad_number && pt_max_optimizer_steps>=1 && pt_max_optimizer_steps<=100000000,"invalid optimizer step limit");}else if pl_equal(flag,"--focus-history") || pl_equal(flag,"--focus-copies") {vp_require(option+1<argc,"missing focus option value");option=option+1;let value=load64(argv+option*8);let n=pl_integer(value,pl_size(value));vp_require(!pl_bad_number && n>=0 && n<=1024,"invalid focus option value");if pl_equal(flag,"--focus-history") {vp_require(pt_focus_history<0,"duplicate focus-history option");pt_focus_history=n;}else {vp_require(!pt_focus_copies && n>=1,"duplicate or invalid focus-copies option");pt_focus_copies=n;}}else if pl_equal(flag,"--large-model") {vp_require(!pt_large_option,"duplicate large-model option");pt_large_option=1;pt_memory_width=256;}else if pl_equal(flag,"--stop-weight-one") {vp_require(!pt_stop_weight_one,"duplicate stop weight option");pt_stop_weight_one=1;pt_stop_weight=PB_ONE;}else if pl_equal(flag,"--image-128") {vp_require(pt_image_side==84,"duplicate image resolution option");pt_image_side=128;pt_image_bytes=49152;}else if pl_equal(flag,"--random") {vp_require(!pt_scratch_init,"duplicate random initialization option");pt_scratch_init=1;}else if pl_equal(flag,"--categorical") {vp_require(!categorical_option,"duplicate categorical option");categorical_option=1;pt_action_width=7;}else if pl_equal(flag,"--phase-gated") {vp_require(!pt_phase_gate,"duplicate phase-gated option");pt_phase_gate=1;pt_action_width=7;}else if pl_equal(flag,"--event-aux") {vp_require(!pt_event_aux,"duplicate event auxiliary option");pt_event_aux=1;}else if pl_equal(flag,"--memory-pose") {vp_require(!pt_pose_directory && option+1<argc,"missing or duplicate memory-pose directory");option=option+1;pt_pose_directory=load64(argv+option*8);pt_pose_aux=1;}else if pl_equal(flag,"--target-position") || pl_equal(flag,"--target-heatmap") {vp_require(!pt_target_directory && option+1<argc,"missing or duplicate target-position directory");if pl_equal(flag,"--target-heatmap") {pt_heat_aux=1;}else {pt_target_aux=1;}option=option+1;pt_target_directory=load64(argv+option*8);}else if pl_equal(flag,"--heat-actor") {vp_require(!pt_heat_actor,"duplicate heat-actor option");pt_heat_actor=1;}else if pl_equal(flag,"--heat-stop-gradient") {vp_require(!pt_heat_stop_gradient,"duplicate heat-stop-gradient option");pt_heat_stop_gradient=1;}else if pl_equal(flag,"--heat-absence") {vp_require(!pt_heat_absence,"duplicate heat-absence option");pt_heat_absence=1;}else if pl_equal(flag,"--phase-from-valid") {vp_require(!pt_phase_from_valid,"duplicate phase supervision option");pt_phase_from_valid=1;}else if pl_equal(flag,"--mirror-augment") {vp_require(!pt_mirror_augment,"duplicate mirror augmentation option");pt_mirror_augment=1;}else if pl_equal(flag,"--checkpoint-every") {vp_require(!pt_checkpoint_every && option+1<argc,"missing or duplicate checkpoint interval");option=option+1;let value=load64(argv+option*8);pt_checkpoint_every=pl_integer(value,pl_size(value));vp_require(!pl_bad_number && pt_checkpoint_every>=1 && pt_checkpoint_every<=10000,"invalid checkpoint interval");}else {vp_require(0,"unknown training option");}option=option+1;}
    vp_require(!pt_heat_actor || (pt_heat_aux && pt_action_width==7 && (!pt_phase_gate || pt_memory_width==256)),"heat-actor phase gating requires large categorical target-heatmap training");
    vp_require(!pt_heat_stop_gradient || pt_heat_actor,"heat-stop-gradient requires a heat actor");
    vp_require(!pt_heat_absence || pt_heat_aux,"heat-absence requires target-heatmap training");
    vp_require(!pt_reversal_milli || pt_action_width==7,"reversal penalty requires categorical actions");
    vp_require(!pt_phase_consistency_milli || pt_phase_gate,"phase consistency requires a phase-gated policy");
    vp_require(!pt_balanced_phase || pt_phase_gate,"balanced phase loss requires a phase-gated policy");
    vp_require(pt_memory_width==128 || (pt_image_side==84 && pt_action_width==7 && pt_heat_actor && !pt_target_aux),"large model requires the 84x84 categorical heat actor");
    pm_rng=(seed^0x5a5a5a5a)&2147483647;pf_rng=(seed^0x36b19ad7)&2147483647;pt_data=pt_data_open(load64(argv+32));
    if pt_image_side==128 {vp_require(load64(pt_data)==load64("PVDAT128"),"128x128 training requires PVDAT128 data");pt_row_bytes=56;}else {pt_row_bytes=vd_row_bytes(pt_data);}vp_require(pt_row_bytes,"invalid visual demonstration data");let episodes=load64(pt_data+8);let training_count=load64(pt_data+16);pt_length=load64(pt_data+24);
    let episode_limit=256;if pt_image_side==84 {episode_limit=vd_episode_limit(pt_data);}vp_require(episodes>=2 && episodes<=episode_limit && training_count>=1 && training_count<episodes && pt_length>=1 && pt_length<=512 && pt_batch*pt_length<=1024,"invalid demonstration dimensions or batch sequence exceeds 1024 frames");
    vp_require((pt_focus_history<0 && !pt_focus_copies) || (pt_focus_history>=0 && pt_focus_history<training_count && pt_focus_copies>=1 && pt_focus_copies<=training_count),"focus requires a fitting history and a valid copy count");
    pt_record_size=pt_length*(pt_image_bytes+pt_row_bytes);vp_require(pt_data_size==32+episodes*pt_record_size,"truncated demonstration data");
    vp_require(pt_image_side==84 || !pt_pose_aux,"128x128 memory-pose supervision is not yet supported");
    if pt_pose_aux || pt_target_aux || pt_heat_aux {vc_init(argc,argv);if pt_pose_aux {pt_pose_open(pt_pose_directory,pt_data,pt_data_size,pt_row_bytes);}if pt_target_aux || pt_heat_aux {pt_target_open_with_image(pt_target_directory,pt_data,pt_data_size,pt_row_bytes,pt_image_bytes);}}
    // Longer unrolled GRU episodes need more nodes than detector inference.
    vp_graph_limit=65536;vp_init(load64(argv+24),2,0);vp_checkpoint_open(load64(argv+8),load64(argv+16));let checkpoint_index=0;while checkpoint_index<load64(vp_checkpoint+8) {vp_require(pt_heat_actor || !pl_equal(vp_checkpoint+32+checkpoint_index*256,"visual.merge.weight_T"),"continuing a heat actor requires --heat-actor and target supervision");checkpoint_index=checkpoint_index+1;}pl_print(1,"Building native training graph.\n");
    pt_model(pt_batch,pt_length);if pt_action_width==7 {pt_rng=seed;}pl_print(1,"Preparing native backward graph.\n");let parameters=pt_prepare(load64(argv+24));pt_batch_open();pt_check_rows(episodes);pl_print(1,"Native training graphs ready.\n");
    let order=alloc(episodes*8);let i=0;while i<episodes {store64(order+i*8,i);i=i+1;}
    let curve=syscall(2,vp_path(output,"curves.jsonl"),577,420,0,0,0);vp_require(curve>=0,"cannot create training curve");
    let rate=f64_div(f64_from_i64(micros),0x412e848000000000);let started=pl_now();let best=0x7ff0000000000000;let epoch=0;
    pt_save(vp_path(output,"initial.bin"),0);pt_batch_load(order,0,pb_min(pt_batch,training_count));let initial=pt_loss(0,rate);
    let repeated=pt_loss(0,rate);vp_require(f64_lt(f64_magnitude(f64_sub(initial,repeated)),0x3eb0c6f7a0b5ed8d),"initial forward is not repeatable");
    pt_batch_load(order,0,pb_min(pt_batch,training_count));repeated=pt_loss(0,rate);
    vp_require(f64_lt(f64_magnitude(f64_sub(initial,repeated)),0x3eb0c6f7a0b5ed8d),"reloading the same batch changes the forward pass");
    let initial_validation=0;let initial_batches=0;i=training_count;
    while i<episodes {pt_batch_load(order,i,pb_min(pt_batch,episodes-i));initial_validation=f64_add(initial_validation,pt_loss(0,rate));initial_batches=initial_batches+1;i=i+pt_batch;}
    // Warm starts are valid candidates too: continuation may worsen held-out
    // loss even when fitting loss improves. Keep the initial checkpoint until
    // an optimizer update actually improves validation.
    best=f64_div(initial_validation,f64_from_i64(initial_batches));pt_save(vp_path(output,"weights.bin"),0);
    pt_log_epoch(curve,0,initial,best,1,pl_now()-started);
    while epoch<epochs && (!pt_max_optimizer_steps || pt_adam_steps<pt_max_optimizer_steps) {
        // Rebuild the fitting permutation before replacing entries, so omitted
        // histories are not permanently lost in later epochs. Validation is
        // never resampled or changed.
        if pt_focus_copies {i=0;while i<training_count {store64(order+i*8,i);i=i+1;}}
        i=training_count;while i>1 {i=i-1;let j=pt_random()%(i+1);let a=load64(order+i*8);store64(order+i*8,load64(order+j*8));store64(order+j*8,a);}
        if pt_focus_copies {let location=0;while location<training_count && load64(order+location*8)!=pt_focus_history {location=location+1;}vp_require(location<training_count,"focused history missing from permutation");let first=load64(order);store64(order,pt_focus_history);store64(order+location*8,first);
            i=0;while i<pt_focus_copies {store64(order+i*8,pt_focus_history);i=i+1;}i=training_count;while i>1 {i=i-1;let j=pt_random()%(i+1);let a=load64(order+i*8);store64(order+i*8,load64(order+j*8));store64(order+j*8,a);}}
        let total=0;let batches=0;let start=0;pt_mirror_active=pt_mirror_augment;pt_feedback_drop_active=pt_feedback_drop_milli;
        while start<training_count && (!pt_max_optimizer_steps || pt_adam_steps<pt_max_optimizer_steps) {let count=pb_min(pt_batch,training_count-start);if pt_prefetched!=start {pt_batch_fill(order,start,count);}pt_prefetched=-1;pt_batch_send();
            let next=start+pt_batch;if next<training_count && (!pt_max_optimizer_steps || pt_adam_steps+1<pt_max_optimizer_steps) {pt_prefetch_order=order;pt_prefetch_start=next;pt_prefetch_count=pb_min(pt_batch,training_count-next);}
            if !pt_adam_steps {pt_order_file(vp_path(output,"first-order.bin"),order,episodes);if pt_mirror_augment {pt_order_file(vp_path(output,"first-mirror-mask.bin"),pt_mirror_mask_host,1);}if pt_feedback_drop_milli {pt_order_file(vp_path(output,"first-feedback-drop-mask.bin"),pt_feedback_drop_mask_host,1);}}
            total=f64_add(total,pt_loss(1,rate));batches=batches+1;
            if pt_adam_steps==1 {pt_save(vp_path(output,"first-after.bin"),0);pt_save(vp_path(output,"first-gradients.bin"),1);}
            start=start+pt_batch;
        }
        let validation=0;let validation_batches=0;start=training_count;pt_mirror_active=0;pt_feedback_drop_active=0;
        while start<episodes {pt_batch_load(order,start,pb_min(pt_batch,episodes-start));validation=f64_add(validation,pt_loss(0,rate));validation_batches=validation_batches+1;start=start+pt_batch;}
        if pt_feedback_drop_milli {pt_order_file(vp_path(output,"last-validation-feedback-drop-mask.bin"),pt_feedback_drop_mask_host,1);}
        validation=f64_div(validation,f64_from_i64(validation_batches));let selected=f64_lt(validation,best);
        if selected {best=validation;pt_save(vp_path(output,"weights.bin"),0);}
        epoch=epoch+1;if pt_checkpoint_every && !(epoch%pt_checkpoint_every) {pt_save_epoch(output,epoch);}pt_log_epoch(curve,epoch,f64_div(total,f64_from_i64(batches)),validation,selected,pl_now()-started);
    }
    pt_save(vp_path(output,"last.bin"),0);pt_order_file(vp_path(output,"final-order.bin"),order,episodes);syscall(3,curve,0,0,0,0,0);
    pl_print(1,"Native Flexscript CNN/GRU training complete. Parameters: ");let b=alloc(32);let s=alloc(64);pl_builder(b,s,64);pl_int(b,parameters);pl_text(b,"\n");pl_write(1,s,load64(b+8));return 0;
}
