import "sampling.flex";
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==2,"sampling-tests OUTPUT_JSON");let logits=alloc(28);let output=alloc(8);let i=0;
    while i<7 {let selected=ps_quantile(logits,output,vc_number(i*2+1,14),PB_ONE);vc_require(selected==i && ca_class(pb_read_float(output),pb_read_float(output+4))==i,"uniform quantile maps to wrong joint action");i=i+1;}
    vc_require(ps_quantile(logits,output,pb_neg(PB_ONE),PB_ONE)== -1 && ps_quantile(logits,output,PB_ONE,PB_ONE)== -1 && ps_quantile(logits,output,0,0)== -1,"invalid sampling parameters accepted");
    pb_put32(logits,0x7fc00000);vc_require(ps_quantile(logits,output,0,PB_ONE)== -1,"nonfinite logit accepted");pb_put32(logits,0);i=0;while i<7 {pb_put32(logits+i*4,pb_f64_to_f32(vc_number(-1000,1)));i=i+1;}pb_put32(logits+16,pb_f64_to_f32(vc_number(1000,1)));vc_require(ps_quantile(logits,output,0,PB_ONE)==4 && ps_quantile(logits,output,vc_number(999999,1000000),PB_ONE)==4,"stable softmax failed on extreme logits");
    pb_put32(logits+16,pb_f64_to_f32(vc_number(-1000,1)));pb_put32(logits,0);pb_put32(logits+4,pb_f64_to_f32(0x3fe62e42fefa39ef));vc_require(ps_quantile(logits,output,vc_number(1,4),PB_ONE)==0 && ps_quantile(logits,output,vc_number(1,4),vc_number(2,1))==1,"lower temperature did not sharpen action probabilities");
    i=0;while i<7 {pb_put32(logits+i*4,0);i=i+1;}let counts=alloc(56);let expected=alloc(256*8);let hidden=alloc(512);vc_require(ps_reset(hidden),"zero memory did not reset sampler");i=0;
    while i<10000 {let kind=ps_decode(logits,output);vc_require(kind>=0 && kind<7,"sampled action is outside action table");let p=counts+kind*8;store64(p,load64(p)+1);if i<256 {store64(expected+i*8,kind);}i=i+1;}
    i=0;while i<7 {vc_require(load64(counts+i*8)>=1200 && load64(counts+i*8)<=1650,"uniform sampling distribution is biased");i=i+1;}ps_reset(hidden);i=0;while i<256 {vc_require(ps_decode(logits,output)==load64(expected+i*8),"reset did not reproduce sampled action sequence");i=i+1;}
    let before=ps_rng;pb_put32(hidden,0x3f800000);vc_require(!ps_reset(hidden) && ps_rng==before,"nonzero recurrent memory reset RNG");ps_inverse_temperature=0;vc_require(ps_decode(logits,output)==0,"greedy tie behavior changed");
    vc_save_text(load64(argv+8),"{\"passed\":true,\"runtime\":\"Flexscript\",\"pythonRequired\":false,\"uniformDistributionChecked\":true,\"invalidParametersRejected\":true,\"extremeLogitsStable\":true,\"jointActionTablePreserved\":true,\"episodeResetReplaysExactly\":true,\"greedyTieBehaviorPreserved\":true}\n");return 0;
}
