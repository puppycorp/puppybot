// Resident native policy contracts: pixels and memory matter; explicit reset
// must reproduce the same output without process restart.
import "../control/environment.flex";
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==3,"visual-control-policy POLICY_DIRECTORY NEW_OUTPUT_DIRECTORY");let output=vc_absolute(load64(argv+16));vc_mkdir(output);ve_open_buffers();ve_policy_open(vc_absolute(load64(argv+8)),output);
    let hidden=alloc(512);let first=alloc(520);let original=alloc(21168);let i=0;while i<21168 {store8(ve_image+i,(i*17+43)%256);i=i+1;}vc_copy(original,ve_image,21168);
    ve_action(hidden,0);vc_copy(first,ve_policy_output,520);pb_zero(hidden,512);ve_action(hidden,0);i=0;while i<520 {vc_require(load8(first+i)==load8(ve_policy_output+i),"hidden state leaked across an explicit reset");i=i+1;}
    pb_zero(hidden,512);ve_action(hidden,1);let pixel_delta=pb_fmax(f64_magnitude(f64_sub(pb_read_float(first),pb_read_float(ve_policy_output))),f64_magnitude(f64_sub(pb_read_float(first+4),pb_read_float(ve_policy_output+4))));
    vc_require(f64_gt(pixel_delta,vc_number(1,10000000)),"policy output does not respond to pixels");vc_copy(hidden,first+8,512);ve_action(hidden,0);let memory_delta=pb_fmax(f64_magnitude(f64_sub(pb_read_float(first),pb_read_float(ve_policy_output))),f64_magnitude(f64_sub(pb_read_float(first+4),pb_read_float(ve_policy_output+4))));
    vc_require(f64_gt(memory_delta,vc_number(1,10000000)),"policy output does not respond to recurrent memory");i=0;while i<130 {let value=pb_read_float(ve_policy_output+i*4);vc_require(f64_is_finite(value) && f64_le(f64_magnitude(value),PB_ONE),"native action/GRU state is not finite and bounded");i=i+1;}
    vc_finish(ve_policy,15000);let text=alloc(1024);let b=alloc(32);pl_builder(b,text,1024);pl_text(b,"{\"passed\":true,\"runtime\":\"Flexscript/Pup CUDA\",\"pythonRequired\":false,\"resetBitIdentical\":true,\"boundedOutputs\":true,\"pixelActionMaxDelta\":");pl_float(b,pixel_delta);pl_text(b,",\"memoryActionMaxDelta\":");pl_float(b,memory_delta);pl_text(b,"}\n");vc_write(vc_path(output,"result.json"),text,load64(b+8));pl_write(1,text,load64(b+8));return 0;
}
