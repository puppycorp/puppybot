// Native visual-policy training support. Shared Pup forward kernels, explicit
// reverse graph, full-sequence recurrent gradients and FP32 Adam on CUDA.
import "../ml/runtime.flex";
import "action-weight.flex";
global pt_tensors=0;
global pt_split=0;
global pt_recurrence_function=0;
global pt_registers_function=0;
// Categorical policies without auxiliary heads batch the input projection and
// heads over all steps and run the recurrence as one kernel.
global pt_fused=0;
global pt_parameters=0;
global pt_backward=0;
global pt_function=0;
global pt_gradient_arena=0;
global pt_gradient_count=0;
global pt_zero=0;
global pt_norm=0;
global pt_norm_host=0;
global pt_norm_device=0;
global pt_norm_count=0;
global pt_optimizer=0;
global pt_optimizer_meta=0;
global pt_optimizer_host=0;
global pt_adam_steps=0;
global pt_beta1=0x3ff0000000000000;
global pt_beta2=0x3ff0000000000000;
global pt_rng=7;
global pt_scratch_init=0;
global pt_images=0;
global pt_image_side=84;
global pt_image_bytes=21168;
global pt_memory_width=128;
global pt_proprio=0;
global pt_actions=0;
global pt_phases=0;
global pt_memories=0;
global pt_action_width=2;
global pt_phase_gate=0;
global pt_event_aux=0;
global pt_events=0;
global pt_pose_aux=0;
global pt_poses=0;
global pt_target_aux=0;
global pt_heat_aux=0;
global pt_heat_actor=0;
global pt_heat_stop_gradient=0;
global pt_reversal_milli=0;
global pt_detached_heat=0;
global pt_target_predictions=0;

