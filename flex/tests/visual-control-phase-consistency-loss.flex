import "../control/loss.flex";
fn main(argc,argv) {
    vc_init(argc,argv);let a=alloc(4);let b=alloc(4);let ga=alloc(4);let gb=alloc(4);let epsilon=vc_number(1,1000);let offset=vc_number(1,4);let weight=vc_number(3,10);
    pb_put32(a,pb_f64_to_f32(vc_number(7,20)));pb_put32(b,pb_f64_to_f32(vc_number(-1,5)));pb_put32(ga,pb_f64_to_f32(offset));pb_put32(gb,pb_f64_to_f32(offset));
    let value=pt_phase_consistency_loss(pb_read_float(a),pb_read_float(b),weight,ga,gb);vc_require(f64_gt(value,0) && f64_lt(value,weight),"phase consistency loss is outside probability bounds");
    let side=0;while side<2 {let logit=a;let gradient=ga;if side {logit=b;gradient=gb;}let original=pb_u32(logit);let base=pb_read_float(logit);let scratch_a=alloc(4);let scratch_b=alloc(4);
        pb_put32(logit,pb_f64_to_f32(f64_add(base,epsilon)));pb_zero(scratch_a,4);pb_zero(scratch_b,4);let plus=pt_phase_consistency_loss(pb_read_float(a),pb_read_float(b),weight,scratch_a,scratch_b);
        pb_put32(logit,pb_f64_to_f32(f64_sub(base,epsilon)));pb_zero(scratch_a,4);pb_zero(scratch_b,4);let minus=pt_phase_consistency_loss(pb_read_float(a),pb_read_float(b),weight,scratch_a,scratch_b);pb_put32(logit,original);
        let numeric=f64_div(f64_sub(plus,minus),f64_mul(f64_from_i64(2),epsilon));let analytical=f64_sub(pb_read_float(gradient),offset);vc_require(f64_lt(f64_magnitude(f64_sub(numeric,analytical)),vc_number(1,1000)),"phase consistency gradient differs from finite difference");side=side+1;
    }
    let previous=alloc(16);let current=alloc(16);let pm=alloc(4);let cm=alloc(4);pb_zero(previous,16);pb_zero(current,16);pb_put32(pm,0x3f800000);pb_put32(cm,0x3f800000);vc_require(pt_phase_consistency_pair(previous,current,pm,cm),"same-phase supervised frames were not selected");
    pb_put32(current+8,0x3f800000);vc_require(!pt_phase_consistency_pair(previous,current,pm,cm),"phase transition was penalized");pb_put32(previous+8,0x3f800000);vc_require(pt_phase_consistency_pair(previous,current,pm,cm),"same return phase was not selected");pb_put32(pm,0);vc_require(!pt_phase_consistency_pair(previous,current,pm,cm),"masked predecessor was penalized");pb_put32(pm,0x3f800000);pb_put32(cm,0);vc_require(!pt_phase_consistency_pair(previous,current,pm,cm),"masked successor was penalized");
    pb_zero(ga,4);pb_zero(gb,4);let extreme=pt_phase_consistency_loss(f64_from_i64(1000),f64_from_i64(-1000),weight,ga,gb);vc_require(f64_is_finite(extreme) && f64_is_finite(pb_read_float(ga)) && f64_is_finite(pb_read_float(gb)),"extreme logits made phase consistency nonfinite");
    pl_print(1,"Phase consistency gradient, phase boundaries and mask guards passed.\n");return 0;
}
