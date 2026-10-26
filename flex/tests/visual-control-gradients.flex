// Independent native finite-difference and first-Adam checks. The oracle is
// forward evaluations at perturbed weights, not another autodiff framework.
import "../control/training.flex";
import "../control/host.flex";
fn vg_loss(seeds) {
    vp_execute();let out=alloc(16);let loss=0;let t=0;
    while t<3 {
        let action=vp_at(pt_actions,t);vp_read_tensor(action,out);let i=0;
        while i<4 {let scale=vc_number((t+1)*(i+1),17);loss=f64_add(loss,f64_mul(pb_read_float(out+i*4),scale));if seeds {pb_put32(out+i*4,pb_f64_to_f32(scale));}i=i+1;}
        if seeds {pt_upload(pt_gradient(action),out,16);}
        let phase=vp_at(pt_phases,t);vp_read_tensor(phase,out);i=0;
        while i<2 {let scale=vc_number((t+1)*(i+1),11);loss=f64_add(loss,f64_mul(pb_read_float(out+i*4),scale));if seeds {pb_put32(out+i*4,pb_f64_to_f32(scale));}i=i+1;}
        if seeds {pt_upload(pt_gradient(phase),out,8);}t=t+1;
    }syscall(11,out,16,0,0,0,0);return loss;
}
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==3,"visual-control-gradients KERNEL_DIRECTORY NEW_OUTPUT_DIRECTORY");let output=vc_absolute(load64(argv+16));vc_mkdir(output);
    vp_init(load64(argv+8),2,0);vp_checkpoint=alloc(32);vp_bytes=32;pt_scratch_init=1;pt_rng=7;pt_model(2,3);let count=pt_prepare(load64(argv+8));
    let images=alloc(6*21168*4);let i=0;while i<6*21168 {pb_put32(images+i*4,pb_f64_to_f32(vc_number((i*17+11)%251,255)));i=i+1;}pt_upload(load64(pt_images),images,6*21168*4);
    let feedback=alloc(6*7*4);i=0;while i<6 {pb_put32(feedback+(i*7)*4,pb_f64_to_f32(vc_number(i-2,10)));i=i+1;}pt_upload(load64(pt_proprio),feedback,6*7*4);
    pt_zero_grad();let original_loss=vg_loss(1);vp_check(device_graph_launch(pt_backward,vp_stream));vp_check(device_stream_wait(vp_stream));
    let maxima=alloc(load64(pt_parameters)*24);let norm=0;let max_error=0;i=0;
    while i<load64(pt_parameters) {
        let p=vp_at(pt_parameters,i);let t=load64(p+8);let n=load64(t+8);let grad=alloc(n*4);vp_check(device_download(grad,pt_gradient(t),n*4));
        let best=0;let index=0;let j=0;while j<n {let value=pb_read_float(grad+j*4);vc_require(f64_is_finite(value),"nonfinite native gradient");norm=f64_add(norm,f64_mul(value,value));if f64_gt(f64_magnitude(value),f64_magnitude(best)) {best=value;index=j;}j=j+1;}
        vc_require(f64_gt(f64_magnitude(best),vc_number(1,1000000000)),"a trainable tensor received no gradient");
        let word=alloc(4);vp_check(device_download(word,load64(t)+index*4,4));let original=pb_read_float(word);let epsilon=vc_number(1,1000);
        pb_put32(word,pb_f64_to_f32(f64_add(original,epsilon)));let high_value=pb_read_float(word);pt_upload(load64(t)+index*4,word,4);let high=vg_loss(0);
        pb_put32(word,pb_f64_to_f32(f64_sub(original,epsilon)));let low_value=pb_read_float(word);pt_upload(load64(t)+index*4,word,4);let low=vg_loss(0);
        pb_put32(word,pb_f64_to_f32(original));pt_upload(load64(t)+index*4,word,4);let numeric=f64_div(f64_sub(high,low),f64_sub(high_value,low_value));let error=f64_magnitude(f64_sub(numeric,best));max_error=pb_fmax(max_error,error);
        vc_require(f64_lt(error,pb_fmax(vc_number(3,10000),f64_mul(f64_magnitude(best),vc_number(8,100)))),vc_concat("finite-difference gradient mismatch: ",load64(p)));
        store64(maxima+i*24,index);store64(maxima+i*24+8,best);store64(maxima+i*24+16,original);syscall(11,grad,n*4,0,0,0,0);syscall(11,word,4,0,0,0,0);i=i+1;
    }
    norm=f64_sqrt(norm);pt_zero_grad();vg_loss(1);let native_norm=pt_step(vc_number(1,10000));vc_require(f64_lt(f64_magnitude(f64_sub(norm,native_norm)),f64_mul(pb_fmax(norm,PB_ONE),vc_number(1,100000))),"native parameter gradient norm mismatch");
    let max_update_error=0;i=0;while i<load64(pt_parameters) {
        let t=load64(vp_at(pt_parameters,i)+8);let index=load64(maxima+i*24);let gradient=load64(maxima+i*24+8);if f64_gt(norm,PB_ONE) {gradient=f64_div(gradient,norm);}
        let expected=f64_sub(load64(maxima+i*24+16),f64_div(f64_mul(vc_number(1,10000),gradient),f64_add(f64_magnitude(gradient),vc_number(1,100000000))));
        let word=alloc(4);vp_check(device_download(word,load64(t)+index*4,4));let error=f64_magnitude(f64_sub(pb_read_float(word),expected));max_update_error=pb_fmax(max_update_error,error);vc_require(f64_lt(error,vc_number(1,1000000)),"native first Adam step mismatch");i=i+1;
    }
    let text=alloc(4096);let b=alloc(32);pl_builder(b,text,4096);pl_text(b,"{\"passed\":true,\"runtime\":\"Flexscript/Pup CUDA\",\"oracle\":\"central finite differences and independent scalar Adam\",\"pythonRequired\":false,\"parameters\":");pl_int(b,count);
    pl_text(b,",\"tensorsChecked\":");pl_int(b,load64(pt_parameters));pl_text(b,",\"sequenceLength\":3,\"batch\":2,\"fullCNNAndGRU\":true,\"maxGradientAbsError\":");pl_float(b,max_error);pl_text(b,",\"maxAdamAbsError\":");pl_float(b,max_update_error);pl_text(b,",\"initialLoss\":");pl_float(b,original_loss);pl_text(b,"}\n");vc_write(vc_path(output,"result.json"),text,load64(b+8));pl_write(1,text,load64(b+8));return 0;
}
