import "../control/loss.flex";
fn main(argc,argv) {
    vc_init(argc,argv);let a=alloc(28);let b=alloc(28);let ga=alloc(28);let gb=alloc(28);let scratch=alloc(112);let i=0;
    while i<7 {pb_put32(a+i*4,pb_f64_to_f32(vc_number(i-3,3)));pb_put32(b+i*4,pb_f64_to_f32(vc_number(2-i,4)));pb_put32(ga+i*4,pb_f64_to_f32(vc_number(1,4)));pb_put32(gb+i*4,pb_f64_to_f32(vc_number(1,4)));i=i+1;}
    let value=pt_reversal_loss(a,b,vc_number(3,10),ga,gb,scratch);vc_require(f64_gt(value,0) && f64_lt(value,vc_number(3,10)),"reversal loss is outside its probability bounds");
    let numerical_a=alloc(28);let numerical_b=alloc(28);let side=0;while side<2 {i=0;while i<7 {let logits=a;let gradient=ga;if side {logits=b;gradient=gb;}let original=pb_u32(logits+i*4);let base=pb_read_float(logits+i*4);let epsilon=vc_number(1,1000);
        pb_put32(logits+i*4,pb_f64_to_f32(f64_add(base,epsilon)));pb_zero(numerical_a,28);pb_zero(numerical_b,28);let plus=pt_reversal_loss(a,b,vc_number(3,10),numerical_a,numerical_b,scratch);
        pb_put32(logits+i*4,pb_f64_to_f32(f64_sub(base,epsilon)));pb_zero(numerical_a,28);pb_zero(numerical_b,28);let minus=pt_reversal_loss(a,b,vc_number(3,10),numerical_a,numerical_b,scratch);pb_put32(logits+i*4,original);
        let numeric=f64_div(f64_sub(plus,minus),f64_mul(f64_from_i64(2),epsilon));let analytical=f64_sub(pb_read_float(gradient+i*4),vc_number(1,4));vc_require(f64_lt(f64_magnitude(f64_sub(numeric,analytical)),vc_number(1,1000)),"reversal loss gradient differs from finite difference");i=i+1;}side=side+1;}
    let previous=alloc(16);let current=alloc(16);pb_put32(previous+4,0x3f800000);pb_put32(current+4,0x3f800000);pb_put32(previous+12,0x3f800000);pb_put32(current+12,0x3f800000);vc_require(pt_reversal_pair(previous,current),"matching teacher directions were not selected");
    pb_put32(current+4,0xbf800000);vc_require(!pt_reversal_pair(previous,current),"teacher-requested reversal was penalized");pb_put32(current+4,0);vc_require(!pt_reversal_pair(previous,current),"teacher stop was penalized");pb_put32(current+4,0x3f800000);pb_put32(current+8,0x3f800000);vc_require(!pt_reversal_pair(previous,current),"phase transition was penalized");pb_put32(current+8,0);pb_put32(previous+12,0);vc_require(!pt_reversal_pair(previous,current),"masked predecessor was penalized");
    pl_print(1,"Reversal loss gradient and teacher-transition guards passed.\n");return 0;
}
