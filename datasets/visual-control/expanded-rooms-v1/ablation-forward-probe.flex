// Compare original neutral-feedback inference with the weight ablation.
import "../../../flex/control/verify.flex";
fn ap_open(policy,output,name) {
    let meta=vc_json_file(vc_path(policy,"receipt.json"));let sha=vc_string(pj_string_field(meta,"weightsSHA256"));
    vc_require(vc_json_int(meta,"memoryWidth",0)==256 && !pj_boolean(meta,"taskFeedback") && pl_equal(vc_file_sha(vc_path(policy,"weights.bin")),sha) && pl_equal(vc_file_sha(vc_path(policy,"policy")),pj_string_field(meta,"binarySHA256")),"ablation probe policy hash mismatch");
    let args=vc_args();vc_add(args,vc_path(policy,"policy"));vc_add(args,vc_path(policy,"weights.bin"));vc_add(args,sha);vc_add(args,vc_path(policy,"kernels"));vc_add(args,"3");vc_add(args,"--raw");let process=vc_spawn(args,vc_path(output,name),0,1);let magic=alloc(8);vc_io(1,load64(process+8),magic,8);vc_require(load64(magic)==load64("VCR25601"),"invalid ablation probe handshake");return process;
}
fn ap_infer(process,input,output) {vc_io(0,load64(process+8),input,(21168+7+256)*4);vc_io(1,load64(process+8),output,263*4);return 0;}
fn main(argc,argv) {
    vc_init(argc,argv);vc_pixels_init();vc_require(argc==6,"ablation-forward-probe ORIGINAL_POLICY ABLATED_POLICY ACTOR_RGB ACTOR_FEEDBACK NEW_OUTPUT");
    let original=vc_absolute(load64(argv+8));let ablated=vc_absolute(load64(argv+16));let rgb_path=vc_absolute(load64(argv+24));let feedback_path=vc_absolute(load64(argv+32));let output=vc_absolute(load64(argv+40));vc_mkdir(output);
    let image=vc_map(rgb_path);vc_require(vc_size==21168,"invalid probe image");let feedback=vc_map(feedback_path);vc_require(vc_size==28 && !pb_u32(feedback+24),"invalid probe feedback");
    let hidden=alloc(1024);pb_zero(hidden,1024);let input=alloc((21168+7+256)*4);let before=alloc(263*4);let after=alloc(263*4);let neutral=alloc(263*4);
    let a=ap_open(original,output,"original.log");let b=ap_open(ablated,output,"ablated.log");vc_policy_input_dimensions(image,feedback,hidden,input,0,21168,256);
    let i=0;while i<5 {pb_put32(input+(21168+i)*4,0);i=i+1;}ap_infer(a,input,before);ap_infer(b,input,neutral);
    pb_put32(input+21168*4,pb_f64_to_f32(vc_number(6,10)));pb_put32(input+(21168+1)*4,pb_f64_to_f32(PB_ONE));pb_put32(input+(21168+2)*4,pb_f64_to_f32(vc_number(3,10)));pb_put32(input+(21168+3)*4,pb_f64_to_f32(vc_number(-3,10)));pb_put32(input+(21168+4)*4,pb_f64_to_f32(vc_number(8,10)));ap_infer(b,input,after);
    let max_original=0;let max_ablated=0;i=0;while i<263 {max_original=pb_fmax(max_original,f64_magnitude(f64_sub(pb_read_float(before+i*4),pb_read_float(after+i*4))));max_ablated=pb_fmax(max_ablated,f64_magnitude(f64_sub(pb_read_float(neutral+i*4),pb_read_float(after+i*4))));i=i+1;}
    vc_require(f64_lt(max_original,vc_number(1,100000)) && f64_lt(max_ablated,vc_number(1,100000)),"ablation does not reproduce neutral drive feedback");vc_finish(a,15000);vc_finish(b,15000);
    let text=alloc(1024);let out=alloc(32);pl_builder(out,text,1024);pl_text(out,"{\"passed\":true,\"cameraInputUnchanged\":true,\"contactInputUnchanged\":true,\"initialMemoryIdentical\":true,\"outputCount\":263,\"originalNeutralVsAblatedError\":");pl_float(out,max_original);pl_text(out,",\"ablatedDriveVariationError\":");pl_float(out,max_ablated);pl_text(out,",\"singleFrameOnly\":true,\"closedLoopPerformanceNotMeasured\":true}\n");vc_require(!load64(out+24),"probe output overflow");vc_write(vc_path(output,"result.json"),text,load64(out+8));return 0;
}
