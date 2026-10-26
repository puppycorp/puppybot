// Full-episode demonstration training: data batching, CNN/GRU backward,
// gradient clipping, Adam, validation and checkpoint selection are Flexscript.
import "training.flex";
global pt_data=0;
global pt_data_size=0;
global pt_length=0;
global pt_batch=0;
global pt_record_size=0;
global pt_batch_images=0;
global pt_batch_proprio=0;
global pt_batch_targets=0;
global pt_image_job=0;
global pt_batch_device=0;
global pt_prediction=0;
global pt_phase_prediction=0;
global pt_action_seed=0;
global pt_phase_seed=0;
global pt_memcpy=0;
global pt_last_norm=0;

fn pt_log1p(x) {
    // x is exp(-abs(logit)), in [0,1]. atanh series has |y| <= 1/3.
    let y=f64_div(x,f64_add(0x4000000000000000,x));let square=f64_mul(y,y);let power=y;let sum=0;let i=1;
    while i<=31 {sum=f64_add(sum,f64_div(power,f64_from_i64(i)));power=f64_mul(power,square);i=i+2;}return f64_mul(0x4000000000000000,sum);
}
fn pt_batch_open() {
    let count=pt_batch*pt_length;pt_batch_images=alloc(count*21168);pt_batch_proprio=alloc(count*7*4);pt_batch_targets=alloc(count*4*4);
    pt_prediction=alloc(pt_batch*2*4);pt_phase_prediction=alloc(pt_batch*4);pt_action_seed=alloc(pt_batch*2*4);pt_phase_seed=alloc(pt_batch*4);
    pt_batch_device=vp_buffer(count*21168);pt_image_job=pt_launch(pt_batch_device,load64(pt_images),count*21168,103,0,0,0);
    pt_memcpy=ffi_symbol(ffi_open("libc.so.6"),"memcpy");vp_require(pt_memcpy,"memcpy is unavailable");return 0;
}
fn pt_batch_load(order,start,count) {
    let b=0;while b<pt_batch {
        let active=b<count;let episode=0;if active {episode=load64(order+(start+b)*8);}
        let base=pt_data+32+episode*pt_record_size;let t=0;
        while t<pt_length {let index=t*pt_batch+b;let values=base+pt_length*21168+t*11*4;
            let field=0;while field<11 {vp_require(f64_is_finite(pb_read_float(values+field*4)),"nonfinite demonstration value");field=field+1;}
            vp_require(!f64_magnitude(pb_read_float(values+24)),"task-event feedback must be masked during training");
            vp_require(f64_le(f64_magnitude(pb_read_float(values+28)),PB_ONE) && f64_le(f64_magnitude(pb_read_float(values+32)),PB_ONE),"demonstration action exceeds [-1,1]");
            vp_require((pb_u32(values+36)==0 || pb_u32(values+36)==0x3f800000) && (pb_u32(values+40)==0 || pb_u32(values+40)==0x3f800000),"invalid demonstration phase/mask");
            ffi_call(pt_memcpy,pt_batch_images+index*21168,base+t*21168,21168,0,0,0);
            ffi_call(pt_memcpy,pt_batch_proprio+index*7*4,values,7*4,0,0,0);
            ffi_call(pt_memcpy,pt_batch_targets+index*4*4,values+7*4,4*4,0,0,0);
            if !active {pb_put32(pt_batch_targets+(index*4+3)*4,0);}t=t+1;
        }b=b+1;
    }
    pt_upload(pt_batch_device,pt_batch_images,pt_batch*pt_length*21168);pt_dispatch(pt_image_job);vp_check(device_stream_wait(vp_stream));
    pt_upload(load64(pt_proprio),pt_batch_proprio,pt_batch*pt_length*7*4);return 0;
}
fn pt_loss(training,rate) {
    vp_execute();if training {pt_zero_grad();}
    let weights=0;let valid=0;let index=0;
    while index<pt_batch*pt_length {
        let target=pt_batch_targets+index*16;let mask=pb_read_float(target+12);let weight=mask;
        if f64_lt(f64_magnitude(pb_read_float(target+4)),0x3f847ae147ae147b) {weight=f64_mul(mask,0x4014000000000000);}
        weights=f64_add(weights,weight);valid=f64_add(valid,mask);index=index+1;
    }
    vp_require(f64_gt(weights,0) && f64_gt(valid,0),"empty training batch");let loss=0;let t=0;
    while t<pt_length {
        let action=vp_at(pt_actions,t);let phase=vp_at(pt_phases,t);vp_read_tensor(action,pt_prediction);vp_read_tensor(phase,pt_phase_prediction);let b=0;
        while b<pt_batch {
            let target=pt_batch_targets+(t*pt_batch+b)*16;let mask=pb_read_float(target+12);let weight=mask;
            if f64_lt(f64_magnitude(pb_read_float(target+4)),0x3f847ae147ae147b) {weight=f64_mul(mask,0x4014000000000000);}
            let axis=0;while axis<2 {
                let delta=f64_sub(pb_read_float(pt_prediction+(b*2+axis)*4),pb_read_float(target+axis*4));let scale=PB_ONE;if !axis {scale=0x4020000000000000;}
                let weighted=f64_div(f64_mul(weight,scale),weights);loss=f64_add(loss,f64_mul(f64_mul(delta,delta),weighted));
                pb_put32(pt_action_seed+(b*2+axis)*4,pb_f64_to_f32(f64_mul(0x4000000000000000,f64_mul(delta,weighted))));axis=axis+1;
            }
            let logit=pb_read_float(pt_phase_prediction+b*4);let label=pb_read_float(target+8);let scale=f64_div(mask,valid);
            let exp=f64_exp(pb_neg(f64_magnitude(logit)));let positive=pb_fmax(logit,0);
            loss=f64_add(loss,f64_mul(scale,f64_add(f64_sub(positive,f64_mul(logit,label)),pt_log1p(exp))));
            let sigmoid=f64_div(PB_ONE,f64_add(PB_ONE,exp));if f64_lt(logit,0) {sigmoid=f64_mul(exp,sigmoid);}
            pb_put32(pt_phase_seed+b*4,pb_f64_to_f32(f64_mul(scale,f64_sub(sigmoid,label))));b=b+1;
        }
        if training {pt_upload(pt_gradient(action),pt_action_seed,pt_batch*2*4);pt_upload(pt_gradient(phase),pt_phase_seed,pt_batch*4);}t=t+1;
    }
    vp_require(f64_is_finite(loss),"nonfinite training loss");if training {pt_last_norm=pt_step(rate);}return loss;
}
fn pt_order_file(path,order,count) {
    let fd=syscall(2,path,577,420,0,0,0);vp_require(fd>=0 && !pl_write(fd,order,count*8),"cannot record training split/order");return syscall(3,fd,0,0,0,0,0);
}
fn pt_log_epoch(fd,epoch,training,validation,best,milliseconds) {
    let out=alloc(1024);let builder=alloc(32);pl_builder(builder,out,1024);
    pl_text(builder,"{\"epoch\":");pl_int(builder,epoch);pl_text(builder,",\"trainingLoss\":");pl_float(builder,training);
    pl_text(builder,",\"validationLoss\":");pl_float(builder,validation);pl_text(builder,",\"selected\":");pl_text(builder,"false");
    if best {store64(builder+8,load64(builder+8)-5);pl_text(builder,"true");}
    pl_text(builder,",\"optimizerSteps\":");pl_int(builder,pt_adam_steps);pl_text(builder,",\"gradientNorm\":");pl_float(builder,pt_last_norm);
    pl_text(builder,",\"elapsedMilliseconds\":");pl_int(builder,milliseconds);pl_text(builder,"}\n");
    vp_require(!load64(builder+24) && !pl_write(fd,out,load64(builder+8)),"cannot record training curve");pl_write(1,out,load64(builder+8));
    syscall(11,out,1024,0,0,0,0);syscall(11,builder,32,0,0,0,0);return 0;
}
fn main(argc,argv) {
    if !pl_init() || (argc!=10 && argc!=11) {pl_print(2,"train WEIGHTS SHA KERNELS DATA OUTPUT EPOCHS BATCH LR_MICROS SEED [--random]\n");return 2;}
    let output=load64(argv+40);let epochs=pl_integer(load64(argv+48),pl_size(load64(argv+48)));vp_require(!pl_bad_number && epochs>=0 && epochs<=10000,"invalid epoch count");
    pt_batch=pl_integer(load64(argv+56),pl_size(load64(argv+56)));vp_require(!pl_bad_number && pt_batch>=1 && pt_batch<=8,"invalid batch size");
    let micros=pl_integer(load64(argv+64),pl_size(load64(argv+64)));vp_require(!pl_bad_number && micros>=1 && micros<=10000,"invalid learning rate");
    let seed=pl_integer(load64(argv+72),pl_size(load64(argv+72)));vp_require(!pl_bad_number && seed>=0 && seed<=2147483647,"invalid random seed");pt_rng=seed;
    if argc==11 {vp_require(pl_equal(load64(argv+80),"--random"),"unknown training option");pt_scratch_init=1;}
    pt_data=vp_map(load64(argv+32));pt_data_size=vp_bytes;
    vp_require(load64(pt_data)==0x3130415441445650,"invalid visual demonstration data");let episodes=load64(pt_data+8);let training_count=load64(pt_data+16);pt_length=load64(pt_data+24);
    vp_require(episodes>=2 && episodes<=256 && training_count>=1 && training_count<episodes && pt_length>=1 && pt_length<=64,"invalid demonstration dimensions");
    pt_record_size=pt_length*(21168+44);vp_require(pt_data_size==32+episodes*pt_record_size,"truncated demonstration data");
    vp_init(load64(argv+24),2,0);vp_checkpoint_open(load64(argv+8),load64(argv+16));pl_print(1,"Building native training graph.\n");
    pt_model(pt_batch,pt_length);pl_print(1,"Preparing native backward graph.\n");let parameters=pt_prepare(load64(argv+24));pt_batch_open();pl_print(1,"Native training graphs ready.\n");
    let order=alloc(episodes*8);let i=0;while i<episodes {store64(order+i*8,i);i=i+1;}
    let curve=syscall(2,vp_path(output,"curves.jsonl"),577,420,0,0,0);vp_require(curve>=0,"cannot create training curve");
    let rate=f64_div(f64_from_i64(micros),0x412e848000000000);let started=pl_now();let best=0x7ff0000000000000;let epoch=0;
    pt_save(vp_path(output,"initial.bin"),0);pt_batch_load(order,0,pb_min(pt_batch,training_count));let initial=pt_loss(0,rate);
    let repeated=pt_loss(0,rate);vp_require(f64_lt(f64_magnitude(f64_sub(initial,repeated)),0x3eb0c6f7a0b5ed8d),"initial forward is not repeatable");
    pt_batch_load(order,0,pb_min(pt_batch,training_count));repeated=pt_loss(0,rate);
    vp_require(f64_lt(f64_magnitude(f64_sub(initial,repeated)),0x3eb0c6f7a0b5ed8d),"reloading the same batch changes the forward pass");
    let initial_validation=0;let initial_batches=0;i=training_count;
    while i<episodes {pt_batch_load(order,i,pb_min(pt_batch,episodes-i));initial_validation=f64_add(initial_validation,pt_loss(0,rate));initial_batches=initial_batches+1;i=i+pt_batch;}
    pt_log_epoch(curve,0,initial,f64_div(initial_validation,f64_from_i64(initial_batches)),0,pl_now()-started);
    while epoch<epochs {
        i=training_count;while i>1 {i=i-1;let j=pt_random()%(i+1);let a=load64(order+i*8);store64(order+i*8,load64(order+j*8));store64(order+j*8,a);}
        let total=0;let batches=0;let start=0;
        while start<training_count {let count=pb_min(pt_batch,training_count-start);pt_batch_load(order,start,count);
            if !pt_adam_steps {pt_order_file(vp_path(output,"first-order.bin"),order,episodes);}
            total=f64_add(total,pt_loss(1,rate));batches=batches+1;
            if pt_adam_steps==1 {pt_save(vp_path(output,"first-after.bin"),0);pt_save(vp_path(output,"first-gradients.bin"),1);}
            start=start+pt_batch;
        }
        let validation=0;let validation_batches=0;start=training_count;
        while start<episodes {pt_batch_load(order,start,pb_min(pt_batch,episodes-start));validation=f64_add(validation,pt_loss(0,rate));validation_batches=validation_batches+1;start=start+pt_batch;}
        validation=f64_div(validation,f64_from_i64(validation_batches));let selected=f64_lt(validation,best);
        if selected {best=validation;pt_save(vp_path(output,"weights.bin"),0);}
        epoch=epoch+1;pt_log_epoch(curve,epoch,f64_div(total,f64_from_i64(batches)),validation,selected,pl_now()-started);
    }
    pt_save(vp_path(output,"last.bin"),0);pt_order_file(vp_path(output,"final-order.bin"),order,episodes);syscall(3,curve,0,0,0,0,0);
    pl_print(1,"Native Flexscript CNN/GRU training complete. Parameters: ");let b=alloc(32);let s=alloc(64);pl_builder(b,s,64);pl_int(b,parameters);pl_text(b,"\n");pl_write(1,s,load64(b+8));return 0;
}
