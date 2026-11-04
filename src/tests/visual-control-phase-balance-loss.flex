import "../control/loss.flex";
fn ps_close(a,b) {return f64_lt(f64_magnitude(f64_sub(a,b)),vc_number(1,100000));}
fn main(argc,argv) {
    vc_init(argc,argv);let one=PB_ONE;let total=f64_from_i64(4);let positive=one;let negative=f64_from_i64(3);
    let search=pt_phase_scale(one,0,total,positive,negative,1);let returning=pt_phase_scale(one,one,total,positive,negative,1);
    vc_require(ps_close(search,vc_number(1,6)) && ps_close(returning,vc_number(1,2)),"phase classes were not balanced");
    vc_require(ps_close(pt_phase_scale(0,one,total,positive,negative,1),0),"masked phase received weight");
    vc_require(ps_close(pt_phase_scale(one,0,total,0,total,1),vc_number(1,4)) && ps_close(pt_phase_scale(one,one,total,total,0,1),vc_number(1,4)),"single-class batch normalization changed");
    vc_require(ps_close(pt_phase_scale(one,one,total,positive,negative,0),vc_number(1,4)),"default phase normalization changed");
    let epsilon=vc_number(1,1000);let logit=vc_number(-1,5);let seed=alloc(4);let a=alloc(4);let b=alloc(4);pb_zero(seed,4);pb_zero(a,4);pb_zero(b,4);
    let value=pt_binary_loss(logit,one,returning,seed);let plus=pt_binary_loss(f64_add(logit,epsilon),one,returning,a);let minus=pt_binary_loss(f64_sub(logit,epsilon),one,returning,b);
    let numerical=f64_div(f64_sub(plus,minus),f64_mul(f64_from_i64(2),epsilon));vc_require(f64_gt(value,0) && f64_lt(f64_magnitude(f64_sub(numerical,pb_read_float(seed))),vc_number(1,1000)),"balanced phase gradient differs from finite difference");
    pl_print(1,"Balanced phase weights, masks, fallback and gradient passed.\n");return 0;
}
