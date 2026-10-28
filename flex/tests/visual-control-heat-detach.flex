// Check the intentionally detached training edge with direct gradient probes.
import "../control/training.flex";
import "../control/host.flex";
fn hd_parameter(name) {
    let i=0;while i<load64(pt_parameters) {let p=vp_at(pt_parameters,i);if pl_equal(load64(p),name) {return load64(p+8);}i=i+1;}vc_require(0,"detached-gradient parameter missing");return 0;
}
fn hd_gradient_norm(name) {
    let tensor=hd_parameter(name);let n=load64(tensor+8);let host=alloc(n*4);vp_check(device_download(host,pt_gradient(tensor),n*4));let sum=0;let i=0;while i<n {let value=pb_read_float(host+i*4);vc_require(f64_is_finite(value),"nonfinite detached-gradient probe");sum=f64_add(sum,f64_magnitude(value));i=i+1;}syscall(11,host,n*4,0,0,0,0);return sum;
}
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==3,"heat-detach KERNELS NEW_OUTPUT");let output=vc_absolute(load64(argv+16));vc_mkdir(output);vp_init(load64(argv+8),2,0);vp_checkpoint=alloc(32);vp_bytes=32;pt_scratch_init=1;pt_rng=7;pt_action_width=7;pt_event_aux=1;pt_heat_aux=1;pt_heat_actor=1;pt_heat_stop_gradient=1;pt_model(2,3);pt_prepare(load64(argv+8));
    let merge=hd_parameter("visual.merge.weight_T");let n=load64(merge+8);let values=alloc(n*4);let i=0;while i<n {pb_put32(values+i*4,pb_f64_to_f32(vc_number(i%7-3,100)));i=i+1;}pt_upload(load64(merge),values,n*4);let images=alloc(6*21168*4);i=0;while i<6*21168 {pb_put32(images+i*4,pb_f64_to_f32(vc_number((i*17+11)%251,255)));i=i+1;}pt_upload(load64(pt_images),images,6*21168*4);let feedback=alloc(6*28);pt_upload(load64(pt_proprio),feedback,6*28);vp_execute();
    pt_zero_grad();let action_seed=alloc(56);pb_put32(action_seed,0x3f800000);pb_put32(action_seed+4,0xbf000000);pb_put32(action_seed+28,0xbf800000);pt_upload(pt_gradient(vp_at(pt_actions,2)),action_seed,56);vp_check(device_graph_launch(pt_backward,vp_stream));vp_check(device_stream_wait(vp_stream));let action_heat=hd_gradient_norm("critic.heat.weight");let action_merge=hd_gradient_norm("visual.merge.weight_T");let action_encoder=hd_gradient_norm("encoder.0.weight");vc_require(!f64_magnitude(action_heat) && f64_gt(action_merge,vc_number(1,1000000000)) && f64_gt(action_encoder,vc_number(1,1000000000)),"action gradient crossed the detached heatmap edge or failed to train the actor");
    pt_zero_grad();let heat_seed=alloc(3200);pb_put32(heat_seed+200*4,0x3f800000);pb_put32(heat_seed+(400+201)*4,0xbf800000);pt_upload(pt_gradient(vp_at(pt_target_predictions,2)),heat_seed,3200);vp_check(device_graph_launch(pt_backward,vp_stream));vp_check(device_stream_wait(vp_stream));let label_heat=hd_gradient_norm("critic.heat.weight");vc_require(f64_gt(label_heat,vc_number(1,1000000000)),"heatmap label failed to train its detached head");
    let text=alloc(1024);let b=alloc(32);pl_builder(b,text,1024);pl_text(b,"{\"passed\":true,\"actionGradientIntoHeatHead\":");pl_float(b,action_heat);pl_text(b,",\"actionGradientIntoMerge\":");pl_float(b,action_merge);pl_text(b,",\"actionGradientIntoEncoder\":");pl_float(b,action_encoder);pl_text(b,",\"labelGradientIntoHeatHead\":");pl_float(b,label_heat);pl_text(b,",\"pythonRequired\":false}\n");vc_write(vc_path(output,"result.json"),text,load64(b+8));return 0;
}