fn pup_model_input(name) {return 0;}
// Training submits work on a nonblocking stream. Pageable default-stream
// uploads can return after staging, before DMA completes; order copies on the
// same stream and wait before host seed buffers are reused or unmapped.
fn pt_upload(out,data,size) {vp_check(device_upload_async(out,data,size,vp_stream));return vp_check(device_stream_wait(vp_stream));}
fn pt_random() {pt_rng=(pt_rng*1103515245+12345)&2147483647;return pt_rng;}
fn pt_track(t) {h_add(pt_tensors,t);return t;}
fn pt_weight(name,shape) {
    let i=0;while i<load64(pt_parameters) {let p=vp_at(pt_parameters,i);if pl_equal(load64(p),name) {return load64(p+8);}i=i+1;}
    let t=0;let missing=1;let source=name;i=0;while i<load64(vp_checkpoint+8) {if pl_equal(vp_checkpoint+32+i*256,name) {missing=0;}i=i+1;}
    if missing && pt_phase_gate {let alias=0;if pl_equal(name,"actor_search.weight_T") || pl_equal(name,"actor_return.weight_T") {alias="actor7.weight_T";}if pl_equal(name,"actor_search.bias") || pl_equal(name,"actor_return.bias") {alias="actor7.bias";}
        if alias {i=0;while i<load64(vp_checkpoint+8) {if pl_equal(vp_checkpoint+32+i*256,alias) {missing=0;source=alias;}i=i+1;}}
    }
    vp_require(!missing || pl_starts(name,"critic.") || (pt_heat_actor && pl_starts(name,"visual.merge.")) || (pt_action_width==7 && pl_starts(name,"actor7.")) || (pt_phase_gate && (pl_starts(name,"actor_search.") || pl_starts(name,"actor_return."))) || pt_scratch_init,"native training checkpoint is missing a parameter");
    if pt_scratch_init || missing {
        t=vp_tensor(shape,0,0,0);let host=alloc(load64(t+8)*4);let fan=vp_count(shape);if load64(shape)>1 {fan=fan/load64(shape+8);}
        if vp_rank(t)==2 {fan=vp_dim(t,0);}let scale=f64_div(PB_ONE,f64_sqrt(f64_from_i64(fan)));i=0;
        while i<load64(t+8) {let value=0;if load64(shape)>1 && !(pt_heat_actor && pl_starts(name,"visual.merge.")) {value=f64_mul(f64_sub(f64_div(f64_from_i64(pt_random()),0x41d0000000000000),PB_ONE),scale);}
            if (pl_equal(name,"actor.bias") || pl_equal(name,"actor7.bias") || pl_equal(name,"actor_search.bias") || pl_equal(name,"actor_return.bias")) && i==1 {value=0x3fd3333333333333;}if pl_equal(name,"critic.event.bias") {value=0xc010000000000000;}pb_put32(host+i*4,pb_f64_to_f32(value));i=i+1;}
        pt_upload(load64(t),host,load64(t+8)*4);syscall(11,host,load64(t+8)*4,0,0,0,0);
    }else {t=vp_parameter(source,shape);}
    let p=alloc(32);store64(p,vp_copy(name));store64(p+8,t);h_add(pt_parameters,p);return pt_track(t);
}
fn pt_binary(op,a,b) {return pt_track(pup_binary(op,a,b));}
fn pt_slice(a,axis,start,length) {return pt_track(pup_slice(a,axis,start,length));}
fn pt_sigmoid(a) {return pt_track(pup_sigmoid(a));}
fn pt_join(a,b,axis) {return pt_track(pup_concat(a,b,axis));}
fn pt_matmul(a,b) {return pt_track(pup_batch_matmul(a,b));}
fn pt_dense(a,name,width,channels) {
    let w=pt_weight(vp_suffix(name,".weight_T"),pup_shape(2,width,channels,1,1));
    let b=pt_weight(vp_suffix(name,".bias"),pup_shape(1,channels,1,1,1));return pt_binary(3,pt_matmul(a,w),b);
}
fn pt_conv(a,name,channels,k,stride) {
    let cin=vp_dim(a,1);let t=pt_track(vp_tensor(pup_shape(4,vp_dim(a,0),channels,(vp_dim(a,2)-k)/stride+1,(vp_dim(a,3)-k)/stride+1),12,a,0));
    let w=pt_weight(vp_suffix(name,".weight"),pup_shape(4,channels,cin,k,k));
    let b=pt_weight(vp_suffix(name,".bias"),pup_shape(1,channels,1,1,1));
    store64(t+48,load64(w));store64(t+56,load64(b));store64(t+64,k);store64(t+72,stride);store64(t+88,1);return t;
}
fn pt_view(t,row,rows) {let columns=vp_dim(t,1);let v=alloc(128);pb_copy(v,t,128);store64(v,load64(t)+row*columns*4);store64(v+8,rows*columns);store64(v+16,pup_shape(2,rows,columns,1,1));store64(v+24,0);return v;}
fn pt_recurrence(ix,wh,bh,batch,width,length) {
    // 128 units and at most two rows keep the recurrent weights in registers (op 30).
    let op=31;let threads=pb_min(1024,batch*width*3);if width==128 && batch<=2 {op=30;threads=384;}
    let t=pt_track(vp_tensor(pup_shape(2,length*batch,width,1,1),op,ix,0));store64(t+48,load64(wh));store64(t+56,load64(bh));store64(t+64,batch);store64(t+72,width);store64(t+80,length);store64(t+88,threads);
    // Gates saved per step for the backward scan: r, z, s and hn.
    store64(t+40,vp_tensor(pup_shape(2,length*batch,width*4,1,1),0,0,0));return t;
}
fn pt_model(batch,length) {
    // The blocked convolution needs output channels in multiples of eight; heat maps have one.
    vp_binary_kernel="binary-train";if !pt_heat_aux {vp_convolution_kernel="convolution-train";vp_convolution_block=8;}
    pt_tensors=h_vec();pt_parameters=h_vec();pt_actions=h_vec();pt_phases=h_vec();pt_memories=h_vec();pt_events=h_vec();pt_poses=h_vec();pt_target_predictions=h_vec();if pt_heat_stop_gradient {pt_detached_heat=h_vec();}
    pt_images=vp_tensor(pup_shape(4,length*batch,3,pt_image_side,pt_image_side),0,0,0);
    pt_proprio=vp_tensor(pup_shape(3,length,batch,7,1),0,0,0);
    let zero=pup_scalar(0);let one=pup_scalar(0x3f800000);let two=pup_scalar(0x40000000);
    let width=pt_memory_width;let first_channels=16;let second_channels=32;let third_channels=32;let flattened=1568;
    if width==256 {first_channels=32;second_channels=64;third_channels=192;flattened=9408;}
    let first_kernel=8;let first_stride=4;if pt_image_side==128 {first_kernel=12;first_stride=6;}
    let encoded=pt_binary(7,pt_conv(pt_images,"encoder.0",first_channels,first_kernel,first_stride),zero);let early=encoded;let heat=0;
    encoded=pt_binary(7,pt_conv(encoded,"encoder.2",second_channels,4,2),zero);
    encoded=pt_binary(7,pt_conv(encoded,"encoder.4",third_channels,3,1),zero);
    encoded=pup_reshape(encoded,pup_shape(2,length*batch,flattened,1,1));
    encoded=pt_binary(7,pt_dense(encoded,"encoder.7",flattened,width),zero);
    encoded=pup_reshape(encoded,pup_shape(3,length,batch,width,1));
    let hidden=vp_tensor(pup_shape(2,batch,width,1,1),0,0,0);let zeros=alloc(batch*width*4);pt_upload(load64(hidden),zeros,batch*width*4);
    let wi=pt_weight("memory.weight_ih_T",pup_shape(2,width+7,width*3,1,1));let bi=pt_weight("memory.bias_ih",pup_shape(1,width*3,1,1,1));
    let wh=pt_weight("memory.weight_hh_T",pup_shape(2,width,width*3,1,1));let bh=pt_weight("memory.bias_hh",pup_shape(1,width*3,1,1,1));
    pt_fused=pt_action_width==7 && !pt_phase_gate && !pt_event_aux && !pt_pose_aux && !pt_target_aux && !pt_heat_aux && !pt_heat_actor && batch*width*44<=49152 && !(width%8);
    if pt_fused {
        let combined=pt_join(pup_reshape(encoded,pup_shape(2,length*batch,width,1,1)),pup_reshape(pt_proprio,pup_shape(2,length*batch,7,1,1)),1);
        let states=pt_recurrence(pt_binary(3,pt_matmul(combined,wi),bi),wh,bh,batch,width,length);
        let actions=pt_dense(states,"actor7",width,7);let phases=pt_dense(states,"critic",width,1);let step=0;
        while step<length {h_add(pt_memories,pt_view(states,step*batch,batch));h_add(pt_actions,pt_view(actions,step*batch,batch));h_add(pt_phases,pt_view(phases,step*batch,batch));step=step+1;}
    }
    let t=0;while !pt_fused && t<length {
        let features=pup_reshape(pt_slice(encoded,0,t,1),pup_shape(2,batch,width,1,1));
        // This training-only branch sees current camera features, before own
        // feedback or recurrent memory. Its labels never become actor inputs.
        if pt_event_aux {h_add(pt_events,pt_dense(features,"critic.event",width,1));}
        if pt_target_aux {h_add(pt_target_predictions,pt_dense(features,"critic.target",width,2));}
        if pt_heat_aux {if !heat {heat=pt_conv(early,"critic.heat",1,1,1);heat=pup_reshape(heat,pup_shape(3,length,batch,400,1));}h_add(pt_target_predictions,pup_reshape(pt_slice(heat,0,t,1),pup_shape(2,batch,400,1,1)));}
        if pt_heat_actor {let heat_features=vp_at(pt_target_predictions,t);if pt_heat_stop_gradient {let detached=alloc(128);pb_copy(detached,heat_features,128);h_add(pt_detached_heat,detached);heat_features=detached;}features=pt_binary(3,features,pt_dense(heat_features,"visual.merge",400,width));}
        let proprio=pup_reshape(pt_slice(pt_proprio,0,t,1),pup_shape(2,batch,7,1,1));
        let combined=pt_join(features,proprio,1);
        let ix=pt_binary(3,pt_matmul(combined,wi),bi);let hx=pt_binary(3,pt_matmul(hidden,wh),bh);
        let ir=pt_slice(ix,1,0,width);let iz=pt_slice(ix,1,width,width);let inn=pt_slice(ix,1,width*2,width);
        let hr=pt_slice(hx,1,0,width);let hz=pt_slice(hx,1,width,width);let hn=pt_slice(hx,1,width*2,width);
        let r=pt_sigmoid(pt_binary(3,ir,hr));let z=pt_sigmoid(pt_binary(3,iz,hz));
        let candidate=pt_binary(4,pt_binary(5,two,pt_sigmoid(pt_binary(5,two,pt_binary(3,inn,pt_binary(5,r,hn))))),one);
        hidden=pt_binary(3,pt_binary(5,pt_binary(4,one,z),candidate),pt_binary(5,z,hidden));
        h_add(pt_memories,hidden);
        // Training-only readout: its targets never enter recurrence or the actor.
        if pt_pose_aux {h_add(pt_poses,pt_dense(hidden,"critic.pose",width,4));}
        let action=0;let phase=0;if pt_phase_gate {phase=pt_dense(hidden,"critic",width,1);let probability=pt_sigmoid(phase);let search=pt_dense(hidden,"actor_search",width,7);let returning=pt_dense(hidden,"actor_return",width,7);action=pt_binary(3,pt_binary(5,pt_binary(4,one,probability),search),pt_binary(5,probability,returning));}
        else {if pt_action_width==7 {action=pt_dense(hidden,"actor7",width,7);}else {action=pt_binary(4,pt_binary(5,two,pt_sigmoid(pt_binary(5,two,pt_dense(hidden,"actor",width,2)))),one);}phase=pt_dense(hidden,"critic",width,1);}
        h_add(pt_actions,action);h_add(pt_phases,phase);t=t+1;
    }
    let inputs=h_vec();let entry=alloc(16);store64(entry,"images");store64(entry+8,pt_images);h_add(inputs,entry);
    entry=alloc(16);store64(entry,"proprio");store64(entry+8,pt_proprio);h_add(inputs,entry);
    let outputs=h_vec();h_add(outputs,vp_at(pt_actions,length-1));vp_check(device_synchronize());pup_finish(inputs,outputs);return 0;
}
fn pt_tensor_by_data(data) {
    let i=0;while i<load64(pt_tensors) {let t=vp_at(pt_tensors,i);if load64(t)==data {return t;}i=i+1;}return 0;
}
// Views address rows of a tracked tensor, so gradients resolve by address range.
fn pt_gradient(t) {
    if !t {return 0;}let i=0;if pt_heat_stop_gradient {while i<load64(pt_detached_heat) {if t==vp_at(pt_detached_heat,i) {return 0;}i=i+1;}}let target=load64(t);i=0;
    while i<load64(pt_tensors) {let u=vp_at(pt_tensors,i);if target>=load64(u) && target<load64(u)+load64(u+8)*4 {return pt_gradient_arena+load64(pt_optimizer_host+i*8)*4+target-load64(u);}i=i+1;}return 0;
}
fn pt_launch(input,output,count,mode,a,b,meta) {
    let values=alloc(88);let args=alloc(88);store64(values,input);store64(values+8,output);store64(values+16,count);
    store64(values+24,mode);store64(values+32,a);store64(values+40,b);store64(values+48,meta);
    let i=0;while i<11 {store64(args+i*8,values+i*8);i=i+1;}
    let job=alloc(24);store64(job,args);store64(job+8,device_config((count+127)/128,1,1,128,1,1,0,vp_stream));store64(job+16,pt_function);return job;
}
fn pt_dispatch(job) {return vp_check(device_dispatch(load64(job+16),load64(job+8),load64(job)));}
fn pt_backward_job(t,parent,role) {
    let gradient=pt_gradient(parent);if !gradient {return 0;}
    let a=load64(load64(t+32));let b=0;if load64(t+40) {b=load64(load64(t+40));}
    if load64(t+24)==24 {a=load64(t);}if load64(t+24)==12 {b=load64(t+48);}
    if load64(t+24)==29 && !role && vp_rank(load64(t+32))==2 && vp_rank(load64(t+40))==2 {let w=load64(t+40);let size=load64(w+8);let transposed=vp_buffer(size*4);
        h_add(pt_backward,pt_launch(0,transposed,size,113,load64(w),0,load64(t+96)));h_add(pt_backward,pt_launch(pt_gradient(t),gradient,load64(parent+8),112,0,transposed,load64(t+96)));return 0;}
    // Blocked input gradients need input channels in eights, blocked weight partials output channels.
    let unpadded=load64(t+24)==12 && !load64(t+80);
    if unpadded && !role && !(vp_dim(load64(t+32),1)%8) {h_add(pt_backward,pt_launch(pt_gradient(t),gradient,load64(parent+8)/8,114,a,b,load64(t+96)));return 0;}
    if unpadded && role==2 && !(vp_dim(t,1)%8) {let parts=pt_weight_parts(t);h_add(pt_backward,pt_launch(pt_gradient(t),pt_split,load64(parent+8)/8*parts,115,a,parts,load64(t+96)));h_add(pt_backward,pt_launch(pt_split,gradient,load64(parent+8),107,0,parts,load64(t+96)));return 0;}
    if load64(t+24)==12 && role>=2 {h_add(pt_backward,pt_launch(pt_gradient(t),pt_split,load64(parent+8)*64,106,a,role,load64(t+96)));h_add(pt_backward,pt_launch(pt_split,gradient,load64(parent+8),107,0,0,0));return 0;}
    h_add(pt_backward,pt_launch(pt_gradient(t),gradient,load64(parent+8),role,a,b,load64(t+96)));return 0;
}
// Blocked weight partials split the batch into enough slices for about 200k work items.
fn pt_weight_parts(t) {return pb_max(64,pb_min(vp_dim(load64(t+32),0),200000/(load64(pt_tensor_by_data(load64(t+48))+8)/8)));}
fn pt_recurrence_backward(t) {
    let input=pt_gradient(t);if !input {return 0;}let ix=load64(t+32);let output=pt_gradient(ix);vp_require(output,"recurrence input has no gradient");
    let batch=load64(t+64);let width=load64(t+72);let length=load64(t+80);let host=alloc(72);store64(host,batch);store64(host+8,width);store64(host+16,length);store64(host+24,load64(t+48));store64(host+32,load64(t+56));
    store64(host+40,vp_buffer(length*batch*width*12));let threads=load64(t+88);store64(host+48,vp_buffer(width*width*12));store64(host+56,threads);store64(host+64,load64(load64(t+40)));let meta=vp_buffer(72);pt_upload(meta,host,72);
    h_add(pt_backward,pt_launch(0,load64(host+48),width*width*3,111,load64(t+48),0,meta));
    let job=pt_launch(input,output,threads,108,load64(ix),load64(t),meta);store64(job+8,device_config(1,1,1,threads,1,1,batch*width*28,vp_stream));store64(job+16,pt_recurrence_function);if load64(t+24)==30 {store64(job+16,pt_registers_function);}h_add(pt_backward,job);
    let wh=pt_gradient(pt_tensor_by_data(load64(t+48)));let bh=pt_gradient(pt_tensor_by_data(load64(t+56)));
    if wh {h_add(pt_backward,pt_launch(0,wh,width*width*3,109,load64(t),0,meta));}if bh {h_add(pt_backward,pt_launch(0,bh,width*3,110,0,0,meta));}return 0;
}
fn pt_prepare(kernel_root) {
    pt_optimizer_host=alloc(load64(pt_tensors)*8);let i=0;
    while i<load64(pt_tensors) {store64(pt_optimizer_host+i*8,pt_gradient_count);pt_gradient_count=pt_gradient_count+load64(vp_at(pt_tensors,i)+8);i=i+1;}
    vp_require(pt_gradient_count<134217728,"training gradient arena exceeds 512 MiB");pt_gradient_arena=vp_buffer(pt_gradient_count*4);
    let image=vp_map(vp_path(kernel_root,"gradients.ptx"));let module=device_module(image);vp_require(module,device_error());syscall(11,image,vp_bytes,0,0,0,0);
    pt_function=device_function(module,"flex_kernel");vp_require(pt_function,device_error());
    if pt_fused {image=vp_map(vp_path(kernel_root,"recurrence-backward.ptx"));module=device_module(image);vp_require(module,device_error());syscall(11,image,vp_bytes,0,0,0,0);pt_recurrence_function=device_function(module,"flex_kernel");vp_require(pt_recurrence_function,device_error());
        image=vp_map(vp_path(kernel_root,"recurrence-registers-backward.ptx"));module=device_module(image);vp_require(module,device_error());syscall(11,image,vp_bytes,0,0,0,0);pt_registers_function=device_function(module,"flex_kernel");vp_require(pt_registers_function,device_error());}
    let split=0;i=0;while i<load64(vp_nodes) {let t=vp_at(vp_nodes,i);if load64(t+24)==12 {split=pb_max(split,load64(pt_tensor_by_data(load64(t+48))+8)*pt_weight_parts(t));}i=i+1;}if split {pt_split=vp_buffer(split*4);}
    pl_print(1,"Native gradient buffers allocated.\n");pt_zero=pt_launch(0,pt_gradient_arena,pt_gradient_count,100,0,0,0);pt_backward=h_vec();i=load64(vp_nodes);
    while i {i=i-1;let t=vp_at(vp_nodes,i);let op=load64(t+24);
        vp_require((op>=3 && op<=7) || op==12 || op==24 || op==25 || op==26 || op==29 || op==30 || op==31,"training operation has no backward implementation");
        if op==30 || op==31 {pt_recurrence_backward(t);}else {pt_backward_job(t,load64(t+32),0);if load64(t+40) {pt_backward_job(t,load64(t+40),1);}}
        if op==12 {pt_backward_job(t,pt_tensor_by_data(load64(t+48)),2);pt_backward_job(t,pt_tensor_by_data(load64(t+56)),3);}
    }
    pl_print(1,"Capturing native backward launches.\n");vp_check(device_capture_begin(vp_stream));i=0;while i<load64(pt_backward) {pt_dispatch(vp_at(pt_backward,i));i=i+1;}
    let graph=device_capture_end(vp_stream);vp_require(graph,device_error());pt_backward=device_graph_instance(graph);vp_require(pt_backward,device_error());vp_check(device_graph_close(graph));
    pl_print(1,"Native backward graph captured.\n");let total=0;i=0;while i<load64(pt_parameters) {total=total+load64(load64(vp_at(pt_parameters,i)+8)+8);i=i+1;}
    pt_norm=h_vec();pt_norm_device=vp_buffer((total/256+load64(pt_parameters))*4);pt_optimizer=h_vec();pt_optimizer_meta=vp_buffer(16);i=0;
    while i<load64(pt_parameters) {
        let p=vp_at(pt_parameters,i);let t=load64(p+8);let count=load64(t+8);let m=vp_buffer(count*4);let v=vp_buffer(count*4);
        store64(p+16,m);store64(p+24,v);pt_dispatch(pt_launch(0,m,count,100,0,0,0));pt_dispatch(pt_launch(0,v,count,100,0,0,0));
        h_add(pt_optimizer,pt_launch(pt_gradient(t),load64(t),count,102,m,v,pt_optimizer_meta));
        let norm_meta=alloc(8);store64(norm_meta,count);let device_meta=vp_buffer(8);pt_upload(device_meta,norm_meta,8);
        let chunks=(count+255)/256;h_add(pt_norm,pt_launch(pt_gradient(t),pt_norm_device+pt_norm_count*4,chunks,101,0,0,device_meta));pt_norm_count=pt_norm_count+chunks;i=i+1;
    }
    pt_norm_host=alloc(pt_norm_count*4);vp_check(device_stream_wait(vp_stream));return total;
}
fn pt_zero_grad() {pt_dispatch(pt_zero);return vp_check(device_stream_wait(vp_stream));}
// The backward pass is queued first, so the host can prepare other work before waiting on it.
fn pt_step_launch() {vp_check(device_graph_launch(pt_backward,vp_stream));let i=0;while i<load64(pt_norm) {pt_dispatch(vp_at(pt_norm,i));i=i+1;}return 0;}
fn pt_step_finish(rate) {
    vp_check(device_stream_wait(vp_stream));let i=0;
    let chunks=pt_norm_count;vp_check(device_download(pt_norm_host,pt_norm_device,chunks*4));let square=0;i=0;
    while i<chunks {square=f64_add(square,pb_read_float(pt_norm_host+i*4));i=i+1;}vp_require(f64_is_finite(square),"nonfinite training gradient");
    let norm=f64_sqrt(square);let scale=PB_ONE;if f64_gt(norm,PB_ONE) {scale=f64_div(PB_ONE,norm);}
    pt_beta1=f64_mul(pt_beta1,0x3feccccccccccccd);pt_beta2=f64_mul(pt_beta2,0x3feff7ced916872b);pt_adam_steps=pt_adam_steps+1;
    let meta=alloc(16);pb_put32(meta,pb_f64_to_f32(scale));pb_put32(meta+4,pb_f64_to_f32(f64_div(PB_ONE,f64_sub(PB_ONE,pt_beta1))));
    pb_put32(meta+8,pb_f64_to_f32(f64_div(PB_ONE,f64_sub(PB_ONE,pt_beta2))));pb_put32(meta+12,pb_f64_to_f32(rate));pt_upload(pt_optimizer_meta,meta,16);syscall(11,meta,16,0,0,0,0);
    i=0;while i<load64(pt_optimizer) {pt_dispatch(vp_at(pt_optimizer,i));i=i+1;}vp_check(device_stream_wait(vp_stream));return norm;
}
fn pt_step(rate) {pt_step_launch();return pt_step_finish(rate);}
fn pt_save(path,gradients) {
    let count=load64(pt_parameters);let bytes=0;let i=0;
    while i<count {bytes=bytes+load64(load64(vp_at(pt_parameters,i)+8)+8)*4;i=i+1;}
    let data=alloc(32+count*256+bytes);store64(data,0x3130303056505550);store64(data+8,count);store64(data+16,32+count*256);store64(data+24,bytes);
    let offset=0;i=0;while i<count {
        let p=vp_at(pt_parameters,i);let t=load64(p+8);let record=data+32+i*256;pb_copy(record,load64(p),pl_size(load64(p)));
        store64(record+192,vp_rank(t));store64(record+200,load64(t+8));store64(record+208,offset);let axis=0;
        while axis<4 {let dim=1;if axis<vp_rank(t) {dim=vp_dim(t,axis);}store64(record+216+axis*8,dim);axis=axis+1;}
        let source=load64(t);if gradients {source=pt_gradient(t);}vp_check(device_download(data+32+count*256+offset,source,load64(t+8)*4));offset=offset+load64(t+8)*4;i=i+1;
    }
    let temporary=vp_suffix(path,".tmp");let fd=syscall(2,temporary,577,420,0,0,0);vp_require(fd>=0 && !pl_write(fd,data,32+count*256+bytes),"cannot save native checkpoint");
    vp_require(!syscall(74,fd,0,0,0,0,0) && !syscall(3,fd,0,0,0,0,0) && !syscall(82,temporary,path,0,0,0,0),"cannot publish native checkpoint");
    syscall(11,data,32+count*256+bytes,0,0,0,0);return 0;
}
