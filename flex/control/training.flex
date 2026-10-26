// Native visual-policy training support. Shared Pup forward kernels, explicit
// reverse graph, full-sequence recurrent gradients and FP32 Adam on CUDA.
import "../ml/runtime.flex";
global pt_tensors=0;
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
global pt_proprio=0;
global pt_actions=0;
global pt_phases=0;

fn pup_model_input(name) {return 0;}
// Training submits work on a nonblocking stream. Pageable default-stream
// uploads can return after staging, before DMA completes; order copies on the
// same stream and wait before host seed buffers are reused or unmapped.
fn pt_upload(out,data,size) {vp_check(device_upload_async(out,data,size,vp_stream));return vp_check(device_stream_wait(vp_stream));}
fn pt_random() {pt_rng=(pt_rng*1103515245+12345)&2147483647;return pt_rng;}
fn pt_track(t) {h_add(pt_tensors,t);return t;}
fn pt_weight(name,shape) {
    let i=0;while i<load64(pt_parameters) {let p=vp_at(pt_parameters,i);if pl_equal(load64(p),name) {return load64(p+8);}i=i+1;}
    let t=0;let missing=1;i=0;while i<load64(vp_checkpoint+8) {if pl_equal(vp_checkpoint+32+i*256,name) {missing=0;}i=i+1;}
    vp_require(!missing || pl_starts(name,"critic.") || pt_scratch_init,"native training checkpoint is missing a parameter");
    if pt_scratch_init || missing {
        t=vp_tensor(shape,0,0,0);let host=alloc(load64(t+8)*4);let fan=vp_count(shape);if load64(shape)>1 {fan=fan/load64(shape+8);}
        if vp_rank(t)==2 {fan=vp_dim(t,0);}let scale=f64_div(PB_ONE,f64_sqrt(f64_from_i64(fan)));i=0;
        while i<load64(t+8) {let value=0;if load64(shape)>1 {value=f64_mul(f64_sub(f64_div(f64_from_i64(pt_random()),0x41d0000000000000),PB_ONE),scale);}
            if pl_equal(name,"actor.bias") && i==1 {value=0x3fd3333333333333;}pb_put32(host+i*4,pb_f64_to_f32(value));i=i+1;}
        pt_upload(load64(t),host,load64(t+8)*4);syscall(11,host,load64(t+8)*4,0,0,0,0);
    }else {t=vp_parameter(name,shape);}
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
fn pt_model(batch,length) {
    pt_tensors=h_vec();pt_parameters=h_vec();pt_actions=h_vec();pt_phases=h_vec();
    pt_images=vp_tensor(pup_shape(4,length*batch,3,84,84),0,0,0);
    pt_proprio=vp_tensor(pup_shape(3,length,batch,7,1),0,0,0);
    let zero=pup_scalar(0);let one=pup_scalar(0x3f800000);let two=pup_scalar(0x40000000);
    let encoded=pt_binary(7,pt_conv(pt_images,"encoder.0",16,8,4),zero);
    encoded=pt_binary(7,pt_conv(encoded,"encoder.2",32,4,2),zero);
    encoded=pt_binary(7,pt_conv(encoded,"encoder.4",32,3,1),zero);
    encoded=pup_reshape(encoded,pup_shape(2,length*batch,1568,1,1));
    encoded=pt_binary(7,pt_dense(encoded,"encoder.7",1568,128),zero);
    encoded=pup_reshape(encoded,pup_shape(3,length,batch,128,1));
    let hidden=vp_tensor(pup_shape(2,batch,128,1,1),0,0,0);let zeros=alloc(batch*128*4);pt_upload(load64(hidden),zeros,batch*128*4);
    let wi=pt_weight("memory.weight_ih_T",pup_shape(2,135,384,1,1));let bi=pt_weight("memory.bias_ih",pup_shape(1,384,1,1,1));
    let wh=pt_weight("memory.weight_hh_T",pup_shape(2,128,384,1,1));let bh=pt_weight("memory.bias_hh",pup_shape(1,384,1,1,1));
    let t=0;while t<length {
        let features=pup_reshape(pt_slice(encoded,0,t,1),pup_shape(2,batch,128,1,1));
        let proprio=pup_reshape(pt_slice(pt_proprio,0,t,1),pup_shape(2,batch,7,1,1));
        let combined=pt_join(features,proprio,1);
        let ix=pt_binary(3,pt_matmul(combined,wi),bi);let hx=pt_binary(3,pt_matmul(hidden,wh),bh);
        let ir=pt_slice(ix,1,0,128);let iz=pt_slice(ix,1,128,128);let inn=pt_slice(ix,1,256,128);
        let hr=pt_slice(hx,1,0,128);let hz=pt_slice(hx,1,128,128);let hn=pt_slice(hx,1,256,128);
        let r=pt_sigmoid(pt_binary(3,ir,hr));let z=pt_sigmoid(pt_binary(3,iz,hz));
        let candidate=pt_binary(4,pt_binary(5,two,pt_sigmoid(pt_binary(5,two,pt_binary(3,inn,pt_binary(5,r,hn))))),one);
        hidden=pt_binary(3,pt_binary(5,pt_binary(4,one,z),candidate),pt_binary(5,z,hidden));
        let action=pt_binary(4,pt_binary(5,two,pt_sigmoid(pt_binary(5,two,pt_dense(hidden,"actor",128,2)))),one);
        h_add(pt_actions,action);h_add(pt_phases,pt_dense(hidden,"critic",128,1));t=t+1;
    }
    let inputs=h_vec();let entry=alloc(16);store64(entry,"images");store64(entry+8,pt_images);h_add(inputs,entry);
    entry=alloc(16);store64(entry,"proprio");store64(entry+8,pt_proprio);h_add(inputs,entry);
    let outputs=h_vec();h_add(outputs,vp_at(pt_actions,length-1));vp_check(device_synchronize());pup_finish(inputs,outputs);return 0;
}
fn pt_tensor_by_data(data) {
    let i=0;while i<load64(pt_tensors) {let t=vp_at(pt_tensors,i);if load64(t)==data {return t;}i=i+1;}return 0;
}
fn pt_gradient(t) {
    if !t {return 0;}let target=load64(t);let i=0;
    while i<load64(pt_tensors) {if load64(vp_at(pt_tensors,i))==target {return pt_gradient_arena+load64(pt_optimizer_host+i*8)*4;}i=i+1;}return 0;
}
fn pt_launch(input,output,count,mode,a,b,meta) {
    let values=alloc(88);let args=alloc(88);store64(values,input);store64(values+8,output);store64(values+16,count);
    store64(values+24,mode);store64(values+32,a);store64(values+40,b);store64(values+48,meta);
    let i=0;while i<11 {store64(args+i*8,values+i*8);i=i+1;}
    let job=alloc(16);store64(job,args);store64(job+8,device_config((count+127)/128,1,1,128,1,1,0,vp_stream));return job;
}
fn pt_dispatch(job) {return vp_check(device_dispatch(pt_function,load64(job+8),load64(job)));}
fn pt_backward_job(t,parent,role) {
    let gradient=pt_gradient(parent);if !gradient {return 0;}
    let a=load64(load64(t+32));let b=0;if load64(t+40) {b=load64(load64(t+40));}
    if load64(t+24)==24 {a=load64(t);}if load64(t+24)==12 {b=load64(t+48);}
    h_add(pt_backward,pt_launch(pt_gradient(t),gradient,load64(parent+8),role,a,b,load64(t+96)));return 0;
}
fn pt_prepare(kernel_root) {
    pt_optimizer_host=alloc(load64(pt_tensors)*8);let i=0;
    while i<load64(pt_tensors) {store64(pt_optimizer_host+i*8,pt_gradient_count);pt_gradient_count=pt_gradient_count+load64(vp_at(pt_tensors,i)+8);i=i+1;}
    vp_require(pt_gradient_count<134217728,"training gradient arena exceeds 512 MiB");pt_gradient_arena=vp_buffer(pt_gradient_count*4);
    let image=vp_map(vp_path(kernel_root,"gradients.ptx"));let module=device_module(image);vp_require(module,device_error());syscall(11,image,vp_bytes,0,0,0,0);
    pt_function=device_function(module,"flex_kernel");vp_require(pt_function,device_error());
    pl_print(1,"Native gradient buffers allocated.\n");pt_zero=pt_launch(0,pt_gradient_arena,pt_gradient_count,100,0,0,0);pt_backward=h_vec();i=load64(vp_nodes);
    while i {i=i-1;let t=vp_at(vp_nodes,i);let op=load64(t+24);
        vp_require((op>=3 && op<=7) || op==12 || op==24 || op==25 || op==26 || op==29,"training operation has no backward implementation");
        pt_backward_job(t,load64(t+32),0);if load64(t+40) {pt_backward_job(t,load64(t+40),1);}
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
fn pt_step(rate) {
    vp_check(device_graph_launch(pt_backward,vp_stream));let i=0;while i<load64(pt_norm) {pt_dispatch(vp_at(pt_norm,i));i=i+1;}vp_check(device_stream_wait(vp_stream));
    let chunks=pt_norm_count;vp_check(device_download(pt_norm_host,pt_norm_device,chunks*4));let square=0;i=0;
    while i<chunks {square=f64_add(square,pb_read_float(pt_norm_host+i*4));i=i+1;}vp_require(f64_is_finite(square),"nonfinite training gradient");
    let norm=f64_sqrt(square);let scale=PB_ONE;if f64_gt(norm,PB_ONE) {scale=f64_div(PB_ONE,norm);}
    pt_beta1=f64_mul(pt_beta1,0x3feccccccccccccd);pt_beta2=f64_mul(pt_beta2,0x3feff7ced916872b);pt_adam_steps=pt_adam_steps+1;
    let meta=alloc(16);pb_put32(meta,pb_f64_to_f32(scale));pb_put32(meta+4,pb_f64_to_f32(f64_div(PB_ONE,f64_sub(PB_ONE,pt_beta1))));
    pb_put32(meta+8,pb_f64_to_f32(f64_div(PB_ONE,f64_sub(PB_ONE,pt_beta2))));pb_put32(meta+12,pb_f64_to_f32(rate));pt_upload(pt_optimizer_meta,meta,16);syscall(11,meta,16,0,0,0,0);
    i=0;while i<load64(pt_optimizer) {pt_dispatch(vp_at(pt_optimizer,i));i=i+1;}vp_check(device_stream_wait(vp_stream));return norm;
}
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
