import "../control/loss.flex";
fn rw_close(a,b) {return f64_lt(f64_magnitude(f64_sub(a,b)),vc_number(1,100000));}
fn main(argc,argv) {
    vc_init(argc,argv);let base=f64_from_i64(3);
    vc_require(rw_close(pt_return_control_weight(base,PB_ONE,1,2000),f64_from_i64(6)),"return control weight was not applied");
    vc_require(rw_close(pt_return_control_weight(base,0,1,2000),base) && rw_close(pt_return_control_weight(base,PB_ONE,0,2000),base) && rw_close(pt_return_control_weight(base,PB_ONE,1,0),base),"search, validation or default weight changed");
    vc_require(rw_close(pt_return_control_weight(0,PB_ONE,1,2000),0),"masked action received weight");
    let logits=alloc(28);let target=alloc(8);let seed=alloc(28);let scratch=alloc(28);let i=0;while i<7 {pb_put32(logits+i*4,pb_f64_to_f32(vc_number(i-3,10)));i=i+1;}pb_put32(target,ca_steering_bits(1));pb_put32(target+4,ca_speed_bits(1));
    let weight=vc_number(2,3);let value=pt_categorical_loss(logits,target,PB_ONE,weight,seed);vc_require(f64_gt(value,0),"weighted categorical loss is empty");let epsilon=vc_number(1,1000);i=0;while i<7 {let original=pb_u32(logits+i*4);let x=pb_read_float(logits+i*4);pb_put32(logits+i*4,pb_f64_to_f32(f64_add(x,epsilon)));let plus=pt_categorical_loss(logits,target,PB_ONE,weight,scratch);pb_put32(logits+i*4,pb_f64_to_f32(f64_sub(x,epsilon)));let minus=pt_categorical_loss(logits,target,PB_ONE,weight,scratch);pb_put32(logits+i*4,original);let numeric=f64_div(f64_sub(plus,minus),f64_mul(f64_from_i64(2),epsilon));vc_require(f64_lt(f64_magnitude(f64_sub(numeric,pb_read_float(seed+i*4))),vc_number(1,1000)),"return-weighted action gradient differs from finite difference");i=i+1;}
    pl_print(1,"Return control weighting, masks, validation and gradients passed.\n");return 0;
}
