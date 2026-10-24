// Synchronized resident inference for any linked Pup factory and its bindings.
import "runtime.flex";
import "../../build/flex/detector-model.flex";
fn bm_now() {syscall(228,1,pl_clock,0,0,0,0);return load64(pl_clock)*1000000000+load64(pl_clock+8);}
fn main(argc,argv) {
    pl_init();if argc<7 {pl_print(2,"Usage: pup-benchmark BACKEND KERNELDIR WEIGHTS.bin WEIGHTS_SHA256 OUTPUT.bin INPUT.bin [INPUT.bin...]\n");return 2;}
    vp_init(load64(argv+16),vp_backend_parse(load64(argv+8)),0);vp_checkpoint_open(load64(argv+24),load64(argv+32));pup_build_model();vp_require(argc==6+load64(vp_inputs),"provide one FP32 input file per model binding");
    let i=0;while i<load64(vp_inputs) {let t=vp_at(vp_at(vp_inputs,i),1);let bytes=load64(t+8)*4;let data=alloc(bytes+1);vp_require(pl_read_file(load64(argv+(6+i)*8),data,bytes+1)==bytes,"input tensor size differs from model binding");vp_upload(load64(t),data,bytes);i=i+1;}
    // Iteration count alone can finish before an idle GPU reaches active clocks.
    let start=bm_now();i=0;while i<10 || bm_now()-start<500000000 {vp_execute();i=i+1;}
    let samples=alloc(30*8);i=0;while i<30 {start=bm_now();vp_execute();store64(samples+i*8,bm_now()-start);i=i+1;}
    let text=alloc(4096);let builder=alloc(32);pl_builder(builder,text,4096);pl_text(builder,"[");i=0;while i<30 {if i {pl_text(builder,",");}pl_uint(builder,load64(samples+i*8));i=i+1;}pl_text(builder,"]\n");pl_print(1,text);
    let bytes=0;i=0;while i<load64(vp_outputs) {bytes=bytes+load64(vp_at(vp_outputs,i)+8)*4;i=i+1;}let output=alloc(bytes);let offset=0;i=0;
    while i<load64(vp_outputs) {let t=vp_at(vp_outputs,i);vp_read_tensor(t,output+offset);offset=offset+load64(t+8)*4;i=i+1;}return pl_atomic_file(load64(argv+40),output,bytes);
}
